import pytest
from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.tools.filesystem import FilesystemTool
from app.tools.terminal import TerminalTool
@pytest.mark.asyncio
async def test_filesystem_list(tmp_path):
    result=await FilesystemTool(PermissionGate(),WorkspacePolicy(str(tmp_path))).execute({"operation":"list","path":"."}); assert result["status"]=="ok"
@pytest.mark.asyncio
async def test_filesystem_write_requires_permission(tmp_path):
    result=await FilesystemTool(PermissionGate(),WorkspacePolicy(str(tmp_path))).execute({"operation":"write","path":"hello.txt","content":"hello"}); assert result["status"]=="permission_required"
@pytest.mark.asyncio
async def test_terminal_requires_permission():
    result=await TerminalTool().execute({"command":"python --version"}); assert result["status"]=="permission_required"
