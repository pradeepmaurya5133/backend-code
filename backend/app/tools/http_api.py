"""Generic REST caller - the "APIs" leg of the tool layer.

This is the most dangerous tool in the set, because an unrestricted HTTP client
can reach anything the host can. It is therefore the most restricted:

  * the target host must be on an explicit allowlist (empty allowlist = nothing
    is reachable, so the capability is off until an operator opts in)
  * private, loopback and link-local addresses are refused even if allowlisted,
    so an entry cannot be used to reach internal services
  * credentials are never taken from the model - it names a stored secret, and
    the server substitutes the value, so a key cannot leak into the transcript
  * anything other than GET/HEAD additionally requires `api.write`
"""

import json as jsonlib
from urllib.parse import urlparse

import httpx

from app.security.permissions import PermissionGate
from app.tools.base import Tool
from app.tools.web import validate_scheme, validate_url

MAX_BODY_CHARS = 20_000
SAFE_METHODS = {"GET", "HEAD"}
ALL_METHODS = SAFE_METHODS | {"POST", "PUT", "PATCH", "DELETE"}


class HttpApiTool(Tool):
    name = "http_api"
    description = (
        "Call an external JSON/REST API. The host must be allowlisted by an operator; "
        "requests to any other host are refused. Never put credentials in the request - "
        "set auth_secret to the NAME of a stored secret and the server injects its value "
        "as a bearer token. GET and HEAD need 'api.call'; writing methods also need 'api.write'."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full https URL of the endpoint."},
            "method": {
                "type": "string",
                "enum": sorted(ALL_METHODS),
                "description": "HTTP method. Defaults to GET.",
            },
            "query": {"type": "object", "description": "Query-string parameters."},
            "body": {"type": "object", "description": "JSON request body for write methods."},
            "headers": {"type": "object", "description": "Extra headers. Authorization is ignored."},
            "auth_secret": {
                "type": "string",
                "description": "Name of a stored secret to send as 'Authorization: Bearer <value>'.",
            },
        },
        "required": ["url"],
    }
    permissions_required = {"api.call", "api.write"}

    def __init__(
        self,
        permissions: PermissionGate = None,
        allowed_hosts: set[str] = None,
        secrets=None,
        timeout: int = 15,
        client=None,
        resolver=None,
    ):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.allowed_hosts = {h.lower() for h in (allowed_hosts or set())}
        self.secrets = secrets
        self.timeout = timeout
        self._client = client
        self._resolver = resolver

    def _host_allowed(self, hostname: str) -> bool:
        host = hostname.lower()
        # An allowlist entry covers its subdomains.
        return any(host == allowed or host.endswith("." + allowed) for allowed in self.allowed_hosts)

    async def execute(self, arguments: dict) -> dict:
        url = (arguments.get("url") or "").strip()
        method = (arguments.get("method") or "GET").upper()

        if not url:
            return {"tool": self.name, "status": "missing_url"}
        if method not in ALL_METHODS:
            return {"tool": self.name, "status": "unsupported_method", "method": method}

        if not self.permissions.allowed("api.call"):
            return {"tool": self.name, "status": "permission_required", "permission": "api.call"}
        if method not in SAFE_METHODS and not self.permissions.allowed("api.write"):
            return {
                "tool": self.name,
                "status": "permission_required",
                "permission": "api.write",
                "method": method,
            }

        # Scheme and shape first - no network access yet.
        hostname, error = validate_scheme(url)
        if error:
            return {"tool": self.name, "url": url, **error}

        # The allowlist is checked BEFORE resolving. Resolving first would leak
        # data to an unapproved host's nameserver even when the request itself
        # is refused, which is a usable exfiltration channel.
        if not self.allowed_hosts:
            return {
                "tool": self.name,
                "status": "no_hosts_allowlisted",
                "detail": "An operator must add hosts to API_ALLOWED_HOSTS before this tool can reach anything.",
            }
        if not self._host_allowed(hostname):
            return {
                "tool": self.name,
                "status": "host_not_allowlisted",
                "host": hostname,
                "allowed": sorted(self.allowed_hosts),
            }

        # Only now resolve, to catch an allowlisted name pointing somewhere internal.
        validated, error = await validate_url(url, self._resolver)
        if error:
            return {"tool": self.name, "url": url, **error}

        headers = {
            str(k): str(v)
            for k, v in (arguments.get("headers") or {}).items()
            # The model must not set credentials directly.
            if str(k).lower() not in ("authorization", "proxy-authorization", "cookie")
        }
        headers.setdefault("User-Agent", "SubhAI/1.0 (+api)")

        secret_name = arguments.get("auth_secret")
        if secret_name:
            if self.secrets is None:
                return {"tool": self.name, "status": "secret_store_unavailable"}
            value = await self.secrets.reveal(secret_name)
            if value is None:
                return {"tool": self.name, "status": "unknown_secret", "secret": secret_name}
            headers["Authorization"] = f"Bearer {value}"

        request = {
            "params": arguments.get("query") or None,
            "headers": headers,
        }
        if method not in SAFE_METHODS and arguments.get("body") is not None:
            request["json"] = arguments["body"]

        try:
            if self._client is not None:
                response = await self._client.request(method, validated, **request)
            else:
                async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
                    response = await client.request(method, validated, **request)
        except httpx.TimeoutException:
            return {"tool": self.name, "status": "timeout", "url": url}
        except httpx.HTTPError as exc:
            return {"tool": self.name, "status": "request_failed", "detail": str(exc)[:300]}

        text = response.text[:MAX_BODY_CHARS]
        parsed = None
        if "json" in response.headers.get("content-type", "").lower():
            try:
                parsed = jsonlib.loads(response.text)
            except ValueError:
                parsed = None

        result = {
            "tool": self.name,
            "status": "ok" if response.is_success else "http_error",
            "url": str(response.url),
            "method": method,
            "http_status": response.status_code,
            "truncated": len(response.text) > MAX_BODY_CHARS,
        }
        if parsed is not None:
            result["json"] = parsed
        else:
            result["body"] = text
        return result
