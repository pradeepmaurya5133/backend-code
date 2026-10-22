from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core import runtime
from app.security.auth import SCOPE_READ, SCOPE_RUN, require

router = APIRouter(prefix="/tools", tags=["tools"])


class ToolRequest(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)
    session_id: str = "default"


@router.get("")
async def list_tools(_=Depends(require(SCOPE_READ))):
    return {"tools": runtime.registry.describe()}


@router.get("/schemas")
async def tool_schemas(_=Depends(require(SCOPE_READ))):
    """Exactly what the model is shown."""
    return {"tools": runtime.registry.definitions()}


@router.post("/execute")
async def execute_tool(request: ToolRequest, _=Depends(require(SCOPE_RUN))):
    """Drive a tool directly, bypassing the model. The same gates apply."""
    tool = runtime.registry.get(request.tool)
    if not tool:
        return {"status": "tool_not_found", "tool": request.tool}
    runtime.registry.bind_session(request.session_id)
    return await tool.execute(request.arguments)
