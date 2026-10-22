"""Lets the agent write to and read from its own long-term memory.

Separate from conversation history: history is the current chat, memory is what
should survive it. `fact` entries are injected into the system prompt on later
turns, which is why writing one is permission-gated - it changes how the agent
behaves in future sessions.
"""

from app.security.permissions import PermissionGate
from app.tools.base import Tool

MAX_CONTENT_CHARS = 2_000


class MemoryTool(Tool):
    name = "memory"
    description = (
        "Store or recall long-term memory that outlives this conversation. Use "
        "operation 'remember' with kind 'fact' for durable preferences or facts about "
        "the user (these are shown to you in future sessions), or kind 'episodic' for a "
        "record of something that happened. Use 'recall' to list recent memories and "
        "'search' to find ones matching a term. Do not store secrets or credentials."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["remember", "recall", "search", "forget"]},
            "content": {"type": "string", "description": "What to remember. Required for 'remember'."},
            "kind": {
                "type": "string",
                "enum": ["fact", "episodic"],
                "description": "'fact' persists into future system prompts; 'episodic' is a log entry.",
            },
            "importance": {
                "type": "number",
                "description": "0.0-1.0. Higher-importance facts are surfaced first.",
            },
            "term": {"type": "string", "description": "Search term for 'search'."},
            "memory_id": {"type": "integer", "description": "Id to remove for 'forget'."},
        },
        "required": ["operation"],
    }
    permissions_required = {"memory.read", "memory.write"}

    def __init__(self, permissions: PermissionGate = None, repository=None):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.repository = repository
        # Set per-request by the agent so memory is scoped to the conversation.
        self.session_id = "default"

    async def execute(self, arguments: dict) -> dict:
        operation = arguments.get("operation", "recall")
        if self.repository is None:
            return {"tool": self.name, "status": "memory_unavailable"}

        writing = operation in ("remember", "forget")
        permission = "memory.write" if writing else "memory.read"
        if not self.permissions.allowed(permission):
            return {"tool": self.name, "status": "permission_required", "permission": permission}

        if operation == "remember":
            content = (arguments.get("content") or "").strip()
            if not content:
                return {"tool": self.name, "status": "missing_content"}
            kind = arguments.get("kind") or "episodic"
            if kind not in ("fact", "episodic"):
                return {"tool": self.name, "status": "unsupported_kind", "kind": kind}
            importance = arguments.get("importance")
            importance = 0.5 if importance is None else max(0.0, min(1.0, float(importance)))
            memory_id = await self.repository.remember(
                self.session_id, content[:MAX_CONTENT_CHARS], kind=kind, importance=importance
            )
            return {"tool": self.name, "status": "ok", "id": memory_id, "kind": kind}

        if operation == "recall":
            kind = arguments.get("kind")
            return {
                "tool": self.name,
                "status": "ok",
                "memories": await self.repository.recall(self.session_id, kind=kind),
            }

        if operation == "search":
            term = (arguments.get("term") or "").strip()
            if not term:
                return {"tool": self.name, "status": "missing_term"}
            return {
                "tool": self.name,
                "status": "ok",
                "matches": await self.repository.search(self.session_id, term),
            }

        if operation == "forget":
            memory_id = arguments.get("memory_id")
            if memory_id is None:
                return {"tool": self.name, "status": "missing_memory_id"}
            removed = await self.repository.forget(int(memory_id))
            return {"tool": self.name, "status": "ok" if removed else "not_found"}

        return {"tool": self.name, "status": "unsupported_operation", "operation": operation}
