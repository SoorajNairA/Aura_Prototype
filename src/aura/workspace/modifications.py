from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from aura.engineering_graph.interfaces import component_interfaces
from aura.engineering_graph.model import EngineeringEntity, EngineeringGraph, EntityKind, Relationship
from aura.engineering_graph.patches import GraphOperation, GraphPatch, PatchOperation, apply_patch
from aura.verification.catalogue import CATALOGUE, CATALOGUE_VERSION


class ModificationError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class ModificationDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["ATTACH_TO_INTERFACE", "SCALE_DIMENSIONS", "SET_PARAMETER", "REPLACE_COMPONENT", "UNSUPPORTED"]
    targetSemanticId: str
    summary: str = Field(min_length=1, max_length=240)
    rationale: str = Field(min_length=1, max_length=1200)
    referenceSemanticId: Optional[str]
    referenceInterface: Optional[str]
    targetInterface: Optional[str]
    scalePercent: Optional[float]
    preserveDimensions: list[Literal["width", "length", "height"]]
    parameterKey: Optional[str]
    parameterValueJson: Optional[str]
    componentDefinitionId: Optional[str]


class LiveModificationPlanner:
    """Converts natural language to a bounded graph edit and validates every model reference."""

    def __init__(self, provider: Any) -> None:
        self.provider, self.last_metadata = provider, {}

    def propose(self, graph: EngineeringGraph, base: int, ids: list[str], request: str, mode: str = "automatic") -> ModificationProposal:
        if base != len(graph.revisions):
            raise ModificationError("stale_revision", "The project changed. Reload it and try the edit again.", 409)
        if len(ids) != 1 or ids[0] not in graph.entities or graph.get(ids[0]).kind is not EntityKind.COMPONENT:
            raise ModificationError("unsupported_target", "Select one component before requesting an edit.")
        target = graph.get(ids[0])
        components = []
        for entity in graph.find(kind=EntityKind.COMPONENT):
            parameters = entity.metadata.get("parameters", {})
            interfaces = component_interfaces(_family(entity), _dimensions(entity), parameters)
            components.append({
                "id": entity.id, "name": entity.name, "family": _family(entity),
                "functionalRoles": parameters.get("functional_roles", []),
                "controlledAxisIds": parameters.get("controlled_axis_ids", []),
                "drivenAxisIds": parameters.get("driven_axis_ids", []),
                "dimensions": entity.metadata.get("dimensions", {}),
                "editableParameterKeys": sorted(key for key, value in parameters.items() if isinstance(value, (str, int, float, bool))),
                "physicalInterfaces": [{"name": item.name, "kind": item.kind, "compatibleWith": list(item.compatible)} for item in interfaces],
            })
        connections = {item.id: item for item in graph.find(kind=EntityKind.CONNECTION)}
        mechanical = []
        for relation in graph.relationships.values():
            if relation.type not in {"mechanical", "fixed", "revolute", "hinge"}:
                continue
            connection = connections.get(str(relation.metadata.get("connection_id", "")))
            mechanical.append({
                "relationshipId": relation.id, "sourceId": relation.source_id, "targetId": relation.target_id,
                "sourceInterface": connection.metadata.get("source_interface") if connection else None,
                "targetInterface": connection.metadata.get("target_interface") if connection else None,
            })
        replacements = [{"componentDefinitionId": item.component_definition_id, "manufacturer": item.manufacturer, "partNumber": item.part_number}
                        for item in CATALOGUE if item.family == _family(target)]
        context = {
            "request": request, "selectedSemanticId": target.id, "components": components,
            "existingMechanicalConnections": mechanical, "compatibleReplacementDefinitions": replacements,
            "allowedActions": {
                "ATTACH_TO_INTERFACE": "Mount/move the selected component using listed compatible interfaces on it and another listed component.",
                "SCALE_DIMENSIONS": "Scale selected dimensions by a percentage and optionally preserve named dimensions.",
                "SET_PARAMETER": "Set one listed scalar parameter; encode the primitive new value in parameterValueJson.",
                "REPLACE_COMPONENT": "Choose one compatible replacement definition.",
                "UNSUPPORTED": "Use when no other action represents the request safely.",
            },
        }
        instruction = (
            "Translate the user's engineering edit into exactly one bounded action. Reason from component roles, axis IDs, topology, "
            "and interface semantics; never use keyword substitution and never invent an ID, interface, parameter, dimension, or part. "
            "targetSemanticId must equal selectedSemanticId. For a joint or axis tip, choose the component whose drivenAxisIds identify "
            "that axis and its distal/end interface. ATTACH_TO_INTERFACE endpoints must be mutually compatible. Return UNSUPPORTED when "
            "the result is ambiguous or cannot be represented safely. Return only the response schema."
        )
        error = ""
        result = decision = None
        for attempt in range(2):
            payload = context if not error else {**context, "previousResponseError": error}
            result = self.provider.generate_structured(
                [{"role": "user", "content": json.dumps(payload, separators=(",", ":"), sort_keys=True)}],
                system_prompt=instruction, max_tokens=900, response_schema=ModificationDecision.model_json_schema())
            try:
                decision = ModificationDecision.model_validate_json(result.text)
                break
            except Exception as exc:
                error = f"Return a schema-valid decision: {exc}"
        if decision is None or result is None:
            raise ModificationError("model_modification_invalid", "The edit could not be converted into a valid engineering operation.", 502)
        if decision.targetSemanticId != target.id:
            raise ModificationError("model_modification_invalid", "The proposed edit did not preserve the selected component.", 502)
        if decision.action == "UNSUPPORTED":
            raise ModificationError("modification_not_actionable", decision.rationale)
        self.last_metadata = {
            "source": "structured_model", "repairAttempts": attempt, "firstPassValid": attempt == 0,
            "inputTokens": getattr(result, "input_tokens", None), "outputTokens": getattr(result, "output_tokens", None),
            "totalTokens": getattr(result, "total_tokens", None),
        }
        dispatch = {"ATTACH_TO_INTERFACE": _attach, "SCALE_DIMENSIONS": _scale,
                    "SET_PARAMETER": _set_parameter, "REPLACE_COMPONENT": _replace}
        return dispatch[decision.action](graph, base, target, decision, mode)


