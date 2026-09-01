from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from aura.engineering_graph.model import EntityKind
from aura.engineering_graph.patches import GraphPatch


@dataclass(frozen=True)
class ProjectRequest:
    project_name: str
    objective: str
    requirements: tuple[str, ...]
    components: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    representation: str = "system_diagram"

    def validate(self) -> None:
        if not self.project_name.strip() or not self.objective.strip():
            raise ValueError("Project name and objective are required")
        if not self.requirements:
            raise ValueError("At least one requirement is required")
        if any(not value.strip() for value in (*self.requirements, *self.components, *self.assumptions)):
            raise ValueError("Request values must not be blank")


@dataclass(frozen=True)
class PlannedEntity:
    id: str
    kind: EntityKind
    name: str
    parent_id: str | None = None
    metadata: tuple[tuple[str, Any], ...] = ()


@dataclass(frozen=True)
class PlannedRelationship:
    id: str
    source_id: str
    target_id: str
    type: str


@dataclass(frozen=True)
class RepresentationRequest:
    entity_id: str
    representation_type: str


@dataclass(frozen=True)
class VerificationRequest:
    patch_id: str
    checks: tuple[str, ...]


@dataclass(frozen=True)
class WorkspaceEventProposal:
    event_type: str
    entity_id: str


@dataclass(frozen=True)
class SubsystemSpec:
    id: str
    name: str
    role: str
    description: str


@dataclass(frozen=True)
class ComponentSpec:
    id: str
    name: str
    role: str
    subsystem_id: str
    description: str
    parameters: dict[str, Any]
    interfaces: tuple[str, ...]
    dimensions: dict[str, dict[str, Any]]
    representation_status: str = "placeholder"
    evidence_refs: tuple[str, ...] = ()
    assumption_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ConnectionSpec:
    id: str
    source_id: str
    target_id: str
    source_interface: str
    target_interface: str
    connection_type: str
    description: str


@dataclass(frozen=True)
class ProjectPlan:
    request: ProjectRequest
    entities: tuple[PlannedEntity, ...]
    relationships: tuple[PlannedRelationship, ...]
    patch: GraphPatch
    representation_requests: tuple[RepresentationRequest, ...]
    verification_request: VerificationRequest
    workspace_events: tuple[WorkspaceEventProposal, ...]
    subsystems: tuple[SubsystemSpec, ...] = ()
    components: tuple[ComponentSpec, ...] = ()
    connections: tuple[ConnectionSpec, ...] = ()
    constraints: tuple[str, ...] = ()

    def validate(self) -> None:
        self.request.validate()
        ids = [entity.id for entity in self.entities]
        if len(ids) != len(set(ids)):
            raise ValueError("Planner output contains duplicate entity ids")
        known = set(ids)
        for entity in self.entities:
            if entity.parent_id is not None and entity.parent_id not in known:
                raise ValueError(f"Planner output references missing parent {entity.parent_id}")
        parents = {entity.id: entity.parent_id for entity in self.entities}
        for entity_id in parents:
            seen: set[str] = set()
            current = entity_id
            while current is not None:
                if current in seen:
                    raise ValueError(f"Planner hierarchy contains a parent cycle at {current}")
                seen.add(current)
                current = parents.get(current)
        for relationship in self.relationships:
            if relationship.source_id not in known or relationship.target_id not in known:
                raise ValueError(f"Planner relationship {relationship.id} has a missing endpoint")
        relationship_ids=[relationship.id for relationship in self.relationships]
        if len(relationship_ids)!=len(set(relationship_ids)):
            raise ValueError("Planner output contains duplicate relationship ids")
        if self.verification_request.patch_id != self.patch.id:
            raise ValueError("Verification request must reference the proposed patch")
        subsystem_ids = {item.id for item in self.subsystems}
        component_ids = {item.id for item in self.components}
        if len(subsystem_ids) != len(self.subsystems) or len(component_ids) != len(self.components):
            raise ValueError("Planner output contains duplicate semantic IDs")
        for component in self.components:
            if component.subsystem_id not in subsystem_ids:
                raise ValueError(f"Component {component.id} references missing subsystem {component.subsystem_id}")
        for connection in self.connections:
            if connection.source_id not in component_ids or connection.target_id not in component_ids:
                raise ValueError(f"Connection {connection.id} references a missing component")
        connection_ids=[connection.id for connection in self.connections]
        if len(connection_ids)!=len(set(connection_ids)):
            raise ValueError("Planner output contains duplicate connection ids")
