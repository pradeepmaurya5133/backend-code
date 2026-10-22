from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.tools.base import Tool

# Each operation maps to the single permission it needs.
OPERATION_PERMISSIONS = {
    "list": "filesystem.read",
    "stat": "filesystem.read",
    "read": "filesystem.read",
    "write": "filesystem.write",
    "delete": "filesystem.delete",
}


class FilesystemTool(Tool):
    name = "filesystem"
    description = (
        "Read, inspect, write or delete files inside the agent's sandboxed workspace. "
        "All paths are relative to the workspace root; paths outside it are refused. "
        "Write and delete require permissions that may not be granted."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["list", "stat", "read", "write", "delete"],
                "description": "The filesystem action to perform.",
            },
            "path": {
                "type": "string",
                "description": "Workspace-relative path, e.g. 'notes/todo.txt'. Use '.' for the root.",
            },
            "content": {
                "type": "string",
                "description": "Text to write. Required for the 'write' operation.",
            },
        },
        "required": ["operation", "path"],
    }
    permissions_required = set(OPERATION_PERMISSIONS.values())

    def __init__(self, permissions: PermissionGate = None, workspace: WorkspacePolicy = None):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.workspace = workspace if workspace is not None else WorkspacePolicy()

    def _relative(self, path):
        return str(path.relative_to(self.workspace.root)).replace("\\", "/")

    async def execute(self, arguments: dict) -> dict:
        operation = arguments.get("operation", "list")

        required = OPERATION_PERMISSIONS.get(operation)
        if not required:
            return {"tool": self.name, "status": "unsupported_operation", "operation": operation}
        if not self.permissions.allowed(required):
            return {"tool": self.name, "status": "permission_required", "permission": required}

        # Resolve only after the permission check, so a rejected call cannot probe paths.
        try:
            path = self.workspace.resolve(arguments.get("path", "."))
        except PermissionError as exc:
            return {"tool": self.name, "status": "outside_workspace", "detail": str(exc)}

        if operation == "stat":
            return {
                "tool": self.name,
                "status": "ok",
                "path": self._relative(path),
                "exists": path.exists(),
                "is_file": path.is_file(),
                "is_directory": path.is_dir(),
            }

        if operation == "list":
            if not path.is_dir():
                return {"tool": self.name, "status": "not_a_directory", "path": self._relative(path)}
            return {
                "tool": self.name,
                "status": "ok",
                "path": self._relative(path),
                "items": sorted(p.name for p in path.iterdir()),
            }

        if operation == "read":
            if not path.is_file():
                return {"tool": self.name, "status": "not_a_file", "path": self._relative(path)}
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                return {"tool": self.name, "status": "not_utf8_text", "path": self._relative(path)}
            return {"tool": self.name, "status": "ok", "path": self._relative(path), "content": content}

        if operation == "write":
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(arguments.get("content", ""), encoding="utf-8")
            return {"tool": self.name, "status": "ok", "path": self._relative(path)}

        if operation == "delete":
            if path == self.workspace.root:
                return {"tool": self.name, "status": "refused_workspace_root"}
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    # Recursive deletion is deliberately not offered by this tool.
                    return {"tool": self.name, "status": "directory_not_empty", "path": self._relative(path)}
            else:
                return {"tool": self.name, "status": "not_found", "path": self._relative(path)}
            return {"tool": self.name, "status": "ok", "path": self._relative(path)}
