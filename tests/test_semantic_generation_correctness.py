from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.service import VerificationService
from aura.workspace.bridge import WorkspaceBridge
from aura.workspace.representation_service import representation_specs
from aura.workspace.representations import RepresentationStatus, RepresentationType
from aura.workspace.server import create_app


REGRESSION_CASES = (
    ("Make a ball-on-plate balancing system.", {"moving_surface", "moving_body", "controlled_motion", "feedback_position"}),
    ("Make a two-axis camera platform that can pan and tilt.", {"moving_surface", "moving_body", "controlled_motion"}),
    ("Create a device that detects when a drawer is opened and turns on a light.", {"moving_body", "feedback_open_state", "light_output"}),
    ("Build a small mechanism that automatically keeps a container lid partially open based on temperature.", {"moving_body", "feedback_temperature", "controlled_motion"}),
    ("Create a tabletop machine that moves a lightweight object from one side to another using a small conveyor.", {"moving_surface", "moving_body", "controlled_motion"}),
)


def _graph(objective: str):
    plan = PlannerService().plan(ProjectRequest("Semantic regression", objective, ("Use low-voltage control",)))
    result = VerificationService().verify(plan)
    assert result.accepted, result.reasons
    return plan, result, WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id), result)


@pytest.mark.parametrize(("objective", "required_roles"), REGRESSION_CASES)
def test_objective_requirements_survive_semantic_compilation(objective: str, required_roles: set[str]):
    plan, result, graph = _graph(objective)
    components = [entity for entity in graph.find(kind=EntityKind.COMPONENT)]
    roles = {role for entity in components for role in entity.metadata["parameters"].get("functional_roles", ())}
    assert required_roles <= roles
    assert any(entity.metadata.get("semantic_requirement") for entity in graph.find(kind=EntityKind.REQUIREMENT))
    assert not [finding for finding in result.findings if finding.severity == "critical" and finding.state.value == "failed"]

    specs = representation_specs(graph)
    physical = [spec for spec in specs if spec.kind is RepresentationType.MECHANICAL_3D]
    circuit = next(spec for spec in specs if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
    assert {spec.semantic_ids[0] for spec in physical} == {entity.id for entity in components}
    assert not circuit.payload["unconnected"]
    assert circuit.payload["fidelity"] == {"portsComplete": True, "netsComplete": True}

    if "ball-on-plate" in objective:
        families = {entity.metadata.get("family") for entity in components}
        assert "tracked_object" in families and "conceptual_sensor" in families
        assert "distance_sensor" not in families
        assert sum(entity.metadata["parameters"].get("controlled_dof", 0) for entity in components) >= 2


def test_unrelated_planner_sensor_intent_is_preserved_as_unresolved():
    objective = "Make a ball-on-plate balancing system."
    request = ProjectRequest("Raw planner provenance", objective, ("Use low voltage",), components=(
        "controller", "tank level distance sensor", "ball position sensor", "two hobby servos", "balancing plate",
    ))
    plan = PlannerService().plan(request)
    trace = dict(next(entity for entity in plan.entities if entity.kind is EntityKind.PROJECT).metadata)["plannerIntentTrace"]
    tank = next(item for item in trace if item["plannerIntent"] == "tank level distance sensor")
    assert tank["resolutionQuality"] == "UNRESOLVED" and tank["normalizedFamily"] is None
    assert "distance_sensor" not in {component.role for component in plan.components}
    verified = VerificationService().verify(plan)
    assert verified.accepted
    assert any(finding.check == "FAMILY_104" for finding in verified.findings)


@pytest.mark.integration
def test_ball_project_has_renderable_proxies_and_honest_circuit_artifact():
    with TestClient(create_app(storage_mode="memory")) as client:
        response = client.post("/api/projects", json={"objective": "Make a ball-on-plate balancing system.", "planningMode": "deterministic_test"})
        assert response.status_code == 201, response.text
        project = response.json()
        graph = client.get(f"/api/projects/{project['projectId']}/graph").json()
        component_ids = {entity["id"] for entity in graph["entities"] if entity["kind"] == "component"}
        mechanical = [item for item in project["representations"] if item["type"] == "mechanical_3d"]
        assert project["status"] == "ready_with_limitations"
        assert {item["semanticIds"][0] for item in mechanical} == component_ids
        assert all(item["status"] == RepresentationStatus.READY.value for item in mechanical)
        assert all(client.get(f"/api/artifacts/{item['artifactId']}/content").json()["geometry"] for item in mechanical)
        circuit = next(item for item in project["representations"] if item["type"] == "circuit_schematic")
        payload = client.get(f"/api/artifacts/{circuit['artifactId']}/content").json()
        assert any(item.get("type") == "schematic_component" and item.get("aura_semantic_id") == "component-position-sensor" for item in payload)
        assert not any(item.get("type") == "source_component" and item.get("name", "").startswith("R") for item in payload)


SEMANTIC_SWEEP = (
    "Create a low voltage robotic arm.", "Build a small servo lid opener.", "Make a desk fan controller.",
    "Build a temperature controlled lid.", "Create a low voltage conveyor.", "Make a pan and tilt platform.",
    "Create a drawer open detector light.", "Build a small pump controller.", "Make a food dispensing mechanism.",
    "Create a camera platform.", "Build a rotating display platform.", "Make a small ventilation fan system.",
    "Create a liquid pump system.", "Build an automatic shade flap.", "Make a light activated indicator.",
    "Create a simple servo mechanism.", "Build a two-axis balancing platform.", "Make a temperature sensing controller.",
    "Create a small motorized belt conveyor.", "Build a tracked object platform.",
)


def test_semantic_generation_sweep_has_no_silent_critical_failures():
    assert len(SEMANTIC_SWEEP) == 20
    for index, objective in enumerate(SEMANTIC_SWEEP):
        plan = PlannerService().plan(ProjectRequest(f"sweep-{index}", objective, ("Use low voltage",)))
        result = VerificationService().verify(plan)
        assert result.accepted, (objective, result.reasons)
        assert not [finding for finding in result.findings if finding.severity == "critical" and finding.state.value == "failed"]
        graph = WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id), result)
        circuit = next(spec for spec in representation_specs(graph) if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
        assert circuit.payload["fidelity"]["portsComplete"] and circuit.payload["fidelity"]["netsComplete"], objective
