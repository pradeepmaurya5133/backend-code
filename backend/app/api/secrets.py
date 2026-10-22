from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_ADMIN, require

router = APIRouter(prefix="/secrets", tags=["security"])


class SecretRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.\-]+$")
    value: str = Field(min_length=1)


@router.get("")
async def list_secrets(_=Depends(require(SCOPE_ADMIN))):
    """Names only. Values are never returned over the API by design."""
    return {
        "secrets": await runtime.secrets.names(),
        "encryption": "fernet",
        "key_derived_from_secret_key": runtime.crypto.derived,
    }


@router.put("")
async def put_secret(request: SecretRequest, _=Depends(require(SCOPE_ADMIN))):
    await runtime.secrets.put(request.name, request.value)
    runtime.audit.record("operator", f"secret.put:{request.name}", "stored")
    return {"status": "stored", "name": request.name}


@router.delete("/{name}")
async def delete_secret(name: str, _=Depends(require(SCOPE_ADMIN))):
    removed = await runtime.secrets.delete(name)
    if removed:
        runtime.audit.record("operator", f"secret.delete:{name}", "deleted")
    return {"status": "deleted" if removed else "not_found", "name": name}
