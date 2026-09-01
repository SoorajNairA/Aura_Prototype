from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .model import EngineeringEntity, EngineeringGraph, EntityKind, Relationship, Revision
from .patches import GraphOperation, GraphPatch, PatchOperation


def graph_to_dict(graph: EngineeringGraph) -> dict[str, Any]:
    return {
        "schema_version": graph.schema_version,
        "project_id": graph.project_id,
        "entities": [asdict(graph.entities[key]) for key in sorted(graph.entities)],
        "relationships": [asdict(graph.relationships[key]) for key in sorted(graph.relationships)],
        "revisions": [asdict(revision) for revision in graph.revisions],
    }


def graph_from_dict(payload: dict[str, Any]) -> EngineeringGraph:
    entity_items=payload.get("entities", [])
    relationship_items=payload.get("relationships", [])
    entity_ids=[item.get("id") for item in entity_items]
    relationship_ids=[item.get("id") for item in relationship_items]
    if len(entity_ids)!=len(set(entity_ids)):
        raise ValueError("Serialized graph contains duplicate entity ids")
    if len(relationship_ids)!=len(set(relationship_ids)):
        raise ValueError("Serialized graph contains duplicate relationship ids")
    entities = {
        item["id"]: EngineeringEntity(
            id=item["id"], kind=EntityKind(item["kind"]), name=item["name"],
            parent_id=item.get("parent_id"), metadata=dict(item.get("metadata", {})),
            source_refs=tuple(item.get("source_refs", ())),
            verification_status=item.get("verification_status", "conceptual"),
            representation_refs=tuple(item.get("representation_refs", ())),
        )
        for item in entity_items
    }
    relationships = {
        item["id"]: Relationship(
            id=item["id"], source_id=item["source_id"], target_id=item["target_id"],
            type=item["type"], metadata=dict(item.get("metadata", {})),
        )
        for item in relationship_items
    }
    graph = EngineeringGraph(
        project_id=payload["project_id"], schema_version=payload.get("schema_version", "1.0"),
        entities=entities, relationships=relationships,
        revisions=[Revision(**item) for item in payload.get("revisions", [])],
    )
    graph.validate()
    return graph


def dumps(graph: EngineeringGraph, *, indent: int | None = 2) -> str:
    return json.dumps(graph_to_dict(graph), indent=indent, sort_keys=True)


def loads(value: str) -> EngineeringGraph:
    return graph_from_dict(json.loads(value))


def save(graph: EngineeringGraph, path: Path) -> None:
    path.write_text(dumps(graph) + "\n", encoding="utf-8")


def load(path: Path) -> EngineeringGraph:
    return loads(path.read_text(encoding="utf-8"))


def patch_to_dict(patch: GraphPatch) -> dict[str, Any]:
    operations = []
    for operation in patch.operations:
        operations.append({
            "operation": operation.operation.value,
            "entity": asdict(operation.entity) if operation.entity else None,
            "relationship": asdict(operation.relationship) if operation.relationship else None,
            "target_id": operation.target_id,
            "changes": operation.changes,
        })
    return {"id": patch.id, "summary": patch.summary,
            "base_revision_id": patch.base_revision_id, "operations": operations}


def patch_from_dict(payload: dict[str, Any]) -> GraphPatch:
    operations = []
    for item in payload["operations"]:
        entity_data = item.get("entity")
        relationship_data = item.get("relationship")
        entity = None
        if entity_data:
            entity = EngineeringEntity(
                id=entity_data["id"], kind=EntityKind(entity_data["kind"]), name=entity_data["name"],
                parent_id=entity_data.get("parent_id"), metadata=entity_data.get("metadata", {}),
                source_refs=tuple(entity_data.get("source_refs", ())),
                verification_status=entity_data.get("verification_status", "conceptual"),
                representation_refs=tuple(entity_data.get("representation_refs", ())))
        relationship = Relationship(**relationship_data) if relationship_data else None
        operations.append(GraphOperation(PatchOperation(item["operation"]), entity, relationship,
                                         item.get("target_id"), item.get("changes", {})))
    return GraphPatch(payload["id"], tuple(operations), payload["summary"], payload.get("base_revision_id"))
