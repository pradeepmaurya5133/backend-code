from fastapi import APIRouter, Depends

from app.core import runtime
from app.security.auth import SCOPE_READ, require

router = APIRouter(prefix="/audit", tags=["security"])


@router.get("")
async def list_audit(limit: int = 50, status: str = None, _=Depends(require(SCOPE_READ))):
    """Durable trail from the database, newest first."""
    bounded = min(max(limit, 1), 500)
    return {
        "count": await runtime.audit_repository.count(),
        "entries": await runtime.audit.durable_entries(bounded, status),
    }


@router.get("/recent")
async def recent(limit: int = 50, _=Depends(require(SCOPE_READ))):
    """In-memory ring for this process - available even if the database is down."""
    return {"entries": runtime.audit.entries(min(max(limit, 1), 500))}
