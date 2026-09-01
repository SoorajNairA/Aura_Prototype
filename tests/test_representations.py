from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aura.engineering_graph.model import EngineeringGraph
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.service import VerificationService
from aura.workspace.bridge import WorkspaceBridge
from aura.workspace.representation_service import CircuitGeneratorAdapter, representation_specs
from aura.workspace.representations import (RepresentationRecord, RepresentationSpec,
    RepresentationSpecValidator, RepresentationStatus, RepresentationType, SpecValidationError)
from aura.workspace.server import create_app


OBJECTIVE="Design a small ESP32 irrigation controller with pump, sensor, driver, tubing, reservoir, enclosure, and power."


def graph():
    plan=PlannerService().plan(ProjectRequest("Automatic Irrigation System",OBJECTIVE,("Use low voltage",)))
    return WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id),VerificationService().verify(plan))


@pytest.mark.unit
def test_representation_lifecycle_and_invalid_transition():
    item=RepresentationRecord("repr-x","project-x",1,("component-pump",),RepresentationType.MECHANICAL_3D)
    item=item.transition(RepresentationStatus.GENERATING).transition(RepresentationStatus.READY).transition(RepresentationStatus.STALE)
    assert item.status is RepresentationStatus.STALE and item.semantic_ids == ("component-pump",)
    with pytest.raises(ValueError,match="Invalid representation transition"): item.transition(RepresentationStatus.READY)


@pytest.mark.unit
def test_mechanical_and_circuit_specs_are_bounded_and_non_executable():
    specs=representation_specs(graph());operations={spec.payload.get("geometry",{}).get("operation") for spec in specs}
    assert {"loft","pipe","filleted_enclosure"} <= operations
    invalid=RepresentationSpec(RepresentationType.MECHANICAL_3D,("component-reservoir",),{"units":"mm","coordinateSystem":{"forward":"+X","left":"+Y","up":"+Z"},"geometry":{"operation":"loft","sections":[{"z":0,"radius":float("inf")},{"z":1,"radius":2}]},"script":"bad"})
    with pytest.raises(SpecValidationError): RepresentationSpecValidator().validate(invalid,{"component-reservoir"})


@pytest.mark.integration
def test_node_generator_success_timeout_and_malformed_output(tmp_path: Path):
    circuit=next(spec for spec in representation_specs(graph()) if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
    result=CircuitGeneratorAdapter(timeout=15).generate(circuit)
    assert result.status is RepresentationStatus.READY and json.loads(result.artifact)[0]["type"]
    slow=tmp_path/"slow.mjs";slow.write_text("setTimeout(()=>{},10000)",encoding="utf8")
    with pytest.raises(TimeoutError): CircuitGeneratorAdapter(timeout=.05,script_path=slow).generate(circuit)
    malformed=tmp_path/"malformed.mjs";malformed.write_text("process.stdout.write('bad')",encoding="utf8")
    with pytest.raises(RuntimeError,match="malformed"): CircuitGeneratorAdapter(script_path=malformed).generate(circuit)


@pytest.mark.integration
def test_node_generator_location_is_independent_of_working_directory(tmp_path: Path):
    circuit=next(spec for spec in representation_specs(graph()) if spec.kind is RepresentationType.CIRCUIT_SCHEMATIC)
    previous=Path.cwd()
    try:
        os.chdir(tmp_path)
        assert CircuitGeneratorAdapter(timeout=15).generate(circuit).status is RepresentationStatus.READY
    finally:
        os.chdir(previous)


@pytest.mark.integration
def test_circuit_artifact_persists_and_driver_change_only_regenerates_schematic(tmp_path: Path):
    app=create_app(storage_mode="sqlite",db_path=tmp_path/"workspace.db",artifact_dir=tmp_path/"artifacts")
    with TestClient(app) as client:
        created=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"}).json();project_id=created["projectId"]
        before={item["representationId"]:item for item in created["representations"]};circuit=before["repr-system-schematic"]
        assert circuit["status"] == "ready" and client.get(f'/api/artifacts/{circuit["artifactId"]}/content').json()
        response=client.post(f"/api/projects/{project_id}/modifications",json={"selectedComponentId":"component-driver","request":"Replace relay with a logic-level MOSFET driver."})
        assert response.status_code == 200
        after={item["representationId"]:item for item in client.get(f"/api/projects/{project_id}").json()["representations"]}
        assert after["repr-system-schematic"]["artifactId"] != circuit["artifactId"]
        for key in ("repr-container-3d","repr-tube-3d","repr-enclosure-3d"): assert after[key]["artifactId"] == before[key]["artifactId"]
        types=[event.type for event in app.state.workspace.repository.get_events_after(project_id,0)]
        assert "representation.stale" in types and types.count("representation.ready") >= 2
    app.state.workspace.repository.close()


@pytest.mark.integration
def test_representation_metadata_survives_restart(tmp_path: Path):
    database=tmp_path/"workspace.db";artifacts=tmp_path/"artifacts";app=create_app(storage_mode="sqlite",db_path=database,artifact_dir=artifacts)
    with TestClient(app) as client: project=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"}).json()
    app.state.workspace.repository.close();restarted=create_app(storage_mode="sqlite",db_path=database,artifact_dir=artifacts)
    with TestClient(restarted) as client: assert client.get(f'/api/projects/{project["projectId"]}').json()["representations"] == project["representations"]
    restarted.state.workspace.repository.close()


@pytest.mark.integration
def test_circuit_generation_failure_persists_visible_fallback_events(tmp_path: Path):
    class FailingGenerator:
        generator_name="tscircuit";generator_version="0.0.1609"
        def generate(self, spec): raise RuntimeError("controlled generator failure")

    app=create_app(storage_mode="sqlite",db_path=tmp_path/"workspace.db",artifact_dir=tmp_path/"artifacts")
    app.state.workspace.representation_service.circuit_generator=FailingGenerator()
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"}).json()
        circuit=next(item for item in project["representations"] if item["type"] == "circuit_schematic")
        assert circuit["status"] == "fallback" and circuit["fallbackType"] == "placeholder"
        types=[event.type for event in app.state.workspace.repository.get_events_after(project["projectId"],0)]
        fallback_index=types.index("representation.fallback")
        assert types[fallback_index-1:fallback_index+1] == ["representation.failed","representation.fallback"]
        assert "narration.created" in types[fallback_index+1:]
    app.state.workspace.repository.close()
