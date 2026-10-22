"""Provider normalisation tests.

These exercise AnthropicProvider against a stub client, so they verify the
request shape and response mapping without a network call or an API key.
"""

import pytest

from app.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from app.llm.base import LLMUnavailable


class Block:
    """Stands in for an SDK content block."""

    def __init__(self, **fields):
        self.__dict__.update(fields)

    def model_dump(self, exclude_none=False):
        return {k: v for k, v in self.__dict__.items() if not exclude_none or v is not None}


class Usage:
    def __init__(self, input_tokens=10, output_tokens=5):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class Response:
    def __init__(self, content, stop_reason="end_turn", stop_details=None):
        self.content = content
        self.stop_reason = stop_reason
        self.stop_details = stop_details
        self.usage = Usage()


class StubMessages:
    def __init__(self, response=None, error=None):
        self._response = response
        self._error = error
        self.requests = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        if self._error:
            raise self._error
        return self._response


class StubClient:
    def __init__(self, response=None, error=None, beta_error=None):
        self.messages = StubMessages(response, error)

        class Beta:
            pass

        self.beta = Beta()
        self.beta.messages = StubMessages(response, beta_error or error)


def provider(client, **kwargs):
    return AnthropicProvider(api_key="test-key", client=client, **kwargs)


# --------------- request shape ---------------


@pytest.mark.asyncio
async def test_request_uses_adaptive_thinking_and_effort():
    client = StubClient(Response([Block(type="text", text="hi")]))
    await provider(client, effort="xhigh").complete("sys", [{"role": "user", "content": "hi"}])

    sent = client.beta.messages.requests[0]
    assert sent["model"] == "claude-opus-5"
    # budget_tokens is rejected on this model family; adaptive replaces it.
    assert sent["thinking"] == {"type": "adaptive"}
    assert "budget_tokens" not in str(sent["thinking"])
    assert sent["output_config"]["effort"] == "xhigh"
    # Sampling params are removed on this model family.
    assert "temperature" not in sent


@pytest.mark.asyncio
async def test_server_side_fallbacks_are_enabled_by_default():
    client = StubClient(Response([Block(type="text", text="hi")]))
    await provider(client).complete("sys", [{"role": "user", "content": "hi"}])

    sent = client.beta.messages.requests[0]
    assert sent["betas"] == [FALLBACK_BETA]
    assert sent["fallbacks"] == "default"


@pytest.mark.asyncio
async def test_fallbacks_can_be_disabled_and_use_the_stable_endpoint():
    client = StubClient(Response([Block(type="text", text="hi")]))
    await provider(client, server_side_fallbacks=False).complete("sys", [{"role": "user", "content": "x"}])

    assert client.beta.messages.requests == []
    assert "betas" not in client.messages.requests[0]


@pytest.mark.asyncio
async def test_output_schema_becomes_a_json_schema_format():
    client = StubClient(Response([Block(type="text", text="{}")]))
    schema = {"type": "object", "properties": {}}
    await provider(client).complete("sys", [{"role": "user", "content": "x"}], output_schema=schema)

    fmt = client.beta.messages.requests[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] is schema


@pytest.mark.asyncio
async def test_tools_are_passed_through_only_when_present():
    client = StubClient(Response([Block(type="text", text="hi")]))
    await provider(client).complete("sys", [{"role": "user", "content": "x"}])
    assert "tools" not in client.beta.messages.requests[0]

    client2 = StubClient(Response([Block(type="text", text="hi")]))
    tools = [{"name": "t", "description": "d", "input_schema": {}}]
    await provider(client2).complete("sys", [{"role": "user", "content": "x"}], tools=tools)
    assert client2.beta.messages.requests[0]["tools"] == tools


# --------------- response normalisation ---------------


@pytest.mark.asyncio
async def test_text_response_is_normalised():
    client = StubClient(Response([Block(type="text", text="the answer")]))
    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])

    assert result.text == "the answer"
    assert result.stop_reason == "end_turn"
    assert result.wants_tools is False
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}


@pytest.mark.asyncio
async def test_tool_use_block_becomes_a_tool_call():
    client = StubClient(
        Response(
            [
                Block(type="text", text="Let me check."),
                Block(type="tool_use", id="tu_1", name="filesystem", input={"operation": "list"}),
            ],
            stop_reason="tool_use",
        )
    )
    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])

    assert result.wants_tools is True
    assert result.tool_calls[0].id == "tu_1"
    assert result.tool_calls[0].name == "filesystem"
    assert result.tool_calls[0].arguments == {"operation": "list"}
    assert result.text == "Let me check."


@pytest.mark.asyncio
async def test_string_encoded_tool_input_is_json_parsed():
    """Tool input escaping varies by model - it must be parsed, never matched."""
    client = StubClient(
        Response(
            [Block(type="tool_use", id="tu_1", name="filesystem", input='{"operation": "list"}')],
            stop_reason="tool_use",
        )
    )
    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])
    assert result.tool_calls[0].arguments == {"operation": "list"}


@pytest.mark.asyncio
async def test_thinking_blocks_are_preserved_for_replay():
    """Thinking blocks must be echoed back unchanged on the same model."""
    client = StubClient(
        Response([Block(type="thinking", thinking="reasoning"), Block(type="text", text="done")])
    )
    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])

    assert [b["type"] for b in result.content_blocks] == ["thinking", "text"]
    assert result.content_blocks[0]["thinking"] == "reasoning"


@pytest.mark.asyncio
async def test_refusal_is_captured_with_its_category():
    details = Block(type="refusal", category="cyber", explanation="declined")
    client = StubClient(Response([], stop_reason="refusal", stop_details=details))
    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])

    assert result.stop_reason == "refusal"
    assert result.refusal == {"category": "cyber", "explanation": "declined"}


# --------------- error mapping ---------------


@pytest.mark.asyncio
async def test_connection_error_becomes_llm_unavailable():
    from anthropic import APIConnectionError

    client = StubClient(error=APIConnectionError(request=None))
    with pytest.raises(LLMUnavailable, match="Could not reach"):
        await provider(client).complete("sys", [{"role": "user", "content": "q"}])


@pytest.mark.asyncio
async def test_rejected_beta_falls_back_to_the_stable_endpoint():
    """If the fallbacks beta is not enabled for the account, still answer."""
    import httpx2

    from anthropic import BadRequestError

    rejected = BadRequestError(
        message="unknown beta",
        response=httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    client = StubClient(Response([Block(type="text", text="recovered")]), beta_error=rejected)

    result = await provider(client).complete("sys", [{"role": "user", "content": "q"}])
    assert result.text == "recovered"
    # It retried on the stable endpoint and stopped using the beta.
    assert len(client.messages.requests) == 1
