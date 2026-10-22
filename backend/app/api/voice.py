from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_READ, SCOPE_RUN, require

router = APIRouter(prefix="/voice", tags=["voice"])

MAX_AUDIO_BYTES = 10 * 1024 * 1024


class VoiceTurnRequest(BaseModel):
    transcript: str = Field(min_length=1)
    session_id: str = "voice"


@router.get("/status")
async def status(_=Depends(require(SCOPE_READ))):
    return runtime.voice.status()


@router.post("/turn")
async def voice_turn(request: VoiceTurnRequest, _=Depends(require(SCOPE_RUN))):
    """Browser mode: the client recognised the speech and sends the text.

    Returns the written reply plus a `spoken` form trimmed for speech synthesis.
    """
    turn = await runtime.voice.from_text(request.transcript, request.session_id)
    return turn.to_dict()


@router.post("/audio")
async def voice_audio(
    session_id: str = "voice",
    file: UploadFile = File(...),
    _=Depends(require(SCOPE_RUN)),
):
    """Server mode: upload audio, get a reply. Needs an STT provider."""
    audio = await file.read(MAX_AUDIO_BYTES + 1)
    if len(audio) > MAX_AUDIO_BYTES:
        return {"status": "audio_too_large", "max_bytes": MAX_AUDIO_BYTES}
    turn = await runtime.voice.from_audio(audio, session_id)
    return turn.to_dict()
