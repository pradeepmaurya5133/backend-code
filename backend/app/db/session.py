"""Async engine and session factory.

The same code path serves SQLite (default, zero-setup) and PostgreSQL
(deployment) - only `DATABASE_URL` differs. `create_all` is used rather than
migrations because the schema is still moving; a real deployment should switch
to Alembic before data matters.
"""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import Base

_engine = None
_session_factory = None


def _normalise(url: str) -> str:
    """Accept sync-style URLs and upgrade them to their async driver."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def engine():
    global _engine
    if _engine is None:
        url = _normalise(settings.database_url)
        kwargs = {"echo": False, "future": True}
        if not url.startswith("sqlite"):
            kwargs |= {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 10}
        _engine = create_async_engine(url, **kwargs)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(engine(), expire_on_commit=False, class_=AsyncSession)
    return _session_factory


async def init_db():
    async with engine().begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def dispose_db():
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


def reset_for_tests(url: str):
    """Point the engine at a throwaway database. Tests only."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
    settings.database_url = url
