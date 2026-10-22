"""Offline providers: one for tests, one for a missing API key.

ScriptedProvider replays a fixed list of LLMResponse objects, which lets the
agent loop - including the suspend/resume path - be tested deterministically
without a network call or an API key.
"""

from app.llm.base import LLMProvider, LLMResponse, LLMToolCall


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def complete(self, system, messages, tools=None, output_schema=None) -> LLMResponse:
        # Record what the agent sent so tests can assert on prompt construction.
        self.calls.append(
            {
                "system": system,
                "messages": messages,
                "tool_names": [t["name"] for t in (tools or [])],
                "output_schema": output_schema,
            }
        )
        if not self._responses:
            return LLMResponse(text="(scripted provider exhausted)", stop_reason="end_turn")
        return self._responses.pop(0)

    @staticmethod
    def text(message: str) -> LLMResponse:
        return LLMResponse(
            text=message,
            stop_reason="end_turn",
            content_blocks=[{"type": "text", "text": message}],
        )

    @staticmethod
    def tool(name: str, arguments: dict, call_id: str = "call_1", preamble: str = "") -> LLMResponse:
        blocks = []
        if preamble:
            blocks.append({"type": "text", "text": preamble})
        blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": arguments})
        return LLMResponse(
            text=preamble,
            tool_calls=[LLMToolCall(id=call_id, name=name, arguments=arguments)],
            stop_reason="tool_use",
            content_blocks=blocks,
        )

    @staticmethod
    def tools(calls: list[tuple], preamble: str = "") -> LLMResponse:
        """Several tool calls in one assistant turn (parallel tool use)."""
        blocks = []
        if preamble:
            blocks.append({"type": "text", "text": preamble})
        tool_calls = []
        for index, (name, arguments) in enumerate(calls):
            call_id = f"call_{index + 1}"
            blocks.append({"type": "tool_use", "id": call_id, "name": name, "input": arguments})
            tool_calls.append(LLMToolCall(id=call_id, name=name, arguments=arguments))
        return LLMResponse(text=preamble, tool_calls=tool_calls, stop_reason="tool_use", content_blocks=blocks)


class UnconfiguredProvider(LLMProvider):
    """Stands in when no API key is set, so the app still boots and explains itself."""

    name = "unconfigured"

    @property
    def configured(self) -> bool:
        return False

    async def complete(self, system, messages, tools=None, output_schema=None) -> LLMResponse:
        return LLMResponse(
            text=(
                "No language model is configured. Set ANTHROPIC_API_KEY in backend/.env "
                "to enable natural-language planning and tool selection."
            ),
            stop_reason="not_configured",
        )
