from __future__ import annotations

from pathlib import Path

from app.config import WORKSPACE_PATH


class ToolManager:
    def __init__(self, workspace: Path = WORKSPACE_PATH) -> None:
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, filename: str) -> Path:
        candidate = (self.workspace / filename).resolve()
        if candidate != self.workspace and self.workspace not in candidate.parents:
            raise ValueError("File operation is restricted to the workspace directory.")
        return candidate

    def read_file(self, filename: str) -> str:
        path = self._safe_path(filename)
        if not path.is_file():
            raise FileNotFoundError(f"Workspace file not found: {filename}")
        return path.read_text(encoding="utf-8")

    def write_file(self, filename: str, content: str) -> str:
        path = self._safe_path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return str(path.relative_to(self.workspace))

    def create_folder(self, foldername: str) -> str:
        path = self._safe_path(foldername)
        path.mkdir(parents=True, exist_ok=True)
        return str(path.relative_to(self.workspace))

    def search(self, query: str) -> list[str]:
        if not query.strip():
            return []
        matches: list[str] = []
        for path in self.workspace.rglob("*"):
            if path.is_file() and query.lower() in path.read_text(encoding="utf-8", errors="ignore").lower():
                matches.append(str(path.relative_to(self.workspace)))
        return matches[:20]

    def list_files(self, folder: str | None = None) -> list[dict[str, str | int]]:
        root = self._safe_path(folder) if folder else self.workspace
        if not root.exists():
            raise FileNotFoundError(f"Workspace folder not found: {folder}")
        if not root.is_dir():
            raise ValueError(f"Workspace path is not a folder: {folder}")
        files: list[dict[str, str | int]] = []
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.name != ".gitkeep":
                files.append({
                    "path": str(path.relative_to(self.workspace)).replace("\\", "/"),
                    "size": path.stat().st_size,
                })
        return files
