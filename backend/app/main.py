"""Subh AI — application entry point.

Design principle: the model never touches the operating system or an external
service directly. It asks the tool orchestrator for an action, the permission
layer decides whether that action is allowed, and only then does the execution
layer perform it.
"""

import contextlib
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agent import router as agent_router
from app.api.audit import router as audit_router
from app.api.auth import router as auth_router
from app.api.confirmations import router as confirmations_router
from app.api.memory import router as memory_router
from app.api.permissions import router as permissions_router
from app.api.secrets import router as secrets_router
from app.api.system import router as system_router
from app.api.tasks import router as tasks_router
from app.api.tools import router as tools_router
from app.api.voice import router as voice_router
from app.core import runtime
from app.core.config import settings
from app.core.preflight import enforce
from app.db.session import dispose_db, init_db

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("subh")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI):
    # Fatal in production, advisory elsewhere.
    for finding in enforce(settings):
        logger.warning("config: %s - %s", finding["setting"], finding["detail"])

    await init_db()
    logger.info("database ready (%s)", settings.database_url.split("://")[0])

    if settings.scheduler_enabled:
        await runtime.scheduler.start()
        logger.info("scheduler started, tick=%ss", settings.scheduler_tick_seconds)

    yield

    await runtime.scheduler.stop()
    await runtime.audit.flush()
    await dispose_db()


app = FastAPI(
    title=f"{settings.agent_name} API",
    version="1.0.0",
    description=(
        "Permission-controlled AI agent. The model requests actions; the permission "
        "layer decides; the execution layer performs them."
    ),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    system_router,
    agent_router,
    tools_router,
    memory_router,
    tasks_router,
    voice_router,
    permissions_router,
    confirmations_router,
    audit_router,
    auth_router,
    secrets_router,
):
    app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    return {
        "name": settings.agent_name,
        "status": "running",
        "version": "1.0.0",
        "docs": "/docs",
        "capabilities": {
            "llm": runtime.provider.configured,
            "tools": runtime.registry.names(),
            "voice_mode": settings.voice_mode,
            "scheduler": runtime.scheduler.running,
            "auth": settings.auth_enabled,
        },
    }
