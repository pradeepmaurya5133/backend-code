"""Process-wide singletons so every router shares one security context.

Without this each router built its own PermissionGate, and a grant made through
one API had no effect on another.
"""

from app.core.agent import Agent
from app.core.config import settings
from app.core.conversations import ConversationService
from app.core.scheduler import Scheduler
from app.db.repository import ApiKeyRepository, AuditRepository, MemoryRepository, TaskRepository
from app.llm.factory import build_provider
from app.security.audit import AuditLog
from app.security.confirmations import ConfirmationStore
from app.security.crypto import Crypto, hash_api_key, new_api_key
from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.services.memory import MemoryService
from app.services.secrets import SecretService
from app.tools.registry import ToolRegistry
from app.voice.pipeline import VoicePipeline

# --- security context ---
permissions = PermissionGate()
workspace = WorkspacePolicy()
confirmations = ConfirmationStore()
crypto = Crypto(settings.data_encryption_key, settings.secret_key)

# --- persistence ---
memory_repository = MemoryRepository()
audit_repository = AuditRepository()
task_repository = TaskRepository()
api_key_repository = ApiKeyRepository()

secrets = SecretService(crypto)
memory = MemoryService(memory_repository)
conversations = ConversationService()
audit = AuditLog(repository=audit_repository)

# --- tools ---
registry = ToolRegistry(
    permissions=permissions,
    workspace=workspace,
    confirmations=confirmations,
    audit=audit,
    memory_repository=memory_repository,
    secrets=secrets,
    allowed_api_hosts=settings.allowed_api_hosts,
    web_timeout=settings.web_timeout_seconds,
    web_max_bytes=settings.web_max_bytes,
)

# --- agent ---
provider = build_provider()
agent = Agent(
    permissions=permissions,
    workspace=workspace,
    confirmations=confirmations,
    audit=audit,
    provider=provider,
    conversations=conversations,
    memory=memory,
    registry=registry,
    max_iterations=settings.llm_max_iterations,
    agent_name=settings.agent_name,
    retry_backoff_seconds=1.0,
)

voice = VoicePipeline(agent, mode=settings.voice_mode)
scheduler = Scheduler(
    agent,
    repository=task_repository,
    audit=audit,
    tick_seconds=settings.scheduler_tick_seconds,
    backoff_seconds=settings.task_retry_backoff_seconds,
)


class ApiKeyService:
    """Issues and verifies operator API keys. Only hashes are stored."""

    def __init__(self, repository: ApiKeyRepository, secret_key: str):
        self.repository = repository
        self.secret_key = secret_key

    async def issue(self, label: str, scopes: list[str]) -> dict:
        key = new_api_key()
        record = await self.repository.add(label, hash_api_key(key, self.secret_key), ",".join(scopes))
        # The plaintext key is returned exactly once and never stored.
        return {**record, "api_key": key}

    async def verify(self, key: str) -> dict | None:
        return await self.repository.find(hash_api_key(key, self.secret_key))

    async def list(self) -> list[dict]:
        return await self.repository.list()

    async def revoke(self, key_id: int) -> bool:
        return await self.repository.revoke(key_id)

    async def count(self) -> int:
        return await self.repository.count()


api_keys = ApiKeyService(api_key_repository, settings.secret_key)


def llm_status() -> dict:
    return {
        "agent_name": settings.agent_name,
        "provider": provider.name,
        "configured": provider.configured,
        "model": settings.llm_model if provider.configured else None,
        "effort": settings.llm_effort if provider.configured else None,
        "max_iterations": settings.llm_max_iterations,
    }


def set_provider(new_provider):
    """Swap the LLM provider at runtime. Used by tests."""
    global provider
    provider = new_provider
    agent.provider = new_provider
    agent.planner.provider = new_provider
