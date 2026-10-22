"""Text-to-speech provider interface.

Unset by default: in "browser" mode the client speaks the reply with
speechSynthesis, so no audio is generated or transferred server-side.
"""

import base64
from abc import ABC, abstractmethod


class TextToSpeech(ABC):
    name: str = "base"

    @abstractmethod
    async def synthesize(self, text: str) -> bytes:
        """Return audio bytes for the given text."""
        raise NotImplementedError

    async def synthesize_base64(self, text: str) -> str:
        return base64.b64encode(await self.synthesize(text)).decode()


class NullTextToSpeech(TextToSpeech):
    """Test double: emits the text itself so the pipeline can be exercised."""

    name = "null"

    async def synthesize(self, text: str) -> bytes:
        return text.encode("utf-8")
