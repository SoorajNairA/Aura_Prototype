from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from typing import Any

from .model import EngineeringEntity, EngineeringGraph, EntityKind

ELECTRICAL_TYPES = {"power", "ground", "control", "signal", "regulated-power", "switched-power"}
NET_STYLES = {"power": "#ef6f61", "ground": "#718096", "control": "#4fd1c5", "signal": "#63b3ed", "regulated-power": "#f6ad55", "switched-power": "#ed8936"}


def materialize_electrical_nets(graph: EngineeringGraph) -> EngineeringGraph:
    """Persist graph-owned nets from electrical connection entities.

    Shared terminals are unioned, so distribution rails become one net. This is
    deterministic and contains no project-name or complete-project knowledge.
    """
    existing = [e for e in graph.entities.values() if e.metadata.get("semantic_type") == "electrical_net"]
    for entity in existing:
        graph.entities.pop(entity.id, None)
    pairs: list[tuple[str, str, str, str]] = []
    for rel in graph.relationships.values():
        if rel.type not in ELECTRICAL_TYPES:
            continue
        connection = graph.entities.get(str(rel.metadata.get("connection_id", "")))
        source_port = str(connection.metadata.get("source_interface", rel.type) if connection else rel.type)
        target_port = str(connection.metadata.get("target_interface", rel.type) if connection else rel.type)
        pairs.append((f"{rel.source_id}:{source_port}", f"{rel.target_id}:{target_port}", rel.type, rel.id))
    parent: dict[str, str] = {}
    def find(value: str) -> str:
        parent.setdefault(value, value)
        if parent[value] != value:
            parent[value] = find(parent[value])
        return parent[value]
    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[max(a, b)] = min(a, b)
    for left, right, _, _ in pairs:
        union(left, right)
    groups: dict[str, list[tuple[str, str, str, str]]] = defaultdict(list)
    for pair in pairs:
        groups[find(pair[0])].append(pair)
    for _, members in sorted(groups.items()):
        terminals = sorted({terminal for left, right, _, _ in members for terminal in (left, right)})
        roles = [role for _, _, role, _ in members]
        role = "ground" if "ground" in roles else "power" if any("power" in item for item in roles) else roles[0]
        digest = sha256("|".join(terminals).encode()).hexdigest()[:12]
        net_id = f"net-{role}-{digest}"
        graph.entities[net_id] = EngineeringEntity(net_id, EntityKind.CONNECTION, net_id.upper().replace("-", "_"), graph.project_id, {
            "semantic_type": "electrical_net", "role": role,
            "terminals": [{"componentId": value.rsplit(":", 1)[0], "interfaceId": value.rsplit(":", 1)[1]} for value in terminals],
            "displayStyle": {"color": NET_STYLES.get(role, "#81e6d9")},
            "connectionIds": sorted(item[3] for item in members),
        })
    return graph


def electrical_nets(graph: EngineeringGraph) -> list[dict[str, Any]]:
    return [{"netId": entity.id, **entity.metadata} for entity in graph.find(kind=EntityKind.CONNECTION)
            if entity.metadata.get("semantic_type") == "electrical_net"]
