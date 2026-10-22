"""The API tool is the widest-reaching capability, so these tests are mostly
about what it refuses: unlisted hosts, internal addresses, model-supplied
credentials, and writes without the write permission."""

import pytest

from app.security.permissions import PermissionGate
from app.tools.http_api import HttpApiTool


async def public_resolver(hostname):
    """Pretend every hostname resolves to a public address."""
    return ["93.184.216.34"]


async def private_resolver(hostname):
    """Pretend every hostname resolves to loopback."""
    return ["127.0.0.1"]


class StubResponse:
    def __init__(self, status=200, body='{"ok":true}', content_type="application/json"):
        self.status_code = status
        self.text = body
        self.headers = {"content-type": content_type}
        self.url = "https://api.example.com/v1/thing"

    @property
    def is_success(self):
        return 200 <= self.status_code < 300


class StubClient:
    def __init__(self, response=None, error=None):
        self._response = response or StubResponse()
        self._error = error
        self.calls = []

    async def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if self._error:
            raise self._error
        return self._response


class StubSecrets:
    def __init__(self, values):
        self.values = values

    async def reveal(self, name):
        return self.values.get(name)


def tool(granted=("api.call",), hosts=("api.example.com",), secrets=None, client=None, resolver=None):
    gate = PermissionGate()
    for permission in granted:
        gate.grant(permission)
    return HttpApiTool(
        gate,
        allowed_hosts=set(hosts),
        secrets=secrets,
        client=client or StubClient(),
        resolver=resolver or public_resolver,
    )


# --------------- permissions ---------------


@pytest.mark.asyncio
async def test_call_requires_api_call_permission():
    result = await tool(granted=()).execute({"url": "https://api.example.com/v1/thing"})
    assert result["status"] == "permission_required"
    assert result["permission"] == "api.call"


@pytest.mark.asyncio
async def test_write_methods_need_api_write():
    """api.call alone must not allow a POST."""
    result = await tool().execute({"url": "https://api.example.com/v1/thing", "method": "POST"})
    assert result["status"] == "permission_required"
    assert result["permission"] == "api.write"


@pytest.mark.asyncio
async def test_write_succeeds_once_api_write_is_granted():
    client = StubClient()
    result = await tool(granted=("api.call", "api.write"), client=client).execute(
        {"url": "https://api.example.com/v1/thing", "method": "POST", "body": {"a": 1}}
    )
    assert result["status"] == "ok"
    assert client.calls[0]["json"] == {"a": 1}


# --------------- host allowlist ---------------


@pytest.mark.asyncio
async def test_empty_allowlist_reaches_nothing():
    """The capability is off until an operator opts a host in."""
    client = StubClient()
    result = await tool(hosts=(), client=client).execute({"url": "https://api.example.com/v1/x"})
    assert result["status"] == "no_hosts_allowlisted"
    assert client.calls == []


@pytest.mark.asyncio
async def test_unlisted_host_is_refused():
    client = StubClient()
    result = await tool(client=client).execute({"url": "https://evil.example.net/steal"})
    assert result["status"] == "host_not_allowlisted"
    assert result["host"] == "evil.example.net"
    assert client.calls == []


@pytest.mark.asyncio
async def test_allowlist_entry_covers_subdomains():
    result = await tool(hosts=("example.com",)).execute({"url": "https://api.example.com/v1/x"})
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_allowlist_does_not_match_a_suffix_lookalike():
    """'example.com' must not authorise 'notexample.com'."""
    result = await tool(hosts=("example.com",)).execute({"url": "https://notexample.com/x"})
    assert result["status"] == "host_not_allowlisted"


@pytest.mark.asyncio
async def test_internal_address_refused_even_if_allowlisted():
    """An allowlist entry must not become a path to internal services."""
    result = await tool(hosts=("localhost",), resolver=private_resolver).execute(
        {"url": "http://localhost:8000/api/metrics"}
    )
    assert result["status"] == "private_address_refused"


