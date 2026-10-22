"""Provider-agnostic LLM interface.

The agent loop is written against these types so the Anthropic client can be
swapped for a scripted one in tests without touching agent logic.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class LLMToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[LLMToolCall] = field(default_factory=list)
    # "end_turn" | "tool_use" | "refusal" | "pause_turn" | "max_tokens" | ...
    stop_reason: str = "end_turn"
    # Provider-native assistant content, stored verbatim so it can be replayed
    # on the next request. Thinking blocks must survive this round trip.
    content_blocks: list = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    # Populated only when stop_reason == "refusal".
    refusal: dict | None = None

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        output_schema: dict | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

    @property
    def configured(self) -> bool:
        return True


class LLMUnavailable(RuntimeError):
    """The provider could not produce a response.

    The agent surfaces this as a run status rather than a 500, so a missing key
    or a rate limit reads as an agent outcome instead of a server crash.
    """
