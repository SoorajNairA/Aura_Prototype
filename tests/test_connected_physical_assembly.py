from __future__ import annotations

import pytest

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.service import VerificationService
from aura.workspace.assembly import engineering_assembly
from aura.workspace.bridge import WorkspaceBridge
from aura.workspace.representation_service import representation_specs
from aura.workspace.representations import RepresentationType


CASES = {
    "solar": "Build a tabletop two-axis solar tracker that automatically points a small solar panel toward the brightest light source using an Arduino Nano.",
    "pan_tilt": "Build a two-axis pan-and-tilt camera mount.",
    "manipulator": "Build a three-axis tabletop robotic manipulator.",
    "sliding_door": "Build a small automatic sliding door.",
}


def compile_case(name: str):
    plan = PlannerService().plan(ProjectRequest(name, CASES[name], ("Use low-voltage power",)))
    verification = VerificationService().verify(plan)
    assert verification.accepted
    graph = WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id), verification)
    return graph, engineering_assembly(graph)


@pytest.mark.parametrize("name", CASES)
def test_primary_mechanisms_are_mate_driven_and_visually_connected(name):
    _, assembly = compile_case(name)
    parts = {part["semanticId"]: part for part in assembly["parts"]}
    assert assembly["primaryMechanismIds"]
    assert not assembly["unresolvedPrimaryMechanism"]
    assert all(parts[item]["transformSource"] in {"FIXED_ROOT", "MATE_SOLVED"} for item in assembly["primaryMechanismIds"])
    assert assembly["visualConnectivity"]["allMateOriginsWithinTolerance"]
    assert assembly["visualConnectivity"]["allMateAxesWithinTolerance"]
    assert not assembly["visualConnectivity"]["severeIntersections"]
    assert all(item["originDistanceMm"] <= .5 for item in assembly["mateDiagnostics"])
    assert not assembly["physicalRepresentationLimitations"]
    assert {part["placementClass"] for part in parts.values()} <= {"MATED", "MOUNTED_INDEPENDENTLY"}


def test_solar_tracker_has_two_axis_chain_panel_sensor_and_mounted_electronics():
    _, assembly = compile_case("solar")
    parts = {part["semanticId"]: part for part in assembly["parts"]}
    families = {part["family"] for part in parts.values()}
    assert {"base", "servo", "articulated_link", "panel", "light_sensor", "microcontroller_board", "low_voltage_power_source"} <= families
    assert sum(item["type"] == "revolute" for item in assembly["relationships"]) == 2
    panel = next(part for part in parts.values() if part["family"] == "panel")
    sensor = next(part for part in parts.values() if part["family"] == "light_sensor")
    controller = next(part for part in parts.values() if part["family"] == "microcontroller_board")
    power = next(part for part in parts.values() if part["family"] == "low_voltage_power_source")
    assert panel["dimensions"][0] >= 180 and panel["dimensions"][2] <= 8
    assert panel["semanticId"] in sensor["mechanicalParents"]
    assert controller["transformSource"] == power["transformSource"] == "MATE_SOLVED"
    assert all(part["transformSource"] != "INDEPENDENT_LAYOUT" for part in parts.values())
    assert len(assembly["visualizationPose"]) == 2


def test_other_mechanisms_reuse_topology_but_have_distinct_terminal_families():
    states = {name: compile_case(name)[1] for name in ("pan_tilt", "manipulator", "sliding_door")}
    pan_families = {part["family"] for part in states["pan_tilt"]["parts"]}
    arm_families = {part["family"] for part in states["manipulator"]["parts"]}
    door_families = {part["family"] for part in states["sliding_door"]["parts"]}
    assert "camera_platform" in pan_families and "panel" not in pan_families
    assert "tool_platform" in arm_families and sum(item["type"] == "revolute" for item in states["manipulator"]["relationships"]) == 3
    assert {"structural_frame", "linear_drive", "sliding_panel"} <= door_families
    assert any(item["type"] == "prismatic" for item in states["sliding_door"]["relationships"])


def test_reusable_family_proxies_expose_recognizable_subparts():
    _, assembly = compile_case("solar")
    parts_by_family = {part["family"]: part for part in assembly["parts"]}
    assert {"body", "mounting_ears", "output_shaft", "cross_horn", "cable_exit"} <= set(parts_by_family["servo"]["representationFeatures"])
    assert {"pcb", "usb_connector", "header_rows", "module_blocks"} <= set(parts_by_family["microcontroller_board"]["representationFeatures"])
    assert {"thin_surface", "backing_frame", "rear_mount", "cell_grid"} <= set(parts_by_family["panel"]["representationFeatures"])
    assert {"sensor_pcb", "four_quadrant_head", "divider_cross"} <= set(parts_by_family["light_sensor"]["representationFeatures"])
    assert {"beam", "proximal_joint", "distal_joint"} <= set(parts_by_family["articulated_link"]["representationFeatures"])


def test_schematic_and_physical_components_share_semantic_identity():
    graph, assembly = compile_case("solar")
    physical = {part["semanticId"] for part in assembly["parts"]}
    circuit = next(spec for spec in representation_specs(graph) if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
    schematic = {component["semanticId"] for component in circuit.payload["components"]}
    assert schematic <= physical
    assert {"component-light-sensor", "component-controller", "component-servo-1", "component-servo-2"} <= schematic
    connections = graph.find(kind=EntityKind.CONNECTION)
    assert any(item.metadata.get("source_id") == "component-light-sensor" and item.metadata.get("target_id") == "component-controller" and item.metadata.get("connection_type") == "signal" for item in connections)
    assert not any({item.metadata.get("source_id"), item.metadata.get("target_id")} == {"component-light-sensor", "component-servo-1"} for item in connections)
    assert not any({item.metadata.get("source_id"), item.metadata.get("target_id")} == {"component-light-sensor", "component-servo-2"} for item in connections)


def test_all_electrical_ports_have_world_resolvable_connector_positions():
    graph, assembly = compile_case("solar")
    electrical_kinds = {"electrical_power_in", "electrical_power_out", "electrical_ground", "control_input", "control_output", "signal_output"}
    component_ids = {entity.id for entity in graph.find(kind=EntityKind.COMPONENT)}
    ports = [item for item in assembly["interfaces"] if item["type"] in electrical_kinds]
    assert ports
    assert all(item["semanticId"] in component_ids for item in ports)
    assert all(len(item["worldPosition"]) == 3 and all(isinstance(value, float) for value in item["worldPosition"]) for item in ports)


def test_mechanical_artifacts_preserve_family_proxy_render_strategy():
    graph, _ = compile_case("solar")
    mechanical = [spec for spec in representation_specs(graph) if spec.kind is RepresentationType.MECHANICAL_3D]
    assert mechanical
    assert all(spec.payload["semanticCoverage"]["renderStrategy"] == "family_proxy" for spec in mechanical)
    assert {spec.payload["semanticCoverage"]["family"] for spec in mechanical} >= {"servo", "panel", "light_sensor"}
