"""Database schema for Subh AI.

Runs on SQLite by default so a developer can start with no infrastructure, and
on PostgreSQL in deployment via the same models - only DATABASE_URL changes.
JSON columns use SQLAlchemy's portable JSON type for that reason.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Conversation(Base):
    """A chat session. Holds the replayable message history for the LLM."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    # The in-flight turn parked waiting for approval, if any.
    suspended: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    plan: Mapped[list | None] = mapped_column(JSON, nullable=True)

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.id"
    )


class Message(Base):
    """One turn. `blocks` keeps provider-native content so thinking and
    tool_use survive the replay; `text` is the human-readable projection."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text, default="")
    blocks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")


class Memory(Base):
    """Long-term recall that outlives a single conversation.

    `kind` separates durable facts the agent should remember from the running
    episodic log of what it did.
    """

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128), index=True)
    kind: Mapped[str] = mapped_column(String(32), default="episodic")  # episodic | fact
    content: Mapped[str] = mapped_column(Text)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    importance: Mapped[float] = mapped_column(Float, default=0.5)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (Index("ix_memories_session_kind", "session_id", "kind"),)


class Task(Base):
    """An automation task: run once, on an interval, or on a cron schedule."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    prompt: Mapped[str] = mapped_column(Text)
    session_id: Mapped[str] = mapped_column(String(128), default="scheduled")
    schedule_kind: Mapped[str] = mapped_column(String(16), default="once")  # once | interval | cron
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cron: Mapped[str | None] = mapped_column(String(128), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    max_retries: Mapped[int] = mapped_column(Integer, default=2)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str] = mapped_column(String(32), default="pending")

    runs: Mapped[list["TaskRun"]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TaskRun.id.desc()"
    )


class TaskRun(Base):
    """One execution attempt of a task, including retries."""

    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), index=True)
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(32), default="running")
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[Task] = relationship(back_populates="runs")


class AuditEntry(Base):
    """Durable audit trail. Mirrors the in-memory log so history survives restarts."""

    __tablename__ = "audit_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(128), default="agent", index=True)
    action: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(64), index=True)
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ApiKey(Base):
    """An operator credential. Only a salted hash of the key is stored."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(128))
    key_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # Comma-separated scopes, e.g. "agent:run,permissions:write".
    scopes: Mapped[str] = mapped_column(String(512), default="agent:run")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Secret(Base):
    """A third-party credential, encrypted at rest with the app's data key."""

    __tablename__ = "secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
