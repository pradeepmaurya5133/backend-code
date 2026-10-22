"""Speech-to-text provider interface.

No cloud provider is wired in. The default voice mode is "browser", where the
client's Web Speech API does recognition and posts the transcript, so the stack
has a working voice loop without any provider.
"""

from abc import ABC, abstractmethod


class SpeechToText(ABC):
    name: str = "base"

    @abstractmethod
    async def transcribe(self, audio: bytes) -> str:
        """Return the transcript for raw audio bytes."""
        raise NotImplementedError


class EchoSpeechToText(SpeechToText):
    """Test double: treats the payload as UTF-8 text rather than audio."""

    name = "echo"

    async def transcribe(self, audio: bytes) -> str:
        return audio.decode("utf-8", errors="replace").strip()
