from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.core.config import settings
from app.security.auth import (
    ALL_SCOPES,
    SCOPE_ADMIN,
    Principal,
    current_principal,
    issue_token,
    require,
)

router = APIRouter(prefix="/auth", tags=["security"])


class ApiKeyRequest(BaseModel):
    label: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=lambda: ["read", "agent:run"])


class TokenRequest(BaseModel):
    api_key: str = Field(min_length=1)


@router.get("/status")
async def auth_status():
    """Deliberately unauthenticated: a client needs to know whether to log in."""
    return {
        "auth_enabled": settings.auth_enabled,
        "scopes": ALL_SCOPES,
        "keys_issued": await runtime.api_keys.count(),
        "warning": None
        if settings.auth_enabled
        else "Authentication is disabled; every caller is treated as a local operator.",
    }


@router.get("/whoami")
async def whoami(principal: Principal = Depends(current_principal)):
    return principal.to_dict()


@router.post("/keys")
async def create_key(request: ApiKeyRequest, _=Depends(require(SCOPE_ADMIN))):
    """Issue an API key. The plaintext is returned once and never stored."""
    unknown = [s for s in request.scopes if s not in ALL_SCOPES]
    if unknown:
        return {"status": "unknown_scopes", "unknown": unknown, "allowed": ALL_SCOPES}
    record = await runtime.api_keys.issue(request.label, request.scopes)
    runtime.audit.record("operator", f"auth.key.issue:{request.label}", "created")
    return {
        "status": "created",
        **record,
        "note": "Store this key now - it cannot be retrieved again.",
    }


@router.get("/keys")
async def list_keys(_=Depends(require(SCOPE_ADMIN))):
    return {"keys": await runtime.api_keys.list()}


@router.delete("/keys/{key_id}")
async def revoke_key(key_id: int, _=Depends(require(SCOPE_ADMIN))):
    revoked = await runtime.api_keys.revoke(key_id)
    if revoked:
        runtime.audit.record("operator", f"auth.key.revoke:{key_id}", "revoked")
    return {"status": "revoked" if revoked else "not_found", "key_id": key_id}


@router.post("/token")
async def exchange_token(request: TokenRequest):
    """Trade an API key for a short-lived JWT, for browser clients."""
    record = await runtime.api_keys.verify(request.api_key)
    if record is None:
        return {"status": "invalid_api_key"}
    return {"status": "ok", **issue_token(record["label"], record["scopes"])}
