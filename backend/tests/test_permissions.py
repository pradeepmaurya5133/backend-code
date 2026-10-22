from app.security.permissions import PermissionGate


def test_privileged_permissions_are_disabled_by_default():
    gate = PermissionGate()
    assert gate.allowed("terminal.execute") is False
    assert gate.allowed("filesystem.write") is False
    assert gate.allowed("filesystem.delete") is False


def test_read_permissions_are_enabled_by_default():
    gate = PermissionGate()
    assert gate.allowed("filesystem.read") is True


def test_unknown_permission_is_denied():
    gate = PermissionGate()
    assert gate.allowed("filesystem") is False
    assert gate.allowed("nonsense.permission") is False


def test_permission_can_be_granted_and_revoked():
    gate = PermissionGate()
    gate.grant("terminal.execute")
    assert gate.allowed("terminal.execute") is True
    gate.revoke("terminal.execute")
    assert gate.allowed("terminal.execute") is False
