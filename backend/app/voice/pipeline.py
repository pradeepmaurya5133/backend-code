"""Voice pipeline (Phase 3): Speech -> AI -> Action -> Speech.

Two modes, because they have very different dependencies:

**browser** (default) - the client does speech recognition and synthesis with
the Web Speech API. The server receives text and returns text plus the voice
hints the client should speak with. This needs no API keys and no audio upload,
which is why it is the default and why the React client works out of the box.

**server** - audio bytes are posted to the API, a provider transcribes them, the
agent runs, and a provider synthesises the reply. The provider interfaces are
defined here; no cloud provider is wired in, so this mode reports
`stt_not_configured` until one is registered.

Either way the middle of the pipeline is identical: the transcript goes through
the same permission-gated agent as a typed request, so speaking a command gets
no more authority than typing it.
"""

from dataclasses import dataclass

# Spoken replies should be shorter than written ones.
MAX_SPOKEN_CHARS = 700


@dataclass
class VoiceTurn:
    transcript: str
    reply: str
    status: str
    spoken: str = ""
    audio_base64: str | None = None
    detail: dict | None = None

    def to_dict(self) -> dict:
        payload = {
            "transcript": self.transcript,
            "reply": self.reply,
            "spoken": self.spoken or self.reply,
            "status": self.status,
        }
        if self.audio_base64:
            payload["audio_base64"] = self.audio_base64
        if self.detail:
            payload["detail"] = self.detail
        return payload


def speakable(text: str) -> str:
    """Trim a written answer into something reasonable to say aloud.

    Code blocks and long JSON are unlistenable, so they are summarised rather
    than read out character by character.
    """
    if not text:
        return ""
    cleaned = text.strip()
    if "```" in cleaned:
        head = cleaned.split("```", 1)[0].strip()
        cleaned = (head + " I've written the code out in the response.").strip()
    if len(cleaned) > MAX_SPOKEN_CHARS:
        cut = cleaned[:MAX_SPOKEN_CHARS]
        # Prefer to end on a sentence boundary.
        boundary = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        cleaned = (cut[: boundary + 1] if boundary > 200 else cut) + " There's more in the full response."
    return cleaned


class VoicePipeline:
    def __init__(self, agent, stt=None, tts=None, mode: str = "browser"):
        self.agent = agent
        self.stt = stt
        self.tts = tts
        self.mode = mode

    def status(self) -> dict:
        return {
            "mode": self.mode,
            "stt_configured": self.stt is not None,
            "tts_configured": self.tts is not None,
            "browser_speech_expected": self.mode == "browser",
        }

    async def from_text(self, transcript: str, session_id: str = "voice") -> VoiceTurn:
        """Speech already recognised by the client: run it and return what to say."""
        transcript = (transcript or "").strip()
        if not transcript:
            return VoiceTurn(transcript="", reply="", status="empty_transcript")

        result = await self.agent.run(transcript, session_id=session_id)
        reply = _reply_text(result)
        turn = VoiceTurn(
            transcript=transcript,
            reply=reply,
            spoken=speakable(reply),
            status=result.get("status", "unknown"),
            detail={
                k: v
                for k, v in (
                    ("confirmation_token", result.get("confirmation_token")),
                    ("pending_call", result.get("pending_call")),
                    ("question", result.get("question")),
                )
                if v
            }
            or None,
        )

        if self.tts is not None:
            turn.audio_base64 = await self.tts.synthesize_base64(turn.spoken)
        return turn

    async def from_audio(self, audio: bytes, session_id: str = "voice") -> VoiceTurn:
        """Full server-side pipeline: transcribe, run, synthesise."""
        if self.stt is None:
            return VoiceTurn(
                transcript="",
                reply="",
                status="stt_not_configured",
                detail={
                    "hint": "Register a speech-to-text provider, or use mode 'browser' "
                    "and POST the transcript to /api/voice/turn."
                },
            )
        transcript = await self.stt.transcribe(audio)
        return await self.from_text(transcript, session_id=session_id)


def _reply_text(result: dict) -> str:
    """Turn any agent outcome into something sayable."""
    status = result.get("status")
    if status == "completed":
        return result.get("answer") or "Done."
    if status == "awaiting_confirmation":
        call = result.get("pending_call") or {}
        target = (call.get("arguments") or {}).get("command") or call.get("tool") or "that action"
        return f"I need your approval before I can run {target}. Say approve, or approve it in the app."
    if status == "clarification_needed":
        return result.get("question") or "Could you give me a bit more detail?"
    if status == "refused":
        return "I can't help with that one."
    if status == "llm_not_configured":
        return "My language model isn't configured yet. Add an API key and I'll be able to answer."
    if status == "llm_unavailable":
        return "I couldn't reach my language model just now. Please try again."
    if status == "max_iterations_reached":
        return "That took more steps than I'm allowed in one go. Try narrowing it down."
    return result.get("detail") or "Something went wrong."