@dataclass(frozen=True)
class ModificationProposal:
    proposal_id: str
    base_revision: int
    target_ids: tuple[str, ...]
    summary: str
    mode: str
    operations: tuple[dict[str, Any], ...]
    affected_ids: tuple[str, ...]
    unaffected: tuple[str, ...]
    regenerate: tuple[str, ...]
    verification: dict[str, Any]
    patch: GraphPatch
    preview: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposalId": self.proposal_id, "baseRevision": self.base_revision,
            "targetSemanticIds": list(self.target_ids), "summary": self.summary, "mode": self.mode,
            "operations": list(self.operations), "affectedSemanticIds": list(self.affected_ids),
            "unaffectedAreas": list(self.unaffected), "artifactsToRegenerate": list(self.regenerate),
            "verification": self.verification, "preview": self.preview,
            "assumptions": ["Conceptual geometry requires physical validation"],
        }


def _proposal(graph: EngineeringGraph, base: int, target: EngineeringEntity, decision: ModificationDecision, mode: str,
              operations: list[dict[str, Any]], patch_operations: list[GraphOperation], affected: tuple[str, ...],
              regenerate: tuple[str, ...] = ()) -> ModificationProposal:
    patch = GraphPatch(f"patch-{uuid4().hex}", tuple(patch_operations), decision.summary, graph.current_revision_id)
    from .assembly import engineering_assembly
    candidate = engineering_assembly(apply_patch(graph, patch))
    part = next((item for item in candidate["parts"] if item["semanticId"] == target.id), None)
    preview = ({"semanticId": target.id, "position": part["assembledTransform"]["position"],
                "rotation": part["assembledTransform"].get("rotation", [0, 0, 0, 1]), "dimensions": part["dimensions"]}
               if part else None)
    verification = {"outcome": "pending_graph_verification", "checks": [{"state": "PASSED", "message": "Edit references validated against the current Engineering Graph"}]}
    return ModificationProposal(f"proposal-{uuid4().hex}", base, (target.id,), decision.summary, mode, tuple(operations), affected,
                                ("unrelated subsystems",), regenerate, verification, patch, preview)


