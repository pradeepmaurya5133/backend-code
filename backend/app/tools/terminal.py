from app.security.audit import AuditLog
from app.security.confirmations import ConfirmationStore
from app.security.permissions import PermissionGate
from app.security.sandbox import CommandSandbox
from app.security.workspace import WorkspacePolicy
from app.tools.base import Tool


class TerminalTool(Tool):
    """Permission-gated, allowlisted, confirmation-required command execution.

    A call must clear three independent checks before anything runs:
      1. the 'terminal.execute' permission is granted
      2. the command passes the sandbox allowlist
      3. a human has approved the confirmation token for that exact command
    """

    name = "terminal"
    description = (
        "Run a shell command in a sandbox. Only allowlisted executables are permitted "
        "(python, pip, node, npm, git, pytest, echo and similar) and shell syntax such as "
        "pipes, redirects and command chaining is refused. Execution additionally requires "
        "human approval: the first call returns a confirmation token and runs nothing. "
        "Use operation 'allowlist' to see what is runnable, or 'inspect' to validate a "
        "command without requesting approval."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["execute", "inspect", "allowlist"],
                "description": "'execute' requests a run, 'inspect' validates only, 'allowlist' lists allowed programs.",
            },
            "command": {
                "type": "string",
                "description": "The command line to run, e.g. 'python --version'. Required for execute/inspect.",
            },
            "timeout": {
                "type": "integer",
                "description": "Optional wall-clock limit in seconds (default 15, maximum 120).",
            },
        },
        "required": ["operation"],
    }
    permissions_required = {"terminal.read", "terminal.execute"}

    def __init__(
        self,
        permissions: PermissionGate = None,
        workspace: WorkspacePolicy = None,
        confirmations: ConfirmationStore = None,
        audit: AuditLog = None,
        sandbox: CommandSandbox = None,
    ):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.workspace = workspace if workspace is not None else WorkspacePolicy()
        self.confirmations = confirmations if confirmations is not None else ConfirmationStore()
        self.audit = audit if audit is not None else AuditLog()
        self.sandbox = sandbox if sandbox is not None else CommandSandbox(self.workspace)

    def _log(self, status: str, command: str, detail: dict = None):
        self.audit.record("agent", f"terminal.execute:{command}", status, detail)

    async def execute(self, arguments: dict) -> dict:
        operation = arguments.get("operation", "execute")

        if operation == "allowlist":
            if not self.permissions.allowed("terminal.read"):
                return {"tool": self.name, "status": "permission_required", "permission": "terminal.read"}
            return {"tool": self.name, "status": "ok", "allowlist": sorted(self.sandbox.allowlist)}

        if operation not in ("execute", "inspect"):
            return {"tool": self.name, "status": "unsupported_operation", "operation": operation}

        command = (arguments.get("command") or "").strip()
        if not command:
            return {"tool": self.name, "status": "missing_command"}

        # 1. Permission.
        if not self.permissions.allowed("terminal.execute"):
            self._log("permission_required", command)
            return {
                "tool": self.name,
                "status": "permission_required",
                "permission": "terminal.execute",
                "command": command,
            }

        # 2. Allowlist / shape validation.
        check = self.sandbox.inspect(command)
        if check["status"] != "ok":
            self._log(check["status"], command, {"detail": check.get("detail")})
            return {"tool": self.name, "command": command, **check}

        if operation == "inspect":
            return {"tool": self.name, "status": "ok", "command": command, "program": check["program"], "would_run": True}

        # 3. Human confirmation, bound to this exact command.
        token = arguments.get("confirmation_token")
        if not token:
            record = self.confirmations.request(self.name, "execute", {"command": command})
            self._log("awaiting_confirmation", command, {"token": record.token})
            return {
                "tool": self.name,
                "status": "confirmation_required",
                "command": command,
                "program": check["program"],
                "confirmation_token": record.token,
                "expires_at": record.expires_at.isoformat(),
                "hint": "Approve via POST /api/confirmations/approve, then resend with confirmation_token.",
            }

        # The approval is bound to its exact command; claim() verifies that
        # before consuming, so a mismatch leaves the approval usable.
        record, error = self.confirmations.claim(token, {"command": command})
        if error:
            status = "token_command_mismatch" if error["status"] == "token_argument_mismatch" else error["status"]
            self._log(status, command, {"token": token})
            return {"tool": self.name, "command": command, **error, "status": status}

        result = self.sandbox.run(command, arguments.get("timeout"))
        self._log(result["status"], command, {"exit_code": result.get("exit_code")})
        return {"tool": self.name, "command": command, **result}
