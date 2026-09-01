from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, Protocol


class RepresentationType(str, Enum):
    PLACEHOLDER = "placeholder"
    MECHANICAL_3D = "mechanical_3d"
    CATALOG_3D = "catalog_3d"
    CIRCUIT_SCHEMATIC = "circuit_schematic"
    SYSTEM_DIAGRAM = "system_diagram"


class RepresentationStatus(str, Enum):
    REQUESTED = "requested"
    GENERATING = "generating"
    READY = "ready"
    FAILED = "failed"
    FALLBACK = "fallback"
    STALE = "stale"
    UNSUPPORTED = "unsupported"


_TRANSITIONS = {
    RepresentationStatus.REQUESTED: {RepresentationStatus.GENERATING, RepresentationStatus.FALLBACK, RepresentationStatus.UNSUPPORTED},
    RepresentationStatus.GENERATING: {RepresentationStatus.READY, RepresentationStatus.FAILED},
    RepresentationStatus.READY: {RepresentationStatus.STALE},
    RepresentationStatus.FAILED: {RepresentationStatus.FALLBACK, RepresentationStatus.GENERATING},
    RepresentationStatus.FALLBACK: {RepresentationStatus.GENERATING, RepresentationStatus.STALE},
    RepresentationStatus.STALE: {RepresentationStatus.GENERATING, RepresentationStatus.FALLBACK},
    RepresentationStatus.UNSUPPORTED: set(),
}


@dataclass(frozen=True)
class RepresentationRecord:
    representation_id: str
    project_id: str
    revision: int
    semantic_ids: tuple[str, ...]
    type: RepresentationType
    status: RepresentationStatus = RepresentationStatus.REQUESTED
    generator: str | None = None
    generator_version: str | None = None
    artifact_id: str | None = None
    fallback_type: RepresentationType = RepresentationType.PLACEHOLDER
    verification_status: str | None = None
    error: str | None = None
    operation_id: str | None = None
    generation: int = 1

    def transition(self, status: RepresentationStatus, **changes: Any) -> "RepresentationRecord":
        if status not in _TRANSITIONS[self.status]:
            raise ValueError(f"Invalid representation transition: {self.status.value} -> {status.value}")
        return replace(self, status=status, **changes)

    def to_dict(self) -> dict[str, Any]:
        return {"representationId": self.representation_id, "projectId": self.project_id,
                "revision": self.revision, "semanticIds": list(self.semantic_ids), "type": self.type.value,
                "status": self.status.value, "generator": self.generator,
                "generatorVersion": self.generator_version, "artifactId": self.artifact_id,
                "fallbackType": self.fallback_type.value, "verificationStatus": self.verification_status,
                "error": self.error, "operationId": self.operation_id, "generation": self.generation}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RepresentationRecord":
        return cls(value["representationId"], value["projectId"], int(value["revision"]),
                   tuple(value["semanticIds"]), RepresentationType(value["type"]),
                   RepresentationStatus(value["status"]), value.get("generator"),
                   value.get("generatorVersion"), value.get("artifactId"),
                   RepresentationType(value.get("fallbackType", "placeholder")),
                   value.get("verificationStatus"), value.get("error"),value.get("operationId"),int(value.get("generation",1)))


@dataclass(frozen=True)
class RepresentationSpec:
    kind: RepresentationType
    semantic_ids: tuple[str, ...]
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind.value, "semanticIds": list(self.semantic_ids), **self.payload}


class SpecValidationError(ValueError): pass


