from __future__ import annotations

from dataclasses import dataclass

from .electrical import electrical_nets
from .interfaces import component_interfaces
from .model import EngineeringGraph, EntityKind


@dataclass(frozen=True)
class InvariantFinding:
    code: str
    message: str
    entity_ids: tuple[str, ...] = ()


def check_engineering_invariants(graph: EngineeringGraph) -> tuple[InvariantFinding, ...]:
    """Production-compatible compiler gate used by tests and demo health checks."""
    findings: list[InvariantFinding] = []
    try:
        graph.validate()
    except ValueError as exc:
        findings.append(InvariantFinding("GRAPH_001", str(exc)))
        return tuple(findings)
    components = {item.id: item for item in graph.find(kind=EntityKind.COMPONENT)}
    interfaces: dict[str, set[str]] = {}
    for entity in components.values():
        dims = entity.metadata.get("dimensions", {})
        values = tuple(float(dims.get(key, {}).get("value", 0)) for key in ("width", "length", "height"))
        if any(value <= 0 for value in values):
            findings.append(InvariantFinding("MECH_001", "Physical dimensions must be positive millimetres.", (entity.id,)))
        family = entity.metadata.get("family", entity.metadata.get("role", ""))
        interfaces[entity.id] = {item.name for item in component_interfaces(family, tuple(max(value, 1) for value in values))}
    seen_nets: set[str] = set(); assigned: dict[tuple[str, str], str] = {}
    for net in electrical_nets(graph):
        if net["netId"] in seen_nets:
            findings.append(InvariantFinding("ELEC_001", "Electrical net IDs must be unique."))
        seen_nets.add(net["netId"])
        for terminal in net["terminals"]:
            key = (terminal["componentId"], terminal["interfaceId"])
            if key[0] not in components or key[1] not in interfaces.get(key[0], set()):
                findings.append(InvariantFinding("ELEC_207", "Net terminal does not resolve to a component electrical interface.", (key[0],)))
            if key in assigned and assigned[key] != net["netId"]:
                findings.append(InvariantFinding("ELEC_208", "Terminal belongs to conflicting nets.", (key[0],)))
            assigned[key] = net["netId"]
    for entity in components.values():
        family = entity.metadata.get("family", entity.metadata.get("role", ""))
        if family == "servo":
            for required in ("power", "ground", "signal"):
                if (entity.id, required) not in assigned:
                    findings.append(InvariantFinding("ELEC_301", f"Servo required terminal {required} is unconnected.", (entity.id,)))
    return tuple(findings)


def assert_engineering_invariants(graph: EngineeringGraph) -> None:
    findings = check_engineering_invariants(graph)
    if findings:
        raise AssertionError("\n".join(f"{item.code}: {item.message} ({', '.join(item.entity_ids)})" for item in findings))
