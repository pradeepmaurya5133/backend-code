from app.security.audit import AuditLog
from app.security.confirmations import ConfirmationStore
from app.security.permissions import PermissionGate
from app.security.workspace import WorkspacePolicy
from app.tools.base import Tool
from app.tools.filesystem import FilesystemTool
from app.tools.http_api import HttpApiTool
from app.tools.memory import MemoryTool
from app.tools.terminal import TerminalTool
from app.tools.web import WebTool


class ToolRegistry:
    """Owns the tool instances and the gate/workspace/audit they all share."""

    def __init__(
        self,
        permissions: PermissionGate = None,
        workspace: WorkspacePolicy = None,
        confirmations: ConfirmationStore = None,
        audit: AuditLog = None,
        memory_repository=None,
        secrets=None,
        allowed_api_hosts: set[str] = None,
        web_timeout: int = 15,
        web_max_bytes: int = 400_000,
        search_provider=None,
    ):
        self.permissions = permissions if permissions is not None else PermissionGate()
        self.workspace = workspace if workspace is not None else WorkspacePolicy()
        self.confirmations = confirmations if confirmations is not None else ConfirmationStore()
        self.audit = audit if audit is not None else AuditLog()
        self._tools: dict[str, Tool] = {}

        self.register(FilesystemTool(self.permissions, self.workspace))
        self.register(TerminalTool(self.permissions, self.workspace, self.confirmations, self.audit))
        self.register(
            WebTool(
                self.permissions,
                timeout=web_timeout,
                max_bytes=web_max_bytes,
                search_provider=search_provider,
            )
        )
        self.register(
            HttpApiTool(
                self.permissions,
                allowed_hosts=allowed_api_hosts,
                secrets=secrets,
                timeout=web_timeout,
            )
        )
        self.register(MemoryTool(self.permissions, memory_repository))

    def register(self, tool: Tool):
        self._tools[tool.name] = tool

    def get(self, name: str):
        return self._tools.get(name)

    def names(self):
        return list(self._tools)

    def bind_session(self, session_id: str):
        """Point session-scoped tools (memory) at the active conversation."""
        memory = self._tools.get("memory")
        if memory is not None:
            memory.session_id = session_id

    def describe(self):
        return [
            {
                "name": name,
                "description": tool.description,
                "permissions": sorted(tool.permissions_required),
            }
            for name, tool in sorted(self._tools.items())
        ]

    def definitions(self) -> list[dict]:
        """Tool definitions for the Messages API, in a stable order.

        Order is deterministic so the cached prompt prefix stays byte-identical
        between requests.
        """
        return [self._tools[name].definition() for name in sorted(self._tools)]

    def permissions_catalog(self) -> set[str]:
        """Every permission any registered tool can ask for."""
        catalog = set()
        for tool in self._tools.values():
            catalog |= set(tool.permissions_required)
        return catalog