def _attach(graph: EngineeringGraph, base: int, target: EngineeringEntity, decision: ModificationDecision, mode: str) -> ModificationProposal:
    reference_id = decision.referenceSemanticId
    if not reference_id or reference_id == target.id or reference_id not in graph.entities or graph.get(reference_id).kind is not EntityKind.COMPONENT:
        raise ModificationError("invalid_attachment_reference", "The placement did not resolve to another current component.")
    reference = graph.get(reference_id)
    reference_interfaces = {item.name: item for item in component_interfaces(_family(reference), _dimensions(reference), reference.metadata.get("parameters", {}))}
    target_interfaces = {item.name: item for item in component_interfaces(_family(target), _dimensions(target), target.metadata.get("parameters", {}))}
    source_interface = reference_interfaces.get(str(decision.referenceInterface or ""))
    target_interface = target_interfaces.get(str(decision.targetInterface or ""))
    if source_interface is None or target_interface is None or target_interface.kind not in source_interface.compatible:
        raise ModificationError("incompatible_attachment_interfaces", "The placement did not resolve to compatible physical interfaces.")
    existing = [relation for relation in graph.relationships.values()
                if relation.type in {"mechanical", "fixed", "revolute", "hinge"} and target.id in {relation.source_id, relation.target_id}]
    if len(existing) > 1:
        raise ModificationError("ambiguous_mechanical_attachment", "This component has multiple structural connections; specify which one should move.")
    occupied = set()
    replacing_ids = {relation.id for relation in existing}
    for relation in graph.relationships.values():
        if relation.id in replacing_ids or relation.type not in {"mechanical", "fixed", "revolute", "hinge"}:
            continue
        connection = graph.entities.get(str(relation.metadata.get("connection_id", "")))
        if connection and connection.kind is EntityKind.CONNECTION:
            occupied.add((relation.source_id, connection.metadata.get("source_interface")))
            occupied.add((relation.target_id, connection.metadata.get("target_interface")))
    if (reference.id, source_interface.name) in occupied:
        raise ModificationError("attachment_interface_in_use", "The selected mounting interface is already occupied by another component.")
    new_value = {"sourceId": reference.id, "targetId": target.id,
                 "sourceInterface": source_interface.name, "targetInterface": target_interface.name}
    if existing:
        relation = existing[0]
        connection_id = str(relation.metadata.get("connection_id", ""))
        connection = graph.entities.get(connection_id)
        if connection is None or connection.kind is not EntityKind.CONNECTION:
            raise ModificationError("mechanical_connection_incomplete", "The current mechanical connection has no editable graph record.")
        old_value = {"sourceId": relation.source_id, "targetId": relation.target_id,
                     "sourceInterface": connection.metadata.get("source_interface"),
                     "targetInterface": connection.metadata.get("target_interface")}
        metadata = dict(connection.metadata) | {
            "source_id": reference.id, "target_id": target.id, "source_interface": source_interface.name,
            "target_interface": target_interface.name, "connection_type": "mechanical"}
        patch_operations = [
            GraphOperation(PatchOperation.UPDATE_RELATIONSHIP, target_id=relation.id,
                           changes={"source_id": reference.id, "target_id": target.id, "type": "mechanical"}),
            GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=connection.id, changes={"metadata": metadata}),
        ]
        operations = [{"operation": "update_mechanical_attachment", "targetId": relation.id, "connectionId": connection.id,
                       "path": "mechanical attachment", "oldValue": old_value, "newValue": new_value}]
    else:
        suffix = uuid4().hex[:10]
        connection_id, relation_id = f"connection-user-mate-{suffix}", f"connection-user-mate-{suffix}-edge"
        metadata = {"source_id": reference.id, "target_id": target.id, "source_interface": source_interface.name,
                    "target_interface": target_interface.name, "connection_type": "mechanical"}
        connection = EngineeringEntity(connection_id, EntityKind.CONNECTION, f"Mount {target.name} to {reference.name}", graph.project_id, metadata)
        relation = Relationship(relation_id, reference.id, target.id, "mechanical", {"connection_id": connection_id})
        patch_operations = [GraphOperation(PatchOperation.ADD_ENTITY, entity=connection), GraphOperation(PatchOperation.ADD_RELATIONSHIP, relationship=relation)]
        operations = [{"operation": "add_mechanical_attachment", "targetId": relation_id, "connectionId": connection_id,
                       "path": "mechanical attachment", "oldValue": None, "newValue": new_value}]
    regenerate = (f"repr-{target.id.removeprefix('component-')}-3d",)
    return _proposal(graph, base, target, decision, mode, operations, patch_operations, (target.id, reference.id), regenerate)


