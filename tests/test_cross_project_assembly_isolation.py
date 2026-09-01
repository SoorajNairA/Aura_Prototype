from __future__ import annotations

from hashlib import sha256
import json
from dataclasses import replace
import pytest

from fastapi.testclient import TestClient

from aura.workspace.server import create_app
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.service import VerificationService


CASES = (
    (
        "rover",
        "Build a two-wheel remote-controlled Arduino Nano rover with a 5 V battery, motor driver, and two DC motors.",
        "Rover",
    ),
    (
        "manipulator",
        "make a quad-axis robotic manipulator",
        "Quad-Axis Robotic Manipulator",
    ),
    (
        "sliding-door",
        "Build an automatic sliding door with a low-voltage controller.",
        "Automatic Sliding Door",
    ),
    (
        "turntable",
        "Build a rotating camera turntable with a low-voltage controller.",
        "Camera Turntable",
    ),
)


def _create(client: TestClient, objective: str) -> dict:
    response = client.post("/api/projects", json={"objective": objective, "planningMode": "deterministic_test"})
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["status"] != "build_incomplete"
    return project


def _state(client: TestClient, project: dict) -> dict:
    project_id = project["projectId"]
    graph = client.get(f"/api/projects/{project_id}/graph").json()
    assembly = client.get(f"/api/projects/{project_id}/assembly").json()
    current = client.get(f"/api/projects/{project_id}").json()
    artifacts = []
    for record in current["representations"]:
        metadata = client.get(f"/api/artifacts/{record['artifactId']}").json()
        assert metadata["projectId"] == project_id
        assert metadata["revision"] == current["revision"] == record["revision"]
        artifacts.append((record["representationId"], record["artifactId"], metadata["contentHash"]))
    return {"project": current, "graph": graph, "assembly": assembly, "artifacts": artifacts}


