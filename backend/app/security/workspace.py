from pathlib import Path
class WorkspacePolicy:
    def __init__(self, root: str = "./workspace"):
        self.root=Path(root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
    def resolve(self, relative_path: str = ".") -> Path:
        candidate=(self.root/relative_path).resolve()
        try: candidate.relative_to(self.root)
        except ValueError as exc: raise PermissionError("Path is outside the AI workspace.") from exc
        return candidate
