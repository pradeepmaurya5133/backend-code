"""Web tool: URL safety, content reduction, permission gating."""

import pytest

from app.security.permissions import PermissionGate
from app.tools.web import WebTool, validate_url

async def public_resolver(hostname):
    """Pretend every hostname resolves to a public address."""
    return ["93.184.216.34"]


async def private_resolver(hostname):
    """Pretend every hostname resolves to loopback."""
    return ["127.0.0.1"]


HTML = """<html><head><title>Subh Docs</title><style>body{color:red}</style>
<script>alert('x')</script></head>
<body><h1>Heading</h1><p>First paragraph.</p><p>Second   paragraph.</p></body></html>"""


class StubResponse:
    def __init__(self, content=b"", status=200, content_type="text/html", url="https://example.com/"):
        self.content = content
        self.status_code = status
        self.headers = {"content-type": content_type}
        self.url = url
        self.encoding = "utf-8"
        self.text = content.decode("utf-8", errors="replace")

    @property
    def is_success(self):
        return 200 <= self.status_code < 300


class StubClient:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.calls = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if self._error:
            raise self._error
        return self._response


def tool(granted=("web.fetch", "web.search"), **kwargs):
    gate = PermissionGate()
    for permission in granted:
        gate.grant(permission)
    kwargs.setdefault("resolver", public_resolver)
    return WebTool(gate, **kwargs)


# --------------- URL validation ---------------


@pytest.mark.parametrize(
    "url",
    ["file:///etc/passwd", "data:text/html,<h1>x", "javascript:alert(1)", "ftp://example.com/x"],
)
@pytest.mark.asyncio
async def test_dangerous_schemes_are_refused(url):
    _, error = await validate_url(url, public_resolver)
    assert error["status"] == "scheme_refused"


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8000/api/health",
        "http://127.0.0.1/",
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://10.0.0.5/",
        "http://192.168.1.1/",
    ],
)
@pytest.mark.asyncio
async def test_private_and_metadata_addresses_are_refused(url):
    """An SSRF guard: tools must not be able to reach internal services.

    Resolution is real here - these literals must be classified as private.
    """
    _, error = await validate_url(url)
    assert error["status"] == "private_address_refused"


@pytest.mark.asyncio
async def test_public_https_is_accepted():
    url, error = await validate_url("https://example.com/page", public_resolver)
    assert error is None
    assert url == "https://example.com/page"


@pytest.mark.asyncio
async def test_unresolvable_host_is_refused():
    async def nothing(hostname):
        return None

    _, error = await validate_url("https://does-not-exist.invalid/", nothing)
    assert error["status"] == "host_unresolvable"


@pytest.mark.asyncio
async def test_public_name_pointing_at_loopback_is_refused():
    """DNS rebinding guard: the name looks fine, the address does not."""
    _, error = await validate_url("https://sneaky.example.com/", private_resolver)
    assert error["status"] == "private_address_refused"


# --------------- permissions ---------------


@pytest.mark.asyncio
async def test_fetch_requires_web_fetch_permission():
    result = await tool(granted=()).execute({"operation": "fetch", "query": "https://example.com"})
    assert result["status"] == "permission_required"
    assert result["permission"] == "web.fetch"


@pytest.mark.asyncio
async def test_search_requires_web_search_permission():
    # web.search is granted by default, so it has to be revoked to test the gate.
    gate = PermissionGate()
    gate.revoke("web.search")
    result = await WebTool(gate).execute({"operation": "search", "query": "subh ai"})
    assert result["status"] == "permission_required"
    assert result["permission"] == "web.search"


@pytest.mark.asyncio
async def test_permission_is_checked_before_the_network():
    """A refused call must not even attempt a request."""
    client = StubClient(StubResponse(b"<p>hi</p>"))
    result = await tool(granted=(), client=client).execute(
        {"operation": "fetch", "query": "https://example.com"}
    )
    assert result["status"] == "permission_required"
    assert client.calls == []


# --------------- fetch ---------------


@pytest.mark.asyncio
async def test_html_is_reduced_to_readable_text():
    client = StubClient(StubResponse(HTML.encode()))
    result = await tool(client=client).execute({"operation": "fetch", "query": "https://example.com"})

    assert result["status"] == "ok"
    assert result["title"] == "Subh Docs"
    assert "First paragraph." in result["text"]
    # Script and style content must never reach the model.
    assert "alert(" not in result["text"]
    assert "color:red" not in result["text"]


@pytest.mark.asyncio
async def test_long_pages_are_truncated_and_flagged():
    body = ("<p>" + "word " * 20000 + "</p>").encode()
    client = StubClient(StubResponse(body))
    result = await tool(client=client, max_bytes=5_000).execute(
        {"operation": "fetch", "query": "https://example.com"}
    )
    assert result["truncated"] is True
    assert len(result["text"]) <= 20_000


@pytest.mark.asyncio
async def test_non_html_is_returned_as_text():
    client = StubClient(StubResponse(b'{"ok":true}', content_type="application/json"))
    result = await tool(client=client).execute({"operation": "fetch", "query": "https://example.com/a.json"})
    assert result["status"] == "ok"
    assert result["text"] == '{"ok":true}'


@pytest.mark.asyncio
async def test_timeout_is_reported_not_raised():
    import httpx

    client = StubClient(error=httpx.TimeoutException("too slow"))
    result = await tool(client=client).execute({"operation": "fetch", "query": "https://example.com"})
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_transport_error_is_reported_not_raised():
    import httpx

    client = StubClient(error=httpx.ConnectError("refused"))
    result = await tool(client=client).execute({"operation": "fetch", "query": "https://example.com"})
    assert result["status"] == "fetch_failed"


# --------------- search ---------------


@pytest.mark.asyncio
async def test_search_without_a_provider_says_so():
    result = await tool().execute({"operation": "search", "query": "subh ai"})
    assert result["status"] == "provider_not_configured"


@pytest.mark.asyncio
async def test_search_uses_a_configured_provider():
    class Provider:
        async def search(self, query):
            return [{"title": "Result", "url": "https://example.com"}]

    result = await tool(search_provider=Provider()).execute({"operation": "search", "query": "x"})
    assert result["status"] == "ok"
    assert result["results"][0]["title"] == "Result"


@pytest.mark.asyncio
async def test_provider_failure_does_not_crash_the_turn():
    class Broken:
        async def search(self, query):
            raise RuntimeError("provider exploded")

    result = await tool(search_provider=Broken()).execute({"operation": "search", "query": "x"})
    assert result["status"] == "search_failed"


@pytest.mark.asyncio
async def test_missing_query_and_bad_operation():
    assert (await tool().execute({"operation": "fetch", "query": "  "}))["status"] == "missing_query"
    assert (await tool().execute({"operation": "delete", "query": "x"}))["status"] == "unsupported_operation"
