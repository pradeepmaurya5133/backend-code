"""Claude provider built on the official `anthropic` SDK."""

import json

from anthropic import (
    APIConnectionError,
    APIStatusError,
    AsyncAnthropic,
    NotFoundError,
    RateLimitError,
)

from app.llm.base import LLMProvider, LLMResponse, LLMToolCall, LLMUnavailable

# Routes a classifier refusal to a fallback model server-side, so a declined
# turn still returns usable content instead of dead-ending the agent loop.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str = "claude-opus-5",
        max_tokens: int = 16000,
        effort: str = "high",
        server_side_fallbacks: bool = True,
        client=None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.effort = effort
        self.server_side_fallbacks = server_side_fallbacks
        self._client = client if client is not None else AsyncAnthropic(api_key=api_key)

    async def complete(self, system, messages, tools=None, output_schema=None) -> LLMResponse:
        request = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": system,
            "messages": messages,
            # Adaptive thinking lets Claude decide how much to reason per turn.
            # `budget_tokens` is rejected on this model family.
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": self.effort},
        }
        if tools:
            request["tools"] = tools
        if output_schema:
            request["output_config"]["format"] = {
                "type": "json_schema",
                "schema": output_schema,
            }

        try:
            if self.server_side_fallbacks:
                response = await self._client.beta.messages.create(
                    betas=[FALLBACK_BETA], fallbacks="default", **request
                )
            else:
                response = await self._client.messages.create(**request)
        except NotFoundError as exc:
            raise LLMUnavailable(f"Model '{self.model}' not available to this account: {exc}") from exc
        except RateLimitError as exc:
            raise LLMUnavailable(f"Rate limited by the Claude API: {exc}") from exc
        except APIStatusError as exc:
            # A rejected beta should degrade to the stable endpoint, not fail the turn.
            if self.server_side_fallbacks and exc.status_code == 400:
                self.server_side_fallbacks = False
                response = await self._client.messages.create(**request)
            else:
                raise LLMUnavailable(f"Claude API error {exc.status_code}: {exc}") from exc
        except APIConnectionError as exc:
            raise LLMUnavailable(f"Could not reach the Claude API: {exc}") from exc

        return self._normalise(response)

    @staticmethod
    def _normalise(response) -> LLMResponse:
        text_parts, tool_calls, blocks = [], [], []

        for block in response.content:
            # Store the native block so thinking/tool_use survive the replay.
            blocks.append(block.model_dump(exclude_none=True))
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                arguments = block.input
                if isinstance(arguments, str):
                    # Escaping varies by model; never string-match the raw input.
                    arguments = json.loads(arguments)
                tool_calls.append(LLMToolCall(id=block.id, name=block.name, arguments=arguments or {}))

        refusal = None
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            refusal = {
                "category": getattr(details, "category", None),
                "explanation": getattr(details, "explanation", None),
            }

        usage = {}
        if getattr(response, "usage", None):
            usage = {
                "input_tokens": getattr(response.usage, "input_tokens", None),
                "output_tokens": getattr(response.usage, "output_tokens", None),
            }

        return LLMResponse(
            text="\n".join(p for p in text_parts if p).strip(),
            tool_calls=tool_calls,
            stop_reason=response.stop_reason or "end_turn",
            content_blocks=blocks,
            usage=usage,
            refusal=refusal,
        )
