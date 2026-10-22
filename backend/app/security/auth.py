"""Authentication and scope checks (Phase 6).

Two credential types:
  * API keys  - for scripts and the scheduler; sent as `X-API-Key`
  * JWT       - for the web/mobile clients; sent as `Authorization: Bearer`

Disabled by default (`AUTH_ENABLED=false`) so local development needs no setup.
When disabled every request is treated as a local operator holding all scopes,
and `/api/health` reports that plainly so an exposed deployment is obvious.
"""

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status

from app.core.config import settings

# Scopes, coarse on purpose: the fine-grained decisions are the permission gate's job.
SCOPE_READ = "read"
SCOPE_RUN = "agent:run"
SCOPE_APPROVE = "confirmations:approve"
SCOPE_ADMIN = "admin"
ALL_SCOPES = [SCOPE_READ, SCOPE_RUN, SCOPE_APPROVE, SCOPE_ADMIN]


class Principal:
    def __init__(self, subject: str, scopes: list[str], kind: str = "local"):
        self.subject = subject
        self.scopes = scopes
        self.kind = kind

    @property
    def is_admin(self) -> bool:
        return SCOPE_ADMIN in self.scopes

    def has(self, scope: str) -> bool:
        return SCOPE_ADMIN in self.scopes or scope in self.scopes

    def to_dict(self) -> dict:
        return {"subject": self.subject, "scopes": self.scopes, "kind": self.kind}


LOCAL_PRINCIPAL = Principal("local-operator", list(ALL_SCOPES), kind="local")


def issue_token(subject: str, scopes: list[str]) -> dict:
    expires = datetime.now(timezone.utc) + timedelta(seconds=settings.jwt_ttl_seconds)
    payload = {"sub": subject, "scopes": scopes, "exp": expires}
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)
    return {"access_token": token, "token_type": "bearer", "expires_at": expires.isoformat()}


def _decode(token: str) -> Principal | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError:
        return None
    return Principal(payload.get("sub", "unknown"), payload.get("scopes", []), kind="jwt")


async def current_principal(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> Principal:
    """Resolve the caller. Raises 401 when auth is on and nothing validates."""
    if not settings.auth_enabled:
        return LOCAL_PRINCIPAL

    if x_api_key:
        # Imported here to keep this module importable without a database.
        from app.core import runtime

        record = await runtime.api_keys.verify(x_api_key)
        if record:
            return Principal(record["label"], record["scopes"], kind="api_key")

    if authorization and authorization.lower().startswith("bearer "):
        principal = _decode(authorization.split(" ", 1)[1].strip())
        if principal:
            return principal

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Provide a valid X-API-Key or Authorization: Bearer token.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require(scope: str):
    """Dependency factory enforcing one scope."""

    async def dependency(principal: Principal = Depends(current_principal)) -> Principal:
        if not principal.has(scope):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Scope '{scope}' is required.",
            )
        return principal

    return dependency