def _scale(graph: EngineeringGraph, base: int, target: EngineeringEntity, decision: ModificationDecision, mode: str) -> ModificationProposal:
    percent = decision.scalePercent
    if percent is None or not -80 <= percent <= 500 or abs(percent) < .01:
        raise ModificationError("invalid_dimension_scale", "Specify a dimension change between -80% and +500%.")
    dimensions = {key: dict(value) for key, value in target.metadata.get("dimensions", {}).items()}
    preserve, operations = set(decision.preserveDimensions), []
    for key in ("width", "length", "height"):
        if key in preserve or key not in dimensions:
            continue
        old = float(dimensions[key]["value"])
        new = round(old * (1 + percent / 100), 3)
        if new <= 0:
            raise ModificationError("invalid_dimension_scale", "The scale would produce a non-positive dimension.")
        dimensions[key]["value"] = new
        operations.append({"operation": "replace_parameter", "path": f"dimensions.{key}.value", "oldValue": old, "newValue": new})
    if not operations:
        raise ModificationError("modification_not_actionable", "The request preserved every available dimension.")
    metadata = dict(target.metadata) | {"dimensions": dimensions}
    patch = [GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=target.id, changes={"metadata": metadata})]
    return _proposal(graph, base, target, decision, mode, operations, patch, (target.id,),
                     (f"repr-{target.id.removeprefix('component-')}-3d",))


def _set_parameter(graph: EngineeringGraph, base: int, target: EngineeringEntity, decision: ModificationDecision, mode: str) -> ModificationProposal:
    parameters, key = dict(target.metadata.get("parameters", {})), str(decision.parameterKey or "")
    if not key or key not in parameters or not isinstance(parameters[key], (str, int, float, bool)):
        raise ModificationError("invalid_parameter_edit", "The edit did not resolve to an existing scalar engineering parameter.")
    try:
        value = json.loads(str(decision.parameterValueJson))
    except Exception as exc:
        raise ModificationError("invalid_parameter_edit", "The requested parameter value was invalid.") from exc
    if not isinstance(value, (str, int, float, bool)) or value == parameters[key]:
        raise ModificationError("invalid_parameter_edit", "The requested parameter value was unchanged or unsupported.")
    old, parameters[key] = parameters[key], value
    metadata = dict(target.metadata) | {"parameters": parameters}
    operation = {"operation": "replace_parameter", "path": f"parameters.{key}", "oldValue": old, "newValue": value}
    patch = [GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=target.id, changes={"metadata": metadata})]
    return _proposal(graph, base, target, decision, mode, [operation], patch, (target.id,))


def _replace(graph: EngineeringGraph, base: int, target: EngineeringEntity, decision: ModificationDecision, mode: str) -> ModificationProposal:
    definition = next((item for item in CATALOGUE if item.component_definition_id == decision.componentDefinitionId), None)
    if definition is None or definition.family != _family(target):
        raise ModificationError("incompatible_component_definition", "The replacement is not a compatible curated component definition.")
    metadata, old = dict(target.metadata), target.metadata.get("component_definition_id")
    metadata["component_definition_id"], metadata["component_definition_version"] = definition.component_definition_id, CATALOGUE_VERSION
    metadata["parameters"] = dict(metadata.get("parameters", {})) | {
        "component_definition_id": definition.component_definition_id, "component_definition_version": CATALOGUE_VERSION}
    dimensions = definition.properties.get("dimensions")
    if dimensions:
        metadata["dimensions"] = {key: {"value": value, "unit": dimensions.unit}
                                  for key, value in zip(("width", "length", "height"), dimensions.value)}
    operation = {"operation": "replace_component_definition", "path": "component_definition_id", "oldValue": old,
                 "newValue": definition.component_definition_id}
    patch = [GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=target.id, changes={"metadata": metadata})]
    return _proposal(graph, base, target, decision, mode, [operation], patch, (target.id,),
                     (f"repr-{target.id.removeprefix('component-')}-3d",))


def _family(entity: EngineeringEntity) -> str:
    return str(entity.metadata.get("family", entity.metadata.get("role", "")))


