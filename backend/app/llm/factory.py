from app.core.config import settings
from app.llm.base import LLMProvider
from app.llm.scripted import UnconfiguredProvider


def build_provider() -> LLMProvider:
    """Return a live Claude provider when a key is present, else a safe stand-in."""
    if not settings.anthropic_api_key:
        return UnconfiguredProvider()

    # Imported lazily so the app boots even if the SDK is absent.
    from app.llm.anthropic_provider import AnthropicProvider

    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=settings.llm_model,
        max_tokens=settings.llm_max_tokens,
        effort=settings.llm_effort,
        server_side_fallbacks=settings.llm_server_side_fallbacks,
    )
