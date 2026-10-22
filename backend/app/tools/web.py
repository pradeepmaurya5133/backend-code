"""Web access for Subh AI.

`fetch` is a real HTTP GET with the same fail-closed posture as the terminal
sandbox: private and loopback addresses are refused, the response is size- and
time-capped, and HTML is reduced to text before the model ever sees it.

`search` needs a provider key. Rather than routing search through the model's
own server-side tool - which would bypass this project's permission layer - it
is a client-side call gated like everything else, and reports
`provider_not_configured` until a key is stored.
"""

import asyncio
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlparse

import httpx

from app.security.permissions import PermissionGate
from app.tools.base import Tool

MAX_TEXT_CHARS = 20_000
BLOCKED_SCHEMES = {"file", "ftp", "gopher", "data", "javascript"}


class _TextExtractor(HTMLParser):
    """Strips markup, scripts and styles, leaving readable text."""

    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skip_depth = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self._parts.append("\n")

    def handle_data(self, data):
        # The title check comes first: <title> lives inside <head>, which is
        # itself skipped, so checking skip_depth first would never see it.
        if self._in_title:
            self.title += data.strip()
            return
        if self._skip_depth:
            return
        text = data.strip()
        if text:
            self._parts.append(text)

    def text(self) -> str:
        joined = " ".join(self._parts)
        return re.sub(r"[ \t]*\n[ \t\n]*", "\n", re.sub(r"[ \t]{2,}", " ", joined)).strip()


async def default_resolver(hostname: str) -> list[str] | None:
    """Resolve a hostname to addresses, or None if it cannot be resolved.

    getaddrinfo is blocking, so it runs in a worker thread - calling it
    directly would stall the event loop for the duration of the DNS lookup.
    """
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except OSError:
        return None
    return [info[4][0] for info in infos]


def _addresses_are_private(addresses: list[str]) -> bool:
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError:
            return True
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return True
    return False


def validate_scheme(raw: str) -> tuple[str | None, dict | None]:
    """Scheme and shape checks only - no network access."""
    parsed = urlparse(raw)
    if parsed.scheme in BLOCKED_SCHEMES:
        return None, {"status": "scheme_refused", "detail": f"'{parsed.scheme}' is not permitted"}
    if parsed.scheme not in ("http", "https"):
        return None, {"status": "scheme_refused", "detail": "Only http and https are permitted"}
    if not parsed.hostname:
        return None, {"status": "invalid_url"}
    return parsed.hostname, None


async def validate_url(raw: str, resolver=None) -> tuple[str | None, dict | None]:
    """Returns (url, error). Error is a tool-shaped dict when the URL is unsafe.

    Resolution happens here rather than at request time so a public hostname
    pointing at 127.0.0.1 or a cloud metadata address is refused too.
    """
    hostname, error = validate_scheme(raw)
    if error:
        return None, error

    addresses = await (resolver or default_resolver)(hostname)
    if addresses is None:
        return None, {"status": "host_unresolvable", "detail": f"'{hostname}' does not resolve"}
    if _addresses_are_private(addresses):
        return None, {
            "status": "private_address_refused",
            "detail": "Loopback, private and link-local addresses are not reachable from tools.",
        }
    return raw, None


class WebTool(Tool):
    name = "web"
    description = (
        "Fetch a web page or search the web. 'fetch' retrieves a URL and returns its "
        "readable text, truncated if long; private, loopback and non-http addresses are "
        "refused. 'search' requires a configured search provider and reports "
        "provider_not_configured until one is set."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string", "enum": ["fetch", "search"]},
            "query": {
                "type": "string",
                "description": "A full URL for 'fetch', or search terms for 'search'.",
            },
        },
        "required": ["operation", "query"],
    }
    permissions_required = {"web.search", "web.fetch"}

    def __init__(
        self,
        permissions: PermissionGate = None,
        timeout: int = 15,
        max_bytes: int = 400_000,
        search_provider=None,
        client=None,
        resolver=None,
    ):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.search_provider = search_provider
        self._client = client
        self._resolver = resolver

    async def execute(self, arguments: dict) -> dict:
        operation = arguments.get("operation", "search")
        query = (arguments.get("query") or "").strip()

        if operation not in ("fetch", "search"):
            return {"tool": self.name, "status": "unsupported_operation", "operation": operation}
        if not query:
            return {"tool": self.name, "status": "missing_query"}

        permission = "web.fetch" if operation == "fetch" else "web.search"
        if not self.permissions.allowed(permission):
            return {"tool": self.name, "status": "permission_required", "permission": permission}

        if operation == "search":
            return await self._search(query)
        return await self._fetch(query)

    async def _search(self, query: str) -> dict:
        if self.search_provider is None:
            return {
                "tool": self.name,
                "status": "provider_not_configured",
                "operation": "search",
                "query": query,
                "detail": "Store a search API key via /api/secrets to enable search.",
            }
        try:
            results = await self.search_provider.search(query)
        except Exception as exc:  # a provider outage must not crash the turn
            return {"tool": self.name, "status": "search_failed", "detail": str(exc)[:300]}
        return {"tool": self.name, "status": "ok", "operation": "search", "query": query, "results": results}

    async def _fetch(self, url: str) -> dict:
        validated, error = await validate_url(url, self._resolver)
        if error:
            return {"tool": self.name, "operation": "fetch", "url": url, **error}

        try:
            if self._client is not None:
                response = await self._client.get(validated)
            else:
                async with httpx.AsyncClient(
                    timeout=self.timeout, follow_redirects=True, max_redirects=5
                ) as client:
                    response = await client.get(
                        validated, headers={"User-Agent": "SubhAI/1.0 (+tool)"}
                    )
        except httpx.TimeoutException:
            return {"tool": self.name, "status": "timeout", "url": url}
        except httpx.HTTPError as exc:
            return {"tool": self.name, "status": "fetch_failed", "url": url, "detail": str(exc)[:300]}

        body = response.content[: self.max_bytes]
        content_type = response.headers.get("content-type", "")
        truncated_bytes = len(response.content) > self.max_bytes

        if "html" in content_type.lower():
            parser = _TextExtractor()
            parser.feed(body.decode(response.encoding or "utf-8", errors="replace"))
            text, title = parser.text(), parser.title
        else:
            text, title = body.decode(response.encoding or "utf-8", errors="replace"), ""

        clipped = text[:MAX_TEXT_CHARS]
        return {
            "tool": self.name,
            "status": "ok",
            "operation": "fetch",
            "url": str(response.url),
            "http_status": response.status_code,
            "content_type": content_type,
            "title": title,
            "text": clipped,
            "truncated": truncated_bytes or len(text) > MAX_TEXT_CHARS,
        }