def _dimensions(entity: EngineeringEntity) -> tuple[float, float, float]:
    values = entity.metadata.get("dimensions", {})
    return tuple(float(values.get(key, {}).get("value", fallback)) for key, fallback in (("width", 45), ("length", 30), ("height", 18)))


# This legacy function is used only by deterministic tests and bounded verification repair.
# Interactive production edits always use LiveModificationPlanner above.
def propose(graph: EngineeringGraph, base: int, ids: list[str], request: str, mode: str = "automatic") -> ModificationProposal:
    if base != len(graph.revisions): raise ValueError("stale_revision")
    if len(ids) != 1 or ids[0] not in graph.entities: raise ValueError("unsupported_target")
    target = graph.get(ids[0]); meta = dict(target.metadata); lower = request.lower(); operations = []
    family = meta.get("family", meta.get("role", "")); regenerate = (); unaffected = ("unrelated subsystems",)
    exact = next((item for item in CATALOGUE if item.component_definition_id.lower() in lower), None)
    if exact:
        compatible_families = {exact.family}
        compatible_families.add({"microcontroller_board": "controller", "small_dc_pump": "water delivery",
                                 "soil_moisture_sensor": "soil sensing"}.get(exact.family, exact.family))
        if family not in compatible_families: raise ValueError("incompatible_component_definition")
        old = meta.get("component_definition_id"); meta["component_definition_id"] = exact.component_definition_id; meta["component_definition_version"] = CATALOGUE_VERSION
        params = dict(meta.get("parameters", {})); params.update(component_definition_id=exact.component_definition_id, component_definition_version=CATALOGUE_VERSION); meta["parameters"] = params
        dimensions = exact.properties.get("dimensions")
        if dimensions: meta["dimensions"] = {key: {"value": value, "unit": dimensions.unit} for key, value in zip(("width", "length", "height"), dimensions.value)}
        summary = f"Upgrade {target.name} to curated {exact.manufacturer} {exact.part_number}"; regenerate = (f"repr-{target.id.removeprefix('component-')}-3d",)
        operations = [{"operation": "replace_component_definition", "path": "component_definition_id", "oldValue": old, "newValue": exact.component_definition_id}]
    elif family == "temperature_sensor" and any(value in lower for value in ("lower", "threshold", "temperature", "earlier")):
        params = dict(meta["parameters"]); old = params.get("threshold_c", 26); params["threshold_c"] = old - 2; meta["parameters"] = params
        summary = "Lower the temperature activation threshold"; operations = [{"operation": "replace_parameter", "path": "parameters.threshold_c", "oldValue": old, "newValue": params["threshold_c"]}]
    elif family in {"container", "reservoir"} and any(value in lower for value in ("larger", "capacity", "size", "width", "depth")):
        dimensions = {key: dict(value) for key, value in meta["dimensions"].items()}
        for key in ("width", "length"):
            old = dimensions[key]["value"]; dimensions[key]["value"] = round(old * 1.2)
            operations.append({"operation": "replace_parameter", "path": f"dimensions.{key}.value", "oldValue": old, "newValue": dimensions[key]["value"]})
        meta["dimensions"] = dimensions; summary = "Increase container capacity while preserving height"
        regenerate = (f"repr-{target.id.removeprefix('component-')}-3d",); unaffected = ("electronics",)
    elif family in {"motor_driver", "relay"} and "mosfet" in lower:
        params = dict(meta["parameters"]); old = params.get("driver_type"); params.update(driver_type="logic-level MOSFET", flyback_protection=True); meta["parameters"] = params
        summary = f"Replace {target.name} with a logic-level MOSFET"; regenerate = (f"repr-{target.id.removeprefix('component-')}-schematic",)
        operations = [{"operation": "replace_parameter", "path": "parameters.driver_type", "oldValue": old, "newValue": params["driver_type"]}]
    elif family in {"small_dc_pump", "pump"} and any(value in lower for value in ("move", "farther", "position")):
        old = meta.get("assembly_offset_mm", [0, 0, 0]); meta["assembly_offset_mm"] = [-35, -45, 0]
        summary = f"Move {target.name} farther from electronics while preserving fluid connections"; regenerate = (f"repr-{target.id.removeprefix('component-')}-3d",)
        operations = [{"operation": "replace_parameter", "path": "assembly_offset_mm", "oldValue": old, "newValue": meta["assembly_offset_mm"]}]
    else: raise ValueError("unsupported_modification")
    patch = GraphPatch(f"patch-{uuid4().hex}", (GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=target.id, changes={"metadata": meta}),), summary, graph.current_revision_id)
    verification = {"outcome": "accepted_with_warnings", "checks": [{"state": "PASSED", "message": "Target and values valid"}]}
    return ModificationProposal(f"proposal-{uuid4().hex}", base, tuple(ids), summary, mode, tuple(operations), (target.id,), unaffected, regenerate, verification, patch)


