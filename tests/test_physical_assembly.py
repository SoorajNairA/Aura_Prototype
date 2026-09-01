from aura.engineering_graph.model import EngineeringGraph
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.service import VerificationService
from aura.workspace.assembly import engineering_assembly, interpolate_position
from aura.workspace.bridge import WorkspaceBridge


def graph():
    plan=PlannerService().plan(ProjectRequest("Automatic Irrigation System","Design a small ESP32 irrigation controller with pump, sensor, driver, tubing, reservoir, enclosure, and power.",("Use low voltage",)))
    return WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id),VerificationService().verify(plan))


def test_semantic_assembly_is_complete_and_semantically_unique():
    assembly=engineering_assembly(graph());parts=assembly["parts"]
    ids=[part["semanticId"] for part in parts]
    assert len(ids)==len(set(ids))==len(parts)
    assert assembly["hierarchy"]
    assert {part["representationSource"] for part in parts}=={"family-aware procedural representation"}
    assert all(part["generatorFamily"].endswith("-proxy") for part in parts)


def test_connector_references_and_compatibility_are_valid():
    assembly=engineering_assembly(graph());ids={part["semanticId"] for part in assembly["parts"]}
    connectors={item["interfaceId"]:item for item in assembly["connectors"]}
    assert all(item["semanticId"] in ids for item in connectors.values())
    for relation in assembly["relationships"][:5]:
        left,right=connectors[relation["from"]],connectors[relation["to"]]
        assert right["type"] in left["compatibleTypes"] or left["type"] in right["compatibleTypes"]


def test_explode_interpolation_is_deterministic_reversible_and_separated():
    assembly=engineering_assembly(graph());parts=assembly["parts"]
    assert all(interpolate_position(part,0)==tuple(part["assembledTransform"]["position"]) for part in parts)
    assert all(interpolate_position(part,1)==tuple(part["explodedTransform"]["position"]) for part in parts)
    assert interpolate_position(parts[0],.4)==interpolate_position(parts[0],.4)
    assert all(interpolate_position(part,0,"electronics")==tuple(part["assembledTransform"]["position"]) for part in parts if part["subsystem"]!="electronics")
    exploded=[interpolate_position(part,1) for part in parts]
    assert len(set(exploded))==len(parts)


def test_assembly_reconstructs_identically_after_graph_serialization():
    from aura.engineering_graph.serialization import graph_from_dict,graph_to_dict
    original=graph();restored=graph_from_dict(graph_to_dict(original))
    assert engineering_assembly(restored)==engineering_assembly(original)
