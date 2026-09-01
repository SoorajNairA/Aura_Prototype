from __future__ import annotations

from collections.abc import Callable

from aura.engineering_graph.model import EngineeringGraph
from aura.engineering_graph.model import EntityKind
from aura.engineering_graph.patches import apply_patch
from aura.engineering_graph.electrical import materialize_electrical_nets
from aura.verification.results import VerificationResult

from .events import WorkspaceEvent


class WorkspaceBridge:
    """Commit verified graph changes and publish frontend-neutral events."""

    def __init__(self) -> None:
        self._listeners: list[Callable[[WorkspaceEvent], None]] = []
        self._events: list[WorkspaceEvent] = []

    @property
    def events(self) -> tuple[WorkspaceEvent, ...]:
        return tuple(self._events)

    def subscribe(self, listener: Callable[[WorkspaceEvent], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def emit(self, event: WorkspaceEvent) -> None:
        self._events.append(event)
        for listener in tuple(self._listeners):
            listener(event)

    def commit(self, graph: EngineeringGraph, result: VerificationResult) -> EngineeringGraph:
        if not result.accepted or result.patch is None:
            self.emit(WorkspaceEvent(
                "verification.failed", graph.project_id,
                payload={"reasons": list(result.reasons), "state": result.state.value},
            ))
            return graph
        if not graph.revisions:
            self.emit(WorkspaceEvent("project.started", graph.project_id))
        updated = materialize_electrical_nets(apply_patch(graph, result.patch))
        kind_events = {
            EntityKind.REQUIREMENT: "requirements.created",
            EntityKind.ASSUMPTION: "assumptions.created",
            EntityKind.SUBSYSTEM: "subsystem.added",
            EntityKind.COMPONENT: "component.added",
            EntityKind.CONNECTION: "connection.added",
        }
        for operation in result.patch.operations:
            entity = operation.entity
            if entity and entity.kind in kind_events:
                self.emit(WorkspaceEvent(kind_events[entity.kind], updated.project_id,
                    revision_id=updated.current_revision_id, entity_id=entity.id))
            elif operation.target_id and operation.target_id in updated.entities:
                changed = updated.get(operation.target_id)
                if changed.kind == EntityKind.COMPONENT:
                    self.emit(WorkspaceEvent("component.updated", updated.project_id,
                        revision_id=updated.current_revision_id, entity_id=changed.id))
            elif operation.target_id and operation.target_id in updated.relationships:
                relationship = updated.relationships[operation.target_id]
                self.emit(WorkspaceEvent("connection.updated", updated.project_id,
                    revision_id=updated.current_revision_id, entity_id=relationship.id,
                    payload={"source_id": relationship.source_id, "target_id": relationship.target_id}))
        self.emit(WorkspaceEvent("verification.started", graph.project_id))
        for finding in result.findings:
            if finding.severity in {"warning", "critical"}:
                self.emit(WorkspaceEvent("warning.created", updated.project_id,
                    revision_id=updated.current_revision_id, entity_id=finding.entity_ids[0] if finding.entity_ids else None,
                    payload={"finding_id": finding.id, "message": finding.message}))
        self.emit(WorkspaceEvent("verification.completed", graph.project_id, payload={"state": result.state.value}))
        self.emit(WorkspaceEvent(
            "revision.committed", updated.project_id,
            revision_id=updated.current_revision_id,
            payload={"patch_id": result.patch.id, "summary": result.patch.summary},
        ))
        self.emit(WorkspaceEvent(
            "project.created", updated.project_id,
            revision_id=updated.current_revision_id, entity_id=updated.project_id,
        ))
        # This is graph readiness for bridge consumers. The server withholds it
        # until required representation compilation has completed.
        self.emit(WorkspaceEvent("project.ready", updated.project_id, revision_id=updated.current_revision_id))
        return updated

    def selection_changed(self, project_id: str, entity_id: str) -> None:
        self.emit(WorkspaceEvent("selection.changed", project_id, entity_id=entity_id))

    def focus_requested(self, project_id: str, entity_ids: list[str], explanation: str) -> None:
        self.emit(WorkspaceEvent("focus.requested", project_id,
            entity_id=entity_ids[0] if entity_ids else None,
            payload={"entity_ids": entity_ids, "explanation": explanation}))
