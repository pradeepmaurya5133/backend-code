"""Data access for Subh AI.

Each repository opens its own short-lived session so callers (tools, the agent
loop, the scheduler) never share a transaction across an await boundary.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, desc, func, select

from app.db.models import (
    ApiKey,
    AuditEntry,
    Conversation,
    Memory,
    Message,
    Secret,
    Task,
    TaskRun,
)
from app.db.session import session_factory


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ConversationRepository:
    async def get_or_create(self, session_id: str) -> Conversation:
        async with session_factory()() as db:
            row = await db.scalar(select(Conversation).where(Conversation.session_id == session_id))
            if row is None:
                row = Conversation(session_id=session_id)
                db.add(row)
                await db.commit()
                await db.refresh(row)
            return row

    async def history(self, session_id: str, limit: int = 60) -> list[dict]:
        """Replayable message list for the LLM, oldest first."""
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation is None:
                return []
            rows = (
                await db.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(desc(Message.id))
                    .limit(limit)
                )
            ).all()

        messages = []
        for row in reversed(rows):
            # Blocks are the provider-native content; fall back to plain text.
            messages.append({"role": row.role, "content": row.blocks if row.blocks else row.text})
        return _drop_orphaned_tool_results(messages)

    async def transcript(self, session_id: str, limit: int = 100) -> list[dict]:
        """Human-readable chat log for a UI."""
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation is None:
                return []
            rows = (
                await db.scalars(
                    select(Message)
                    .where(Message.conversation_id == conversation.id)
                    .order_by(Message.id)
                    .limit(limit)
                )
            ).all()
        return [
            {
                "role": r.role,
                "text": r.text,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
            if r.text
        ]

    async def add_message(self, session_id: str, role: str, text: str = "", blocks: list = None):
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation is None:
                conversation = Conversation(session_id=session_id)
                db.add(conversation)
                await db.flush()
            if role == "user" and not conversation.title and text:
                conversation.title = text[:120]
            db.add(Message(conversation_id=conversation.id, role=role, text=text, blocks=blocks))
            conversation.updated_at = utcnow()
            await db.commit()

    async def set_suspended(self, session_id: str, suspended: dict | None):
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation is None:
                return
            conversation.suspended = suspended
            await db.commit()

    async def get_suspended(self, session_id: str) -> dict | None:
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            return conversation.suspended if conversation else None

    async def set_plan(self, session_id: str, plan: list):
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation:
                conversation.plan = plan
                await db.commit()

    async def sessions(self) -> list[dict]:
        async with session_factory()() as db:
            rows = (await db.scalars(select(Conversation).order_by(desc(Conversation.updated_at)))).all()
            counts = dict(
                (await db.execute(select(Message.conversation_id, func.count(Message.id)).group_by(Message.conversation_id))).all()
            )
        return [
            {
                "session_id": r.session_id,
                "title": r.title,
                "messages": counts.get(r.id, 0),
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
                "awaiting_confirmation": bool(r.suspended),
            }
            for r in rows
        ]

    async def reset(self, session_id: str) -> bool:
        async with session_factory()() as db:
            conversation = await db.scalar(
                select(Conversation).where(Conversation.session_id == session_id)
            )
            if conversation is None:
                return False
            await db.execute(delete(Conversation).where(Conversation.id == conversation.id))
            await db.commit()
            return True


def _drop_orphaned_tool_results(messages: list[dict]) -> list[dict]:
    """Remove leading tool_result messages whose tool_use was trimmed away.

    A dangling tool_result makes the next Messages API request invalid, so the
    window has to start on a clean boundary.
    """
    while messages:
        content = messages[0].get("content")
        is_results = isinstance(content, list) and any(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        )
        if not is_results:
            break
        messages.pop(0)
    return messages


class MemoryRepository:
    async def remember(
        self, session_id: str, content: str, kind: str = "episodic", detail: dict = None, importance: float = 0.5
    ) -> int:
        async with session_factory()() as db:
            row = Memory(
                session_id=session_id, kind=kind, content=content, detail=detail, importance=importance
            )
            db.add(row)
            await db.commit()
            return row.id

    async def recall(self, session_id: str, kind: str = None, limit: int = 20) -> list[dict]:
        async with session_factory()() as db:
            query = select(Memory).where(Memory.session_id == session_id)
            if kind:
                query = query.where(Memory.kind == kind)
            rows = (await db.scalars(query.order_by(desc(Memory.id)).limit(limit))).all()
        return [
            {
                "id": r.id,
                "kind": r.kind,
                "content": r.content,
                "detail": r.detail,
                "importance": r.importance,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def search(self, session_id: str, term: str, limit: int = 20) -> list[dict]:
        async with session_factory()() as db:
            rows = (
                await db.scalars(
                    select(Memory)
                    .where(Memory.session_id == session_id, Memory.content.ilike(f"%{term}%"))
                    .order_by(desc(Memory.importance), desc(Memory.id))
                    .limit(limit)
                )
            ).all()
        return [{"id": r.id, "kind": r.kind, "content": r.content, "importance": r.importance} for r in rows]

    async def facts(self, session_id: str, limit: int = 10) -> list[str]:
        """Durable facts, most important first - injected into the system prompt."""
        async with session_factory()() as db:
            rows = (
                await db.scalars(
                    select(Memory)
                    .where(Memory.session_id == session_id, Memory.kind == "fact")
                    .order_by(desc(Memory.importance), desc(Memory.id))
                    .limit(limit)
                )
            ).all()
        return [r.content for r in rows]

    async def forget(self, memory_id: int) -> bool:
        async with session_factory()() as db:
            row = await db.get(Memory, memory_id)
            if row is None:
                return False
            await db.delete(row)
            await db.commit()
            return True


class AuditRepository:
    async def record(self, actor: str, action: str, status: str, detail: dict = None):
        async with session_factory()() as db:
            db.add(AuditEntry(actor=actor, action=action, status=status, detail=detail))
            await db.commit()

    async def entries(self, limit: int = 50, status: str = None) -> list[dict]:
        async with session_factory()() as db:
            query = select(AuditEntry)
            if status:
                query = query.where(AuditEntry.status == status)
            rows = (await db.scalars(query.order_by(desc(AuditEntry.id)).limit(limit))).all()
        return [
            {
                "id": r.id,
                "actor": r.actor,
                "action": r.action,
                "status": r.status,
                "detail": r.detail,
                "timestamp": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

    async def count(self) -> int:
        async with session_factory()() as db:
            return await db.scalar(select(func.count(AuditEntry.id))) or 0


class TaskRepository:
    async def create(self, **fields) -> dict:
        async with session_factory()() as db:
            task = Task(**fields)
            db.add(task)
            # Flush so column defaults (enabled, schedule_kind) are populated -
            # scheduling off an unflushed object sees enabled=None and never runs.
            await db.flush()
            task.next_run_at = _first_run(task)
            await db.commit()
            await db.refresh(task)
            return _task_dict(task)

    async def get(self, task_id: int) -> dict | None:
        async with session_factory()() as db:
            task = await db.get(Task, task_id)
            return _task_dict(task) if task else None

    async def list(self) -> list[dict]:
        async with session_factory()() as db:
            rows = (await db.scalars(select(Task).order_by(Task.id))).all()
            return [_task_dict(r) for r in rows]

    async def due(self, now: datetime = None) -> list[dict]:
        now = now or utcnow()
        async with session_factory()() as db:
            rows = (
                await db.scalars(
                    select(Task).where(
                        Task.enabled.is_(True),
                        Task.next_run_at.is_not(None),
                        Task.next_run_at <= now,
                    )
                )
            ).all()
            return [_task_dict(r) for r in rows]

    async def set_enabled(self, task_id: int, enabled: bool) -> dict | None:
        async with session_factory()() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return None
            task.enabled = enabled
            task.next_run_at = _first_run(task) if enabled else None
            await db.commit()
            await db.refresh(task)
            return _task_dict(task)

    async def delete(self, task_id: int) -> bool:
        async with session_factory()() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return False
            await db.delete(task)
            await db.commit()
            return True

    async def mark_ran(self, task_id: int, status: str):
        async with session_factory()() as db:
            task = await db.get(Task, task_id)
            if task is None:
                return
            task.last_run_at = utcnow()
            task.last_status = status
            task.next_run_at = _next_run(task)
            await db.commit()

    async def start_run(self, task_id: int, attempt: int) -> int:
        async with session_factory()() as db:
            run = TaskRun(task_id=task_id, attempt=attempt, status="running")
            db.add(run)
            await db.commit()
            return run.id

    async def finish_run(self, run_id: int, status: str, detail: dict = None):
        async with session_factory()() as db:
            run = await db.get(TaskRun, run_id)
            if run is None:
                return
            run.status = status
            run.detail = detail
            run.finished_at = utcnow()
            await db.commit()

    async def runs(self, task_id: int, limit: int = 20) -> list[dict]:
        async with session_factory()() as db:
            rows = (
                await db.scalars(
                    select(TaskRun)
                    .where(TaskRun.task_id == task_id)
                    .order_by(desc(TaskRun.id))
                    .limit(limit)
                )
            ).all()
        return [
            {
                "id": r.id,
                "attempt": r.attempt,
                "status": r.status,
                "detail": r.detail,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            }
            for r in rows
        ]


def _task_dict(task: Task) -> dict:
    return {
        "id": task.id,
        "name": task.name,
        "prompt": task.prompt,
        "session_id": task.session_id,
        "schedule_kind": task.schedule_kind,
        "interval_seconds": task.interval_seconds,
        "cron": task.cron,
        "enabled": task.enabled,
        "max_retries": task.max_retries,
        "next_run_at": task.next_run_at.isoformat() if task.next_run_at else None,
        "last_run_at": task.last_run_at.isoformat() if task.last_run_at else None,
        "last_status": task.last_status,
    }


def _first_run(task: Task) -> datetime | None:
    if not task.enabled:
        return None
    if task.schedule_kind == "once":
        return utcnow()
    return _advance(task, utcnow())


def _next_run(task: Task) -> datetime | None:
    if task.schedule_kind == "once" or not task.enabled:
        return None
    return _advance(task, utcnow())


def _advance(task: Task, after: datetime) -> datetime | None:
    if task.schedule_kind == "interval" and task.interval_seconds:
        return after + timedelta(seconds=task.interval_seconds)
    if task.schedule_kind == "cron" and task.cron:
        from croniter import croniter

        return croniter(task.cron, after).get_next(datetime)
    return None


class ApiKeyRepository:
    async def add(self, label: str, key_hash: str, scopes: str) -> dict:
        async with session_factory()() as db:
            row = ApiKey(label=label, key_hash=key_hash, scopes=scopes)
            db.add(row)
            await db.commit()
            await db.refresh(row)
            return {"id": row.id, "label": row.label, "scopes": row.scopes, "active": row.active}

    async def find(self, key_hash: str) -> dict | None:
        async with session_factory()() as db:
            row = await db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash))
            if row is None or not row.active:
                return None
            row.last_used_at = utcnow()
            await db.commit()
            return {"id": row.id, "label": row.label, "scopes": row.scopes.split(",")}

    async def list(self) -> list[dict]:
        async with session_factory()() as db:
            rows = (await db.scalars(select(ApiKey).order_by(ApiKey.id))).all()
        return [
            {
                "id": r.id,
                "label": r.label,
                "scopes": r.scopes.split(","),
                "active": r.active,
                "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
            }
            for r in rows
        ]

    async def revoke(self, key_id: int) -> bool:
        async with session_factory()() as db:
            row = await db.get(ApiKey, key_id)
            if row is None:
                return False
            row.active = False
            await db.commit()
            return True

    async def count(self) -> int:
        async with session_factory()() as db:
            return await db.scalar(select(func.count(ApiKey.id))) or 0


class SecretRepository:
    async def put(self, name: str, ciphertext: str):
        async with session_factory()() as db:
            row = await db.scalar(select(Secret).where(Secret.name == name))
            if row is None:
                db.add(Secret(name=name, ciphertext=ciphertext))
            else:
                row.ciphertext = ciphertext
            await db.commit()

    async def get(self, name: str) -> str | None:
        async with session_factory()() as db:
            row = await db.scalar(select(Secret).where(Secret.name == name))
            return row.ciphertext if row else None

    async def names(self) -> list[str]:
        async with session_factory()() as db:
            rows = (await db.scalars(select(Secret.name).order_by(Secret.name))).all()
        return list(rows)

    async def delete(self, name: str) -> bool:
        async with session_factory()() as db:
            row = await db.scalar(select(Secret).where(Secret.name == name))
            if row is None:
                return False
            await db.delete(row)
            await db.commit()
            return True
