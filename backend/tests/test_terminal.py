import pytest

from app.security.audit import AuditLog
from app.security.confirmations import ConfirmationStore
from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.tools.terminal import TerminalTool


def build(tmp_path, granted=False):
    gate = PermissionGate()
    if granted:
        gate.grant("terminal.execute")
    store = ConfirmationStore()
    audit = AuditLog()
    tool = TerminalTool(gate, WorkspacePolicy(str(tmp_path)), store, audit)
    return tool, gate, store, audit


@pytest.mark.asyncio
async def test_gate_one_permission_blocks_before_anything_else(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=False)
    result = await tool.execute({"command": "python --version"})
    assert result["status"] == "permission_required"
    # No confirmation should be created for a call that never cleared permissions.
    assert store.pending() == []


@pytest.mark.asyncio
async def test_gate_two_allowlist_blocks_before_confirmation(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    result = await tool.execute({"command": "curl http://example.com"})
    assert result["status"] == "not_allowlisted"
    assert store.pending() == []


@pytest.mark.asyncio
async def test_gate_three_requires_confirmation_before_running(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    result = await tool.execute({"command": "python --version"})
    assert result["status"] == "confirmation_required"
    assert result["confirmation_token"]
    assert len(store.pending()) == 1
    # Nothing ran - no process output is present.
    assert "stdout" not in result


@pytest.mark.asyncio
async def test_approved_command_executes(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    first = await tool.execute({"command": "python --version"})
    token = first["confirmation_token"]
    store.approve(token)

    result = await tool.execute({"command": "python --version", "confirmation_token": token})
    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert "Python" in (result["stdout"] + result["stderr"])


@pytest.mark.asyncio
async def test_denied_command_does_not_execute(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    token = (await tool.execute({"command": "python --version"}))["confirmation_token"]
    store.deny(token)

    result = await tool.execute({"command": "python --version", "confirmation_token": token})
    assert result["status"] == "token_denied"
    assert "stdout" not in result


@pytest.mark.asyncio
async def test_token_cannot_be_reused_for_a_different_command(tmp_path):
    """The approval is bound to the exact command it was issued for."""
    tool, _, store, _ = build(tmp_path, granted=True)
    token = (await tool.execute({"command": "python --version"}))["confirmation_token"]
    store.approve(token)

    result = await tool.execute(
        {"command": "python -c \"print('something-else')\"", "confirmation_token": token}
    )
    assert result["status"] == "token_command_mismatch"
    assert "stdout" not in result

    # A mismatched attempt must not burn the approval - the command it was
    # actually issued for still has to work.
    allowed = await tool.execute({"command": "python --version", "confirmation_token": token})
    assert allowed["status"] == "completed"


@pytest.mark.asyncio
async def test_approval_is_single_use(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    token = (await tool.execute({"command": "python --version"}))["confirmation_token"]
    store.approve(token)

    assert (await tool.execute({"command": "python --version", "confirmation_token": token}))["status"] == "completed"
    replay = await tool.execute({"command": "python --version", "confirmation_token": token})
    assert replay["status"] == "token_consumed"


@pytest.mark.asyncio
async def test_revoking_permission_mid_session_stops_execution(tmp_path):
    tool, gate, store, _ = build(tmp_path, granted=True)
    token = (await tool.execute({"command": "python --version"}))["confirmation_token"]
    store.approve(token)
    gate.revoke("terminal.execute")

    result = await tool.execute({"command": "python --version", "confirmation_token": token})
    assert result["status"] == "permission_required"


@pytest.mark.asyncio
async def test_inspect_does_not_execute_or_need_confirmation(tmp_path):
    tool, _, store, _ = build(tmp_path, granted=True)
    result = await tool.execute({"operation": "inspect", "command": "python --version"})
    assert result["status"] == "ok"
    assert result["would_run"] is True
    assert store.pending() == []


@pytest.mark.asyncio
async def test_allowlist_is_readable_and_audit_records_attempts(tmp_path):
    tool, _, _, audit = build(tmp_path, granted=False)
    listed = await tool.execute({"operation": "allowlist"})
    assert listed["status"] == "ok"
    assert "python" in listed["allowlist"]

    await tool.execute({"command": "python --version"})
    assert len(audit) == 1
    assert audit.entries()[0]["status"] == "permission_required"