def _fingerprint(state: dict) -> str:
    """Test-only project-level fingerprint; reusable individual templates may match."""
    graph = state["graph"]
    assembly = state["assembly"]
    payload = {
        "components": sorted((entity["id"], entity["metadata"].get("family")) for entity in graph["entities"] if entity["kind"] == "component"),
        "mates": sorted((item["from"], item["to"], item["type"]) for item in assembly["relationships"]),
        "transforms": sorted((part["semanticId"], part["assembledTransform"]["position"], part["transformSource"]) for part in assembly["parts"]),
        "mechanicalSpecs": sorted((record[0], record[2]) for record in state["artifacts"] if record[0].endswith("-3d")),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def test_distinct_mechanical_projects_keep_graphs_artifacts_and_assemblies_isolated(tmp_path):
    database = tmp_path / "workspace.db"
    artifacts = tmp_path / "artifacts"
    app = create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)
    with TestClient(app) as client:
        projects = {name: _create(client, objective) for name, objective, _ in CASES}
        states = {name: _state(client, project) for name, project in projects.items()}

        # The project records own their artifacts even where the underlying
        # bounded component template legitimately produces matching geometry.
        artifact_ids = [artifact_id for state in states.values() for _, artifact_id, _ in state["artifacts"]]
        assert len(artifact_ids) == len(set(artifact_ids))
        assert len({_fingerprint(state) for state in states.values()}) == len(CASES)

        rover = states["rover"]
        rover_mates = rover["assembly"]["relationships"]
        assert len([part for part in rover["assembly"]["parts"] if part["family"] == "small_dc_motor"]) == 2
        assert len([part for part in rover["assembly"]["parts"] if part["family"] == "drive_wheel"]) == 2
        assert sum("shaft" in mate["from"] and "hub-input" in mate["to"] for mate in rover_mates) == 2
        assert not rover["assembly"]["unresolvedMechanicalRelations"]

        manipulator = states["manipulator"]
        entities = manipulator["graph"]["entities"]
        axis_requirement = next(entity for entity in entities if entity["id"] == "requirement-controlled-axes")
        assert axis_requirement["metadata"]["required_axes"] == 4
        components = [entity for entity in entities if entity["kind"] == "component"]
        axis_ids = {axis for entity in components for axis in entity["metadata"]["parameters"].get("controlled_axis_ids", [])}
        driven_axis_ids = {axis for entity in components for axis in entity["metadata"]["parameters"].get("driven_axis_ids", [])}
        assert axis_ids == driven_axis_ids == {"axis-1", "axis-2", "axis-3", "axis-4"}
        primary_mates=[mate for mate in manipulator["assembly"]["relationships"] if mate["from"].rsplit(":",1)[0] in manipulator["assembly"]["primaryMechanismIds"] and mate["to"].rsplit(":",1)[0] in manipulator["assembly"]["primaryMechanismIds"]]
        assert len(primary_mates) == 9  # four body mounts, four rotary outputs, one end platform
        assert manipulator["assembly"]["transformSourceCounts"]["MATE_SOLVED"] == 11
        assert all(part["transformSource"] in {"FIXED_ROOT", "MATE_SOLVED"} for part in manipulator["assembly"]["parts"] if part["semanticId"] in manipulator["assembly"]["primaryMechanismIds"])
        assert len({tuple(part["assembledTransform"]["position"]) for part in manipulator["assembly"]["parts"] if part["semanticId"] in manipulator["assembly"]["primaryMechanismIds"]}) == 10
        assert not manipulator["assembly"]["unresolvedMechanicalRelations"]
        assert not manipulator["assembly"]["unresolvedPrimaryMechanism"]

        sliding = states["sliding-door"]
        sliding_mates = sliding["assembly"]["relationships"]
        assert any("linear-output" in mate["from"] and "linear-input" in mate["to"] and mate["type"] == "prismatic" for mate in sliding_mates)
        assert {part["family"] for part in sliding["assembly"]["parts"]} >= {"linear_drive", "sliding_panel"}
        assert not sliding["assembly"]["unresolvedMechanicalRelations"]

        turntable = states["turntable"]
        turntable_families={part["family"] for part in turntable["assembly"]["parts"]}
        assert {"base", "servo", "camera_platform"} <= turntable_families
        assert "mounting_plate" not in turntable_families
        assert "enclosure" not in turntable_families
        assert "articulated_link" not in turntable_families
        turntable_primary_mates=[mate for mate in turntable["assembly"]["relationships"] if mate["from"].rsplit(":",1)[0] in turntable["assembly"]["primaryMechanismIds"] and mate["to"].rsplit(":",1)[0] in turntable["assembly"]["primaryMechanismIds"]]
        assert len(turntable_primary_mates) == 2
        assert not turntable["assembly"]["unresolvedPrimaryMechanism"]

        # A reusable template may recur, but no universal project-level bundle
        # may be injected into every unrelated mechanism.
        family_sets=[frozenset(part["family"] for part in state["assembly"]["parts"]) for state in states.values()]
        assert len(set(family_sets)) == len(CASES)
        assert not set.intersection(*(set(item) for item in family_sets)) >= {"enclosure", "mounting_plate", "generic_mechanical_part"}

        # Repeated switching must return the same project-owned graph and
        # transforms rather than a previously loaded scene or assembly state.
        for name in ("rover", "manipulator", "sliding-door", "turntable", "rover", "turntable", "sliding-door", "manipulator"):
            assert _state(client, projects[name]) == states[name]
    app.state.workspace.repository.close()

    reopened = create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)
    with TestClient(reopened) as client:
        for name, project in projects.items():
            assert _state(client, project) == states[name]
    reopened.state.workspace.repository.close()


def test_axis_requirement_rejects_a_vague_driven_mechanism():
    plan = PlannerService().plan(ProjectRequest(
        "Tri-Axis Robotic Manipulator",
        "Build a tri-axis robotic manipulator with three hobby servos.",
        ("Provide three independent servo control channels", "Use low voltage"),
    ))
    vague = replace(plan, components=tuple(
        replace(component, parameters={key: value for key, value in component.parameters.items() if key != "driven_axis_ids"})
        for component in plan.components
    ))
    result = VerificationService().verify(vague)
    assert not result.accepted
    assert any(finding.check == "MECH_311" and finding.severity == "critical" for finding in result.findings)


@pytest.mark.parametrize(("phrase", "expected"), (
    ("single-axis positioning stage", 1),
    ("dual axis positioning stage", 2),
    ("tri-axis positioning stage", 3),
    ("quad-axis positioning stage", 4),
    ("four independent degrees of freedom", 4),
    ("4-DOF positioning stage", 4),
    ("6 axis positioning stage", 6),
))
def test_structured_axis_language_is_preserved(phrase, expected):
    assert PlannerService._requested_axis_count(phrase) == expected


def test_servo_architecture_does_not_retain_an_unconnected_motor_driver():
    plan=PlannerService().plan(ProjectRequest(
        "Sliding mechanism", "Build an automatic sliding door with a low-voltage controller.",
        ("Use a motor-driven linear mechanism", "Use low voltage"),
        components=("microcontroller_board", "servo", "motor_driver", "mounting_plate", "generic_mechanical_part"),
    ))
    assert "motor_driver" not in {component.role for component in plan.components}
    assert VerificationService().verify(plan).accepted
