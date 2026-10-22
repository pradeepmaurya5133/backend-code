from dataclasses import dataclass, field

# Anything that reaches outside the process, writes, or destroys starts OFF.
# Read-only, in-sandbox capabilities start ON so the agent is useful immediately.
DEFAULT_PERMISSIONS = {
    "filesystem.read": True,
    "filesystem.write": False,
    "filesystem.delete": False,
    "terminal.read": True,
    "terminal.execute": False,
    "web.search": True,
    "web.fetch": False,
    "api.call": False,
    "api.write": False,
    "memory.read": True,
    "memory.write": True,
}


@dataclass
class PermissionGate:
    permissions: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_PERMISSIONS))

    def allowed(self, permission: str) -> bool:
        # Unknown permissions are denied, so a typo fails closed.
        return self.permissions.get(permission, False)

    def grant(self, permission: str) -> None:
        self.permissions[permission] = True

    def revoke(self, permission: str) -> None:
        self.permissions[permission] = False

    def snapshot(self) -> dict[str, bool]:
        return dict(self.permissions)

    def reset(self) -> None:
        self.permissions = dict(DEFAULT_PERMISSIONS)