def inverse_proposal(graph: EngineeringGraph, revision: dict[str, Any]) -> ModificationProposal:
    diff = revision.get("verification", {}).get("diff")
    if not diff or not diff.get("changed"): raise ValueError("nothing_to_undo")
    patch, changed = revision["patch"], diff["changed"]
    attachment = next((item for item in changed if item.get("operation") in {"update_mechanical_attachment", "add_mechanical_attachment"}), None)
    if attachment:
        relation_id, connection_id = attachment["targetId"], attachment["connectionId"]
        if attachment["operation"] == "add_mechanical_attachment":
            if relation_id not in graph.relationships or connection_id not in graph.entities: raise ValueError("nothing_to_undo")
            patch_ops = [GraphOperation(PatchOperation.REMOVE_RELATIONSHIP, target_id=relation_id), GraphOperation(PatchOperation.REMOVE_ENTITY, target_id=connection_id)]
        else:
            old = attachment.get("oldValue") or {}; connection = graph.entities.get(connection_id)
            if relation_id not in graph.relationships or connection is None: raise ValueError("nothing_to_undo")
            metadata = dict(connection.metadata) | {"source_id": old["sourceId"], "target_id": old["targetId"],
                "source_interface": old["sourceInterface"], "target_interface": old["targetInterface"], "connection_type": "mechanical"}
            patch_ops = [GraphOperation(PatchOperation.UPDATE_RELATIONSHIP, target_id=relation_id,
                changes={"source_id": old["sourceId"], "target_id": old["targetId"], "type": "mechanical"}),
                GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=connection_id, changes={"metadata": metadata})]
        inverse = [{**attachment, "oldValue": attachment.get("newValue"), "newValue": attachment.get("oldValue")}]
        graph_patch = GraphPatch(f"patch-{uuid4().hex}", tuple(patch_ops), f"Undo: {patch.summary}", graph.current_revision_id)
        affected = tuple(diff.get("affected", [])); target_id = affected[0] if affected else graph.project_id
        return ModificationProposal(f"undo-{uuid4().hex}", len(graph.revisions), (target_id,), f"Undo: {patch.summary}", "undo", tuple(inverse), affected,
            tuple(diff.get("unchanged", [])), tuple(diff.get("regenerated", [])), {"outcome": "pending_graph_verification", "checks": []}, graph_patch)
    target_id = next((operation.target_id for operation in patch.operations if operation.operation is PatchOperation.UPDATE_ENTITY
                      and operation.target_id in graph.entities and graph.get(operation.target_id).kind is EntityKind.COMPONENT), None)
    if not target_id: raise ValueError("nothing_to_undo")
    target = graph.get(target_id); metadata = dict(target.metadata); inverse = []
    for change in changed:
        path = change["path"].split("."); cursor = metadata
        for key in path[:-1]: cursor = cursor.setdefault(key, {})
        current = cursor.get(path[-1]); cursor[path[-1]] = change["oldValue"]
        inverse.append({**change, "oldValue": current, "newValue": change["oldValue"]})
    graph_patch = GraphPatch(f"patch-{uuid4().hex}", (GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=target_id, changes={"metadata": metadata}),), f"Undo: {patch.summary}", graph.current_revision_id)
    return ModificationProposal(f"undo-{uuid4().hex}", len(graph.revisions), (target_id,), f"Undo: {patch.summary}", "undo", tuple(inverse),
        tuple(diff.get("affected", [target_id])), tuple(diff.get("unchanged", [])), tuple(diff.get("regenerated", [])),
        {"outcome": "accepted_with_warnings", "checks": [{"state": "PASSED", "message": "Prior structured values restored"}]}, graph_patch)
