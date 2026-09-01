from __future__ import annotations

from pathlib import Path
from typing import Protocol

from aura.engineering_graph.model import EngineeringGraph
from aura.engineering_graph.serialization import load, save


class GraphRepository(Protocol):
    def load(self, project_id: str) -> EngineeringGraph | None: ...
    def save(self, graph: EngineeringGraph) -> None: ...


class JsonGraphRepository:
    """Atomic-file-friendly project graph repository with authorized root scope."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, project_id: str) -> Path:
        if not project_id or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for char in project_id):
            raise ValueError("Project id is not safe for persistence")
        return self.root / f"{project_id}.json"

    def load(self, project_id: str) -> EngineeringGraph | None:
        path = self._path(project_id)
        return load(path) if path.exists() else None

    def save(self, graph: EngineeringGraph) -> None:
        path = self._path(graph.project_id)
        temporary = path.with_suffix(".json.tmp")
        save(graph, temporary)
        temporary.replace(path)
