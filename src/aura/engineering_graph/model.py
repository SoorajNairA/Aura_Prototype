from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Iterable


class EntityKind(str, Enum):
    PROJECT = "project"
    ASSEMBLY = "assembly"
    SUBSYSTEM = "subsystem"
    COMPONENT = "component"
    CONNECTION = "connection"
    REQUIREMENT = "requirement"
    CONSTRAINT = "constraint"
    ASSUMPTION = "assumption"
    DECISION = "decision"
    ARTIFACT = "artifact"
    EVIDENCE = "evidence"
    VERIFICATION_RESULT = "verification_result"
    REPRESENTATION = "representation"


@dataclass(frozen=True)
class EngineeringEntity:
    id: str
    kind: EntityKind
    name: str
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    source_refs: tuple[str, ...] = ()
    verification_status: str = "conceptual"
    representation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("Entity id must not be empty")
        if not self.name.strip():
            raise ValueError("Entity name must not be empty")


@dataclass(frozen=True)
class Relationship:
    id: str
    source_id: str
    target_id: str
    type: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all((self.id.strip(), self.source_id.strip(), self.target_id.strip(), self.type.strip())):
            raise ValueError("Relationship id, endpoints, and type are required")


@dataclass(frozen=True)
class Revision:
    id: str
    parent_id: str | None
    patch_id: str
    summary: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class EngineeringGraph:
    project_id: str
    schema_version: str = "1.0"
    entities: dict[str, EngineeringEntity] = field(default_factory=dict)
    relationships: dict[str, Relationship] = field(default_factory=dict)
    revisions: list[Revision] = field(default_factory=list)

    @property
    def current_revision_id(self) -> str | None:
        return self.revisions[-1].id if self.revisions else None

    def get(self, entity_id: str) -> EngineeringEntity:
        try:
            return self.entities[entity_id]
        except KeyError as exc:
            raise KeyError(f"Unknown engineering entity: {entity_id}") from exc

    def find(self, *, kind: EntityKind | None = None, parent_id: str | None = None) -> list[EngineeringEntity]:
        values: Iterable[EngineeringEntity] = self.entities.values()
        if kind is not None:
            values = (entity for entity in values if entity.kind == kind)
        if parent_id is not None:
            values = (entity for entity in values if entity.parent_id == parent_id)
        return sorted(values, key=lambda entity: entity.id)

    def children(self, entity_id: str) -> list[EngineeringEntity]:
        self.get(entity_id)
        return self.find(parent_id=entity_id)

    def validate(self) -> None:
        if self.schema_version != "1.0":
            raise ValueError(f"Unsupported Engineering Graph schema version: {self.schema_version}")
        if self.project_id not in self.entities:
            raise ValueError("Graph project_id must reference a project entity")
        if self.entities[self.project_id].kind != EntityKind.PROJECT:
            raise ValueError("Graph project_id must reference EntityKind.PROJECT")
        for entity in self.entities.values():
            if entity.parent_id is not None and entity.parent_id not in self.entities:
                raise ValueError(f"Entity {entity.id} has missing parent {entity.parent_id}")
            if not _finite_values(entity.metadata):
                raise ValueError(f"Entity {entity.id} metadata contains NaN or Infinity")
            dimensions=entity.metadata.get("dimensions")
            if dimensions is not None:
                if not isinstance(dimensions,dict) or not dimensions:
                    raise ValueError(f"Entity {entity.id} dimensions must be a non-empty mapping")
                scale={"mm":1.0,"cm":10.0,"m":1000.0,"in":25.4,"inch":25.4,"inches":25.4}
                for dimension in dimensions.values():
                    if not isinstance(dimension,dict) or dimension.get("unit") not in scale:
                        raise ValueError(f"Entity {entity.id} has unsupported dimension units")
                    millimetres=float(dimension.get("value",0))*scale[dimension["unit"]]
                    if not math.isfinite(millimetres) or not 0<millimetres<=10_000:
                        raise ValueError(f"Entity {entity.id} dimensions must be finite, positive, and at most 10000 mm")
        parents={entity.id:entity.parent_id for entity in self.entities.values()}
        for entity_id in parents:
            seen:set[str]=set();current: str | None=entity_id
            while current is not None:
                if current in seen:
                    raise ValueError(f"Graph hierarchy contains a parent cycle at {current}")
                seen.add(current);current=parents.get(current)
        for relationship in self.relationships.values():
            if relationship.source_id not in self.entities or relationship.target_id not in self.entities:
                raise ValueError(f"Relationship {relationship.id} has a missing endpoint")
            if not _finite_values(relationship.metadata):
                raise ValueError(f"Relationship {relationship.id} metadata contains NaN or Infinity")


def _finite_values(value: Any) -> bool:
    if isinstance(value,float): return math.isfinite(value)
    if isinstance(value,dict): return all(_finite_values(item) for item in value.values())
    if isinstance(value,(list,tuple)): return all(_finite_values(item) for item in value)
    return True
