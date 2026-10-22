from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_READ, SCOPE_RUN, require

router = APIRouter(prefix="/memory", tags=["memory"])


class RememberRequest(BaseModel):
    content: str = Field(min_length=1)
    session_id: str = "default"
    kind: str = "fact"
    importance: float = 0.6


@router.get("")
async def recall(session_id: str = "default", kind: str = None, _=Depends(require(SCOPE_READ))):
    return {"session_id": session_id, "memories": await runtime.memory.recall(session_id, kind)}


@router.get("/search")
async def search(term: str, session_id: str = "default", _=Depends(require(SCOPE_READ))):
    return {"term": term, "matches": await runtime.memory.search(session_id, term)}


@router.get("/context")
async def context(session_id: str = "default", _=Depends(require(SCOPE_READ))):
    """Exactly the memory text injected into the system prompt."""
    return {"session_id": session_id, "prompt_context": await runtime.memory.prompt_context(session_id)}


@router.post("")
async def remember(request: RememberRequest, _=Depends(require(SCOPE_RUN))):
    if request.kind not in ("fact", "episodic"):
        return {"status": "unsupported_kind", "kind": request.kind}
    memory_id = await runtime.memory_repository.remember(
        request.session_id,
        request.content,
        kind=request.kind,
        importance=max(0.0, min(1.0, request.importance)),
    )
    return {"status": "ok", "id": memory_id}


@router.delete("/{memory_id}")
async def forget(memory_id: int, _=Depends(require(SCOPE_RUN))):
    return {"status": "ok" if await runtime.memory.forget(memory_id) else "not_found"}
