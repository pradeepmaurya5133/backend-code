"""Shared test fixtures.

Every test that touches persistence gets its own file-backed SQLite database, so
suites cannot see each other's rows. A file (not :memory:) is used because the
async engine opens more than one connection and an in-memory database would not
be shared between them.
"""

import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from app.core.config import settings
from app.db.session import dispose_db, init_db, reset_for_tests


@pytest_asyncio.fixture
async def db(tmp_path):
    """A fresh database for one test."""
    path = tmp_path / f"subh_{uuid.uuid4().hex}.db"
    original = settings.database_url
    reset_for_tests(f"sqlite+aiosqlite:///{path.as_posix()}")
    await init_db()
    yield path
    await dispose_db()
    reset_for_tests(original)


@pytest.fixture
def workspace(tmp_path):
    """An isolated agent workspace."""
    root = tmp_path / "workspace"
    root.mkdir(exist_ok=True)
    return root


@pytest.fixture
def client(tmp_path):
    """A TestClient with the app's lifespan run against a throwaway database.

    Entering TestClient as a context manager is what triggers lifespan, which is
    what creates the schema - a module-level TestClient would skip it.
    """
    from app.core import runtime
    from app.main import app

    path = tmp_path / f"api_{uuid.uuid4().hex}.db"
    original_url = settings.database_url
    original_scheduler = settings.scheduler_enabled
    original_auth = settings.auth_enabled
    original_permissions = runtime.permissions.snapshot()
    original_provider = runtime.provider

    reset_for_tests(f"sqlite+aiosqlite:///{path.as_posix()}")
    # The background scheduler would run tasks mid-assertion.
    settings.scheduler_enabled = False

    with TestClient(app) as test_client:
        yield test_client

    settings.scheduler_enabled = original_scheduler
    settings.auth_enabled = original_auth
    runtime.permissions.permissions = dict(original_permissions)
    runtime.confirmations._requests.clear()
    runtime.set_provider(original_provider)
    reset_for_tests(original_url)


@pytest.fixture
def scripted(client):
    """Install a scripted LLM provider into the running app."""
    from app.core import runtime
    from app.llm.scripted import ScriptedProvider

    def install(responses):
        provider = ScriptedProvider(responses)
        runtime.set_provider(provider)
        return provider

    return install


@pytest.fixture
def plan_text():
    """A scripted planning response, for paths that run with planning on."""
    import json

    from app.llm.scripted import ScriptedProvider

    def make(understanding="Understood.", steps=(), question=None):
        return ScriptedProvider.text(
            json.dumps(
                {
                    "understanding": understanding,
                    "steps": list(steps),
                    "clarification_needed": question,
                }
            )
        )

    return make
