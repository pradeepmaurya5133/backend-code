"""Voice pipeline (Phase 3): Speech -> AI -> Action -> Speech."""

import pytest

from app.voice.pipeline import VoicePipeline, speakable
from app.voice.speech_to_text import EchoSpeechToText
from app.voice.text_to_speech import NullTextToSpeech


class FakeAgent:
    def __init__(self, result=None):
        self.result = result or {"status": "completed", "answer": "It is 21 degrees."}
        self.calls = []

    async def run(self, message, session_id="default", plan=True):
        self.calls.append({"message": message, "session_id": session_id})
        return self.result


# --------------- speakable ---------------


def test_short_text_is_spoken_verbatim():
    assert speakable("All done.") == "All done."


def test_code_blocks_are_not_read_aloud():
    spoken = speakable("Here is the fix:\n```python\nprint(1)\n```\nThat's it.")
    assert "```" not in spoken
    assert "print(1)" not in spoken
    assert "written the code out" in spoken


def test_long_text_is_cut_on_a_sentence_boundary():
    text = ("This is a sentence. " * 100).strip()
    spoken = speakable(text)
    assert len(spoken) < len(text)
    assert spoken.endswith("There's more in the full response.")


def test_empty_text_stays_empty():
    assert speakable("") == ""
    assert speakable(None) == ""


# --------------- pipeline ---------------


@pytest.mark.asyncio
async def test_transcript_runs_through_the_agent():
    agent = FakeAgent()
    turn = await VoicePipeline(agent).from_text("what is the weather", session_id="v1")

    assert turn.status == "completed"
    assert turn.reply == "It is 21 degrees."
    assert turn.spoken == "It is 21 degrees."
    # Speaking a command must go through the same agent as typing it.
    assert agent.calls[0] == {"message": "what is the weather", "session_id": "v1"}


@pytest.mark.asyncio
async def test_empty_transcript_is_rejected_without_calling_the_agent():
    agent = FakeAgent()
    turn = await VoicePipeline(agent).from_text("   ")
    assert turn.status == "empty_transcript"
    assert agent.calls == []


@pytest.mark.asyncio
async def test_approval_request_is_spoken_as_a_request():
    agent = FakeAgent(
        {
            "status": "awaiting_confirmation",
            "confirmation_token": "tok_1",
            "pending_call": {"tool": "terminal", "arguments": {"command": "python --version"}},
        }
    )
    turn = await VoicePipeline(agent).from_text("check python")

    assert turn.status == "awaiting_confirmation"
    assert "approval" in turn.reply
    assert "python --version" in turn.reply
    assert turn.detail["confirmation_token"] == "tok_1"


@pytest.mark.asyncio
async def test_clarification_is_spoken_as_the_question():
    agent = FakeAgent({"status": "clarification_needed", "question": "Which file did you mean?"})
    turn = await VoicePipeline(agent).from_text("fix it")
    assert turn.reply == "Which file did you mean?"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,fragment",
    [
        ("refused", "can't help"),
        ("llm_not_configured", "isn't configured"),
        ("llm_unavailable", "couldn't reach"),
        ("max_iterations_reached", "more steps"),
    ],
)
async def test_every_outcome_has_something_sayable(status, fragment):
    turn = await VoicePipeline(FakeAgent({"status": status})).from_text("do a thing")
    assert fragment in turn.reply


@pytest.mark.asyncio
async def test_audio_without_stt_reports_configuration():
    turn = await VoicePipeline(FakeAgent()).from_audio(b"\x00\x01")
    assert turn.status == "stt_not_configured"
    assert "browser" in turn.detail["hint"]


@pytest.mark.asyncio
async def test_full_server_pipeline_with_providers():
    """Speech -> AI -> Action -> Speech, end to end, with test doubles."""
    pipeline = VoicePipeline(FakeAgent(), stt=EchoSpeechToText(), tts=NullTextToSpeech(), mode="server")
    turn = await pipeline.from_audio(b"what is the weather")

    assert turn.transcript == "what is the weather"
    assert turn.reply == "It is 21 degrees."
    assert turn.audio_base64  # synthesised audio came back
    payload = turn.to_dict()
    assert payload["spoken"] == "It is 21 degrees."
    assert "audio_base64" in payload


def test_status_reports_mode_and_providers():
    assert VoicePipeline(FakeAgent()).status() == {
        "mode": "browser",
        "stt_configured": False,
        "tts_configured": False,
        "browser_speech_expected": True,
    }
    configured = VoicePipeline(FakeAgent(), stt=EchoSpeechToText(), tts=NullTextToSpeech(), mode="server")
    assert configured.status()["stt_configured"] is True
    assert configured.status()["browser_speech_expected"] is False
