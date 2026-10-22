from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_ADMIN, SCOPE_READ, require
from app.security.permissions import DEFAULT_PERMISSIONS

# Only declared permissions may be toggled, so a typo cannot create a
# permission that no tool will ever check.
KNOWN_PERMISSIONS = sorted(runtime.registry.permissions_catalog() | set(DEFAULT_PERMISSIONS))

router = APIRouter(prefix="/permissions", tags=["security"])


class PermissionChange(BaseModel):
    permission: str = Field(min_length=1)


@router.get("")
async def list_permissions(_=Depends(require(SCOPE_READ))):
    return {
        "permissions": {name: runtime.permissions.allowed(name) for name in KNOWN_PERMISSIONS},
        "known": KNOWN_PERMISSIONS,
        "defaults": DEFAULT_PERMISSIONS,
    }


@router.post("/grant")
async def grant_permission(change: PermissionChange, _=Depends(require(SCOPE_ADMIN))):
    if change.permission not in KNOWN_PERMISSIONS:
        return {"status": "unknown_permission", "permission": change.permission, "known": KNOWN_PERMISSIONS}
    runtime.permissions.grant(change.permission)
    runtime.audit.record("operator", f"permission.grant:{change.permission}", "granted")
    return {"status": "granted", "permission": change.permission}


@router.post("/revoke")
async def revoke_permission(change: PermissionChange, _=Depends(require(SCOPE_ADMIN))):
    if change.permission not in KNOWN_PERMISSIONS:
        return {"status": "unknown_permission", "permission": change.permission, "known": KNOWN_PERMISSIONS}
    runtime.permissions.revoke(change.permission)
    runtime.audit.record("operator", f"permission.revoke:{change.permission}", "revoked")
    return {"status": "revoked", "permission": change.permission}


@router.post("/reset")
async def reset_permissions(_=Depends(require(SCOPE_ADMIN))):
    runtime.permissions.reset()
    runtime.audit.record("operator", "permission.reset", "reset")
    return {"status": "reset", "permissions": runtime.permissions.snapshot()}
