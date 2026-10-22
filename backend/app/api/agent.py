from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_READ, SCOPE_RUN, require

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentRequest(BaseModel):
    message: str = Field(min_length=1)
    session_id: str = "default"
    # Set false to skip the planning call and go straight to the tool loop.
    plan: bool = True


class SessionRequest(BaseModel):
    session_id: str = "default"


@router.get("/status")
async def status(_=Depends(require(SCOPE_READ))):
    return runtime.llm_status()


@router.post("/run")
async def run_agent(request: AgentRequest, _=Depends(require(SCOPE_RUN))):
    return await runtime.agent.run(request.message, request.session_id, request.plan)


@router.post("/resume")
async def resume_agent(request: SessionRequest, _=Depends(require(SCOPE_RUN))):
    """Continue a turn that stopped for human approval."""
    return await runtime.agent.resume(request.session_id)


@router.get("/pending")
async def pending(session_id: str = "default", _=Depends(require(SCOPE_READ))):
    return await runtime.agent.pending(session_id)


@router.post("/reset")
async def reset_session(request: SessionRequest, _=Depends(require(SCOPE_RUN))):
    cleared = await runtime.conversations.reset(request.session_id)
    return {"status": "reset" if cleared else "no_such_session", "session_id": request.session_id}


@router.get("/sessions")
async def sessions(_=Depends(require(SCOPE_READ))):
    return {"sessions": await runtime.conversations.sessions()}


@router.get("/transcript")
async def transcript(session_id: str = "default", _=Depends(require(SCOPE_READ))):
    return {"session_id": session_id, "messages": await runtime.conversations.transcript(session_id)}
