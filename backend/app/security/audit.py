"""Audit trail.

Keeps a fast in-memory ring for the current process and, when a repository is
attached, mirrors every entry to the database so history survives a restart.
The database write is fire-and-forget: an audit outage must not take a tool call
down with it.
"""

import asyncio
import contextlib
from collections import deque
from datetime import datetime, timezone

MAX_ENTRIES = 500


class AuditLog:
    def __init__(self, max_entries: int = MAX_ENTRIES, repository=None):
        self._entries = deque(maxlen=max_entries)
        self.repository = repository
        self._pending: set[asyncio.Task] = set()

    def record(self, user_id: str, action: str, status: str, detail: dict = None) -> dict:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "action": action,
            "status": status,
        }
        if detail:
            entry["detail"] = detail
        self._entries.append(entry)
        self._persist(user_id, action, status, detail)
        return entry

    def _persist(self, actor: str, action: str, status: str, detail: dict | None):
        if self.repository is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Called from sync context with no loop - the in-memory ring still has it.
            return
        task = loop.create_task(self._write(actor, action, status, detail))
        # Hold a reference so the task is not garbage collected mid-flight.
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _write(self, actor: str, action: str, status: str, detail: dict | None):
        with contextlib.suppress(Exception):
            await self.repository.record(actor, action, status, detail)

    def entries(self, limit: int = 50) -> list[dict]:
        return list(self._entries)[-limit:][::-1]

    async def durable_entries(self, limit: int = 50, status: str = None) -> list[dict]:
        if self.repository is None:
            return self.entries(limit)
        return await self.repository.entries(limit, status)

    async def flush(self):
        """Await outstanding database writes. Used by tests and shutdown."""
        if self._pending:
            await asyncio.gather(*list(self._pending), return_exceptions=True)

    def __len__(self):
        return len(self._entries)
