"""Health and monitoring (Phase 6)."""

import time

from fastapi import APIRouter, Depends, Response

from app.core import runtime
from app.core.config import settings
from app.core.preflight import report
from app.security.auth import SCOPE_READ, require

router = APIRouter(tags=["system"])
STARTED_AT = time.time()


@router.get("/health")
async def health():
    """Unauthenticated liveness probe."""
    return {
        "status": "ok",
        "agent": settings.agent_name,
        "environment": settings.environment,
        "auth_enabled": settings.auth_enabled,
        "llm_configured": runtime.provider.configured,
    }


@router.get("/ready")
async def ready():
    """Readiness: verifies the database actually answers."""
    checks = {"database": "unknown", "llm": "configured" if runtime.provider.configured else "unconfigured"}
    try:
        await runtime.task_repository.list()
        checks["database"] = "ok"
    except Exception as exc:
        checks["database"] = f"error: {str(exc)[:120]}"
        return Response(
            content=f'{{"status":"not_ready","checks":{checks}}}'.replace("'", '"'),
            media_type="application/json",
            status_code=503,
        )
    return {"status": "ready", "checks": checks}


@router.get("/metrics")
async def metrics(_=Depends(require(SCOPE_READ))):
    return {
        "uptime_seconds": round(time.time() - STARTED_AT, 1),
        "agent": settings.agent_name,
        "environment": settings.environment,
        "llm": runtime.llm_status(),
        "scheduler": runtime.scheduler.status(),
        "tools": runtime.registry.names(),
        "permissions": runtime.permissions.snapshot(),
        "audit_entries_in_memory": len(runtime.audit),
        "audit_entries_persisted": await runtime.audit_repository.count(),
        "pending_confirmations": len(runtime.confirmations.pending()),
        "sessions": len(await runtime.conversations.sessions()),
        "api_keys": await runtime.api_keys.count(),
    }


@router.get("/preflight")
async def preflight(_=Depends(require(SCOPE_READ))):
    """Which insecure defaults are still in place."""
    return report(settings)
