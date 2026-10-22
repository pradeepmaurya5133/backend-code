from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_APPROVE, SCOPE_READ, require

router = APIRouter(prefix="/confirmations", tags=["security"])


class TokenRequest(BaseModel):
    token: str = Field(min_length=1)


@router.get("")
async def list_pending(_=Depends(require(SCOPE_READ))):
    return {"pending": runtime.confirmations.pending()}


@router.post("/approve")
async def approve(request: TokenRequest, principal=Depends(require(SCOPE_APPROVE))):
    result = runtime.confirmations.approve(request.token)
    runtime.audit.record(principal.subject, f"confirmation.approve:{request.token}", result["status"])
    return result


@router.post("/deny")
async def deny(request: TokenRequest, principal=Depends(require(SCOPE_APPROVE))):
    result = runtime.confirmations.deny(request.token)
    runtime.audit.record(principal.subject, f"confirmation.deny:{request.token}", result["status"])
    return result
