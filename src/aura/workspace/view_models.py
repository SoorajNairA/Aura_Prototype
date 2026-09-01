from __future__ import annotations

from dataclasses import dataclass, field

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from .events import WorkspaceEvent


@dataclass
class WorkspaceProjection:
    project_id: str
    stage: str = "idle"
    selected_id: str | None = None
    hover_id: str | None = None
    focus_ids: set[str] = field(default_factory=set)
    focus_explanation: str = ""
    critical_ids: set[str] = field(default_factory=set)
    revision_id: str | None = None
    progress_events: list[str] = field(default_factory=list)

    @classmethod
    def from_graph(cls, graph: EngineeringGraph) -> "WorkspaceProjection":
        critical: set[str] = set()
        for result in graph.find(kind=EntityKind.VERIFICATION_RESULT):
            if result.metadata.get("severity") == "critical":
                critical.update(result.metadata.get("entity_ids", []))
        return cls(graph.project_id, "ready", critical_ids=critical, revision_id=graph.current_revision_id)

    def select(self, graph: EngineeringGraph, entity_id: str) -> None:
        graph.get(entity_id)
        self.selected_id = entity_id

    def hover(self, graph: EngineeringGraph, entity_id: str | None) -> None:
        if entity_id is not None:
            graph.get(entity_id)
        self.hover_id = entity_id

    def focus(self, graph: EngineeringGraph, entity_ids: set[str], explanation: str) -> None:
        for entity_id in entity_ids:
            graph.get(entity_id)
        self.focus_ids = set(entity_ids)
        self.focus_explanation = explanation

    def highlight(self, entity_id: str) -> str:
        if entity_id in self.critical_ids: return "critical"
        if entity_id == self.selected_id: return "selected"
        if entity_id in self.focus_ids: return "aura-focus"
        if entity_id == self.hover_id: return "hover"
        return "normal"

    def apply_event(self, event: WorkspaceEvent) -> None:
        if event.project_id != self.project_id:
            return
        self.progress_events.append(event.type)
        self.stage = event.type
        if event.type == "selection.changed":
            self.selected_id = event.entity_id
        elif event.type == "focus.requested":
            self.focus_ids = set(event.payload.get("entity_ids", []))
            self.focus_explanation = event.payload.get("explanation", "")
        elif event.type == "revision.committed":
            self.revision_id = event.revision_id

    def hierarchy(self, graph: EngineeringGraph) -> list[dict]:
        def node(entity_id: str) -> dict:
            entity = graph.get(entity_id)
            return {"id": entity.id, "name": entity.name, "kind": entity.kind.value,
                    "children": [node(child.id) for child in graph.children(entity.id)]}
        return [node(graph.project_id)]

    def verification_summary(self, graph: EngineeringGraph) -> list[dict]:
        return [{"id": item.id, "message": item.name, "state": item.verification_status,
                 "severity": item.metadata.get("severity", "info"),
                 "entity_ids": item.metadata.get("entity_ids", [])}
                for item in graph.find(kind=EntityKind.VERIFICATION_RESULT)]
