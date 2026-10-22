"""Human-in-the-loop confirmation for privileged tool calls.

A gated call does not execute on first request. It is parked as a pending
record and a token is returned; the command runs only after the operator
approves that token. This keeps the decision to execute with a human rather
than with the model.
"""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

DEFAULT_TTL_SECONDS = 300
MAX_PENDING = 100

PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"
EXPIRED = "expired"
CONSUMED = "consumed"


def _now():
    return datetime.now(timezone.utc)


@dataclass
class ConfirmationRequest:
    token: str
    tool: str
    action: str
    arguments: dict
    created_at: datetime
    expires_at: datetime
    status: str = PENDING

    def is_expired(self) -> bool:
        return _now() >= self.expires_at

    def summary(self) -> dict:
        return {
            "token": self.token,
            "tool": self.tool,
            "action": self.action,
            "arguments": self.arguments,
            "status": EXPIRED if (self.status == PENDING and self.is_expired()) else self.status,
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
        }


@dataclass
class ConfirmationStore:
    ttl_seconds: int = DEFAULT_TTL_SECONDS
    _requests: dict[str, ConfirmationRequest] = field(default_factory=dict)

    def request(self, tool: str, action: str, arguments: dict) -> ConfirmationRequest:
        self._evict()
        record = ConfirmationRequest(
            token=secrets.token_urlsafe(16),
            tool=tool,
            action=action,
            arguments=dict(arguments),
            created_at=_now(),
            expires_at=_now() + timedelta(seconds=self.ttl_seconds),
        )
        self._requests[record.token] = record
        return record

    def get(self, token: str):
        return self._requests.get(token)

    def approve(self, token: str) -> dict:
        return self._decide(token, APPROVED)

    def deny(self, token: str) -> dict:
        return self._decide(token, DENIED)

    def _decide(self, token: str, decision: str) -> dict:
        record = self._requests.get(token)
        if not record:
            return {"status": "unknown_token", "token": token}
        # summary() carries its own "status", so it must be spread *before* the
        # outcome key - otherwise it silently overwrites the decision.
        if record.status != PENDING:
            return {**record.summary(), "status": "already_resolved", "current": record.status}
        if record.is_expired():
            record.status = EXPIRED
            return {**record.summary(), "status": EXPIRED}
        record.status = decision
        return {**record.summary(), "status": decision}

    def claim(self, token: str, expected_arguments: dict = None):
        """Consume an approved token exactly once. Returns (record, error).

        `expected_arguments` is verified *before* the token is consumed, so a
        mismatched call cannot burn an otherwise-valid approval.
        """
        record = self._requests.get(token)
        if not record:
            return None, {"status": "unknown_token", "token": token}
        if record.status == EXPIRED or (record.is_expired() and record.status in (PENDING, APPROVED)):
            record.status = EXPIRED
            return None, {"status": EXPIRED, "token": token}
        if record.status == PENDING:
            return None, {"status": "awaiting_confirmation", "token": token}
        if record.status != APPROVED:
            return None, {"status": f"token_{record.status}", "token": token}
        if expected_arguments is not None and record.arguments != expected_arguments:
            # Leave the approval intact - it is still valid for its own command.
            return None, {"status": "token_argument_mismatch", "token": token}
        # Single use - an approval cannot be replayed.
        record.status = CONSUMED
        return record, None

    def pending(self) -> list[dict]:
        self._evict()
        return [r.summary() for r in self._requests.values() if r.status == PENDING]

    def all(self) -> list[dict]:
        return [r.summary() for r in self._requests.values()]

    def _evict(self):
        for token, record in list(self._requests.items()):
            if record.status == PENDING and record.is_expired():
                record.status = EXPIRED
        if len(self._requests) > MAX_PENDING:
            resolved = [t for t, r in self._requests.items() if r.status != PENDING]
            for token in resolved[: len(self._requests) - MAX_PENDING]:
                del self._requests[token]
