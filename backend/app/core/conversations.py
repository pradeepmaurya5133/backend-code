"""Conversation state, persisted to the database.

Earlier phases kept this in a process dict, which meant a restart lost every
chat and a suspended approval could never be resumed. It now lives in the
`conversations` / `messages` tables, so history and parked turns survive both a
restart and a different worker picking up the resume call.

A turn suspends when a tool needs human approval. Because approval arrives on a
later request, the in-flight turn - results already gathered, the call awaiting
approval, and the calls still queued - is serialised into `conversations.suspended`.
"""

from dataclasses import asdict, dataclass, field

from app.db.repository import ConversationRepository

HISTORY_LIMIT = 60


@dataclass
class SuspendedTurn:
    """An agent turn paused mid-way, waiting on a confirmation token."""

    completed_results: list[dict] = field(default_factory=list)
    pending_call: dict | None = None
    queued_calls: list[dict] = field(default_factory=list)
    confirmation_token: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None):
        if not data:
            return None
        return cls(
            completed_results=data.get("completed_results") or [],
            pending_call=data.get("pending_call"),
            queued_calls=data.get("queued_calls") or [],
            confirmation_token=data.get("confirmation_token"),
        )


class ConversationService:
    def __init__(self, repository: ConversationRepository = None, history_limit: int = HISTORY_LIMIT):
        self.repository = repository if repository is not None else ConversationRepository()
        self.history_limit = history_limit

    async def history(self, session_id: str) -> list[dict]:
        """Replayable message list, already cleaned of orphaned tool results."""
        return await self.repository.history(session_id, limit=self.history_limit)

    async def transcript(self, session_id: str) -> list[dict]:
        return await self.repository.transcript(session_id)

    async def add_user(self, session_id: str, text: str):
        await self.repository.add_message(session_id, "user", text=text)

    async def add_assistant(self, session_id: str, blocks: list, text: str = ""):
        # Blocks are stored verbatim so thinking and tool_use survive the replay.
        await self.repository.add_message(session_id, "assistant", text=text, blocks=blocks)

    async def add_tool_results(self, session_id: str, results: list[dict]):
        # One message holding every tool_result for the turn, as the API requires.
        await self.repository.add_message(session_id, "user", text="", blocks=results)

    async def get_suspended(self, session_id: str) -> SuspendedTurn | None:
        return SuspendedTurn.from_dict(await self.repository.get_suspended(session_id))

    async def set_suspended(self, session_id: str, suspended: SuspendedTurn | None):
        await self.repository.set_suspended(session_id, suspended.to_dict() if suspended else None)

    async def set_plan(self, session_id: str, plan: list):
        await self.repository.set_plan(session_id, plan)

    async def sessions(self) -> list[dict]:
        return await self.repository.sessions()

    async def reset(self, session_id: str) -> bool:
        return await self.repository.reset(session_id)
