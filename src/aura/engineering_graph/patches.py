from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any
from uuid import uuid4

from .model import EngineeringEntity, EngineeringGraph, Relationship, Revision


class PatchOperation(str, Enum):
    ADD_ENTITY = "add_entity"
    UPDATE_ENTITY = "update_entity"
    REMOVE_ENTITY = "remove_entity"
    ADD_RELATIONSHIP = "add_relationship"
    UPDATE_RELATIONSHIP = "update_relationship"
    REMOVE_RELATIONSHIP = "remove_relationship"


@dataclass(frozen=True)
class GraphOperation:
    operation: PatchOperation
    entity: EngineeringEntity | None = None
    relationship: Relationship | None = None
    target_id: str | None = None
    changes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GraphPatch:
    id: str
    operations: tuple[GraphOperation, ...]
    summary: str
    base_revision_id: str | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.operations:
            raise ValueError("A graph patch requires an id and at least one operation")


def apply_patch(graph: EngineeringGraph, patch: GraphPatch) -> EngineeringGraph:
    if patch.base_revision_id != graph.current_revision_id:
        raise ValueError("Patch base revision does not match graph revision")
    updated = deepcopy(graph)
    for operation in patch.operations:
        _apply_operation(updated, operation)
    updated.validate()
    updated.revisions.append(
        Revision(
            id=f"revision-{uuid4().hex}",
            parent_id=graph.current_revision_id,
            patch_id=patch.id,
            summary=patch.summary,
        )
    )
    return updated


def _apply_operation(graph: EngineeringGraph, change: GraphOperation) -> None:
    if change.operation == PatchOperation.ADD_ENTITY:
        if change.entity is None or change.entity.id in graph.entities:
            raise ValueError("add_entity requires a new entity")
        graph.entities[change.entity.id] = change.entity
    elif change.operation == PatchOperation.UPDATE_ENTITY:
        if change.target_id not in graph.entities:
            raise ValueError(f"Cannot update missing entity {change.target_id}")
        allowed = {"name", "parent_id", "metadata", "source_refs", "verification_status", "representation_refs"}
        if unknown := set(change.changes) - allowed:
            raise ValueError(f"Unsupported entity changes: {sorted(unknown)}")
        graph.entities[change.target_id] = replace(graph.entities[change.target_id], **change.changes)
    elif change.operation == PatchOperation.REMOVE_ENTITY:
        if change.target_id not in graph.entities:
            raise ValueError(f"Cannot remove missing entity {change.target_id}")
        if any(entity.parent_id == change.target_id for entity in graph.entities.values()):
            raise ValueError("Cannot remove an entity that still has children")
        if any(change.target_id in (rel.source_id, rel.target_id) for rel in graph.relationships.values()):
            raise ValueError("Cannot remove an entity that still has relationships")
        del graph.entities[change.target_id]
    elif change.operation == PatchOperation.ADD_RELATIONSHIP:
        if change.relationship is None or change.relationship.id in graph.relationships:
            raise ValueError("add_relationship requires a new relationship")
        graph.relationships[change.relationship.id] = change.relationship
    elif change.operation == PatchOperation.UPDATE_RELATIONSHIP:
        if change.target_id not in graph.relationships:
            raise ValueError(f"Cannot update missing relationship {change.target_id}")
        allowed = {"source_id", "target_id", "type", "metadata"}
        if unknown := set(change.changes) - allowed:
            raise ValueError(f"Unsupported relationship changes: {sorted(unknown)}")
        graph.relationships[change.target_id] = replace(graph.relationships[change.target_id], **change.changes)
    elif change.operation == PatchOperation.REMOVE_RELATIONSHIP:
        if change.target_id not in graph.relationships:
            raise ValueError(f"Cannot remove missing relationship {change.target_id}")
        del graph.relationships[change.target_id]
    else:
        raise ValueError(f"Unsupported patch operation: {change.operation}")