class RepresentationSpecValidator:
    MAX_DIMENSION_MM = 10_000.0
    MAX_SECTIONS = 16
    MAX_PATH_POINTS = 64
    MAX_COMPONENTS = 100
    OPERATIONS = {"loft", "pipe", "filleted_enclosure", "box", "cylinder", "sphere"}
    COMPONENT_KINDS = {"controller", "soil_sensor", "mosfet", "diode", "resistor", "motor", "servo", "power_source", "generic_sensor", "generic_actuator", "generic_module"}

    def validate(self, spec: RepresentationSpec, graph_ids: set[str]) -> RepresentationSpec:
        if not spec.semantic_ids or any(item not in graph_ids or not item.startswith("component-") for item in spec.semantic_ids):
            raise SpecValidationError("Representation semantic IDs must reference graph components")
        if self._contains_executable_field(spec.payload):
            raise SpecValidationError("Executable fields are forbidden")
        if spec.kind is RepresentationType.MECHANICAL_3D: self._mechanical(spec.payload)
        elif spec.kind is RepresentationType.CIRCUIT_SCHEMATIC: self._circuit(spec.payload, set(spec.semantic_ids))
        else: raise SpecValidationError(f"Unsupported generated representation type: {spec.kind.value}")
        return spec

    def _mechanical(self, payload: dict[str, Any]) -> None:
        if payload.get("units") != "mm": raise SpecValidationError("Mechanical units must be mm")
        expected = {"forward": "+X", "left": "+Y", "up": "+Z"}
        if payload.get("coordinateSystem") != expected: raise SpecValidationError("Unsupported coordinate system")
        geometry = payload.get("geometry")
        if not isinstance(geometry, dict) or geometry.get("operation") not in self.OPERATIONS:
            raise SpecValidationError("Unsupported or missing CAD operation")
        values = list(self._numbers(geometry))
        if not values or any(not math.isfinite(value) or abs(value) > self.MAX_DIMENSION_MM for value in values):
            raise SpecValidationError("CAD values must be finite and bounded")
        if geometry["operation"] in {"box", "cylinder", "sphere", "filleted_enclosure"} and not any(value > 0 for value in values):
            raise SpecValidationError("CAD geometry must have non-zero bounds")
        operation = geometry["operation"]
        if operation == "loft" and not 2 <= len(geometry.get("sections", [])) <= self.MAX_SECTIONS:
            raise SpecValidationError("Loft requires 2-16 sections")
        if operation == "pipe" and not 2 <= len(geometry.get("path", [])) <= self.MAX_PATH_POINTS:
            raise SpecValidationError("Pipe requires 2-64 path points")
        if operation == "filleted_enclosure" and not all(key in geometry for key in ("width", "depth", "height", "radius")):
            raise SpecValidationError("Filleted enclosure parameters are incomplete")

    def _circuit(self, payload: dict[str, Any], semantic_ids: set[str]) -> None:
        components = payload.get("components")
        connections = payload.get("connections")
        unconnected = payload.get("unconnected", [])
        topology = payload.get("netTopology", [])
        if not isinstance(components, list) or not 1 <= len(components) <= self.MAX_COMPONENTS:
            raise SpecValidationError("Circuit component count is invalid")
        if not isinstance(connections, list): raise SpecValidationError("Circuit connections are required")
        if not isinstance(unconnected, list) or not isinstance(topology, list):
            raise SpecValidationError("Circuit fidelity metadata is invalid")
        references: dict[str, set[str]] = {}
        for component in components:
            if component.get("kind") not in self.COMPONENT_KINDS or component.get("semanticId") not in semantic_ids:
                raise SpecValidationError("Unknown circuit component kind or semantic ID")
            reference = component.get("reference")
            pins = component.get("pins")
            if not isinstance(reference, str) or not isinstance(pins, list) or not pins: raise SpecValidationError("Circuit component reference/pins are invalid")
            references[reference] = set(pins)
        for connection in connections:
            for endpoint in (connection.get("from"), connection.get("to")):
                if not isinstance(endpoint, str) or "." not in endpoint: raise SpecValidationError("Connection endpoint is invalid")
                reference, pin = endpoint.split(".", 1)
                if pin not in references.get(reference, set()): raise SpecValidationError(f"Unknown pin reference: {endpoint}")
        for net in topology:
            expected=net.get("expectedTerminals",[]);represented=net.get("representedTerminals",[]);missing=net.get("missingTerminals",[])
            if not isinstance(expected,list) or not isinstance(represented,list) or not isinstance(missing,list):
                raise SpecValidationError("Circuit net topology is invalid")
            if set(missing) != set(expected)-set(represented):
                raise SpecValidationError("Circuit net fidelity does not reconcile its terminals")

    @staticmethod
    def _contains_executable_field(value: Any) -> bool:
        if isinstance(value, dict):
            return any(str(key).lower() in {"code", "script", "javascript", "executable", "command"} or RepresentationSpecValidator._contains_executable_field(item) for key, item in value.items())
        if isinstance(value, list): return any(RepresentationSpecValidator._contains_executable_field(item) for item in value)
        return False

    @staticmethod
    def _numbers(value: Any):
        if isinstance(value, (int, float)) and not isinstance(value, bool): yield float(value)
        elif isinstance(value, dict):
            for item in value.values(): yield from RepresentationSpecValidator._numbers(item)
        elif isinstance(value, list):
            for item in value: yield from RepresentationSpecValidator._numbers(item)


@dataclass(frozen=True)
class GenerationResult:
    status: RepresentationStatus
    artifact: bytes | None
    semantic_mapping: dict[str, str]
    warnings: tuple[str, ...]
    metrics: dict[str, float]
    format: str


class RepresentationGenerator(Protocol):
    generator_name: str
    generator_version: str
    def can_generate(self, spec: RepresentationSpec) -> bool: ...
    def generate(self, spec: RepresentationSpec) -> GenerationResult: ...


# Compatibility aliases for callers that used the original narrow names.
RepresentationRequest = RepresentationRecord