# --------------- credentials ---------------


@pytest.mark.asyncio
async def test_model_supplied_authorization_header_is_stripped():
    """The model must not be able to set credentials directly."""
    client = StubClient()
    await tool(client=client).execute(
        {
            "url": "https://api.example.com/v1/x",
            "headers": {"Authorization": "Bearer leaked-from-context", "X-Trace": "ok"},
        }
    )
    sent = client.calls[0]["headers"]
    assert "Authorization" not in sent
    assert sent["X-Trace"] == "ok"


@pytest.mark.asyncio
async def test_cookie_header_is_stripped():
    client = StubClient()
    await tool(client=client).execute(
        {"url": "https://api.example.com/v1/x", "headers": {"Cookie": "session=abc"}}
    )
    assert "Cookie" not in client.calls[0]["headers"]


@pytest.mark.asyncio
async def test_named_secret_is_injected_server_side():
    """The model names a secret; the server supplies the value."""
    client = StubClient()
    secrets = StubSecrets({"example_token": "s3cr3t"})
    await tool(secrets=secrets, client=client).execute(
        {"url": "https://api.example.com/v1/x", "auth_secret": "example_token"}
    )
    assert client.calls[0]["headers"]["Authorization"] == "Bearer s3cr3t"


@pytest.mark.asyncio
async def test_unknown_secret_is_refused_without_calling_out():
    client = StubClient()
    result = await tool(secrets=StubSecrets({}), client=client).execute(
        {"url": "https://api.example.com/v1/x", "auth_secret": "nope"}
    )
    assert result["status"] == "unknown_secret"
    assert client.calls == []


# --------------- responses ---------------


@pytest.mark.asyncio
async def test_json_response_is_parsed():
    client = StubClient(StubResponse(body='{"value":42}'))
    result = await tool(client=client).execute({"url": "https://api.example.com/v1/x"})
    assert result["json"] == {"value": 42}


@pytest.mark.asyncio
async def test_http_error_status_is_surfaced_not_raised():
    client = StubClient(StubResponse(status=404, body='{"error":"missing"}'))
    result = await tool(client=client).execute({"url": "https://api.example.com/v1/x"})
    assert result["status"] == "http_error"
    assert result["http_status"] == 404


@pytest.mark.asyncio
async def test_non_json_body_is_returned_as_text():
    client = StubClient(StubResponse(body="plain text", content_type="text/plain"))
    result = await tool(client=client).execute({"url": "https://api.example.com/v1/x"})
    assert result["body"] == "plain text"


@pytest.mark.asyncio
async def test_timeout_is_reported():
    import httpx

    client = StubClient(error=httpx.TimeoutException("slow"))
    result = await tool(client=client).execute({"url": "https://api.example.com/v1/x"})
    assert result["status"] == "timeout"


@pytest.mark.asyncio
async def test_unsupported_method_and_missing_url():
    assert (await tool().execute({"url": "", "method": "GET"}))["status"] == "missing_url"
    result = await tool().execute({"url": "https://api.example.com/x", "method": "TRACE"})
    assert result["status"] == "unsupported_method"


@pytest.mark.asyncio
async def test_unlisted_host_is_never_resolved():
    """Resolving an unapproved host would leak data to its nameserver."""
    resolved = []

    async def spy(hostname):
        resolved.append(hostname)
        return ["93.184.216.34"]

    result = await tool(resolver=spy).execute({"url": "https://exfil.attacker.net/?data=secret"})
    assert result["status"] == "host_not_allowlisted"
    assert resolved == [], "the allowlist must be checked before any DNS lookup"


@pytest.mark.asyncio
async def test_empty_allowlist_does_not_resolve_either():
    resolved = []

    async def spy(hostname):
        resolved.append(hostname)
        return ["93.184.216.34"]

    result = await tool(hosts=(), resolver=spy).execute({"url": "https://api.example.com/x"})
    assert result["status"] == "no_hosts_allowlisted"
    assert resolved == []
