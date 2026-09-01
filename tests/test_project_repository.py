from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aura.engineering_graph.serialization import patch_from_dict, patch_to_dict
from aura.infrastructure.persistence.project_repository import (
    PersistenceFailure, SCHEMA_VERSION, SQLiteProjectRepository, UnsupportedSchemaVersion,
)
from aura.workspace.server import create_app


OBJECTIVE = "Design a small ESP32-based automatic plant irrigation system with sensor, pump, driver, power, tubing, reservoir, and enclosure."


def create(client: TestClient) -> str:
    response = client.post("/api/projects", json={"objective": OBJECTIVE, "planningMode": "deterministic_test"})
    assert response.status_code == 201, response.text
    return response.json()["projectId"]


@pytest.mark.unit
def test_schema_initialization_and_version_rejection(tmp_path: Path) -> None:
    database = tmp_path / "workspace.db"
    repository = SQLiteProjectRepository(database, tmp_path / "artifacts")
    version = repository._connection.execute("SELECT version FROM schema_info").fetchone()[0]
    assert version == SCHEMA_VERSION
    repository.close()
    connection = sqlite3.connect(database)
    connection.execute("UPDATE schema_info SET version=999"); connection.commit(); connection.close()
    with pytest.raises(UnsupportedSchemaVersion):
        SQLiteProjectRepository(database, tmp_path / "artifacts")


@pytest.mark.unit
def test_patch_round_trip() -> None:
    from aura.planner.schemas import ProjectRequest
    from aura.planner.service import PlannerService
    plan = PlannerService().plan(ProjectRequest("Automatic Irrigation System", OBJECTIVE, ("Use low voltage",)))
    restored = patch_from_dict(json.loads(json.dumps(patch_to_dict(plan.patch))))
    assert restored.id == plan.patch.id
    assert restored.operations == plan.patch.operations


@pytest.mark.integration
def test_project_graph_verification_revision_event_and_listing_persist(tmp_path: Path) -> None:
    database = tmp_path / "workspace.db"
    app = create_app(storage_mode="sqlite", db_path=database, artifact_dir=tmp_path / "artifacts")
    with TestClient(app) as client:
        project_id = create(client)
        assert client.get("/api/projects").json()[0]["projectId"] == project_id
        graph_before = client.get(f"/api/projects/{project_id}/graph").json()
        revisions = client.get(f"/api/projects/{project_id}/revisions").json()
        assert len(revisions) == 1
        assert revisions[0]["verification"]["findings"]
        events = app.state.workspace.repository.get_events_after(project_id, 0)
        assert [event.event_id for event in events] == list(range(1, len(events) + 1))
    app.state.workspace.repository.close()

    reopened = create_app(storage_mode="sqlite", db_path=database, artifact_dir=tmp_path / "artifacts")
    with TestClient(reopened) as client:
        assert client.get(f"/api/projects/{project_id}/graph").json() == graph_before
        assert len(client.get(f"/api/projects/{project_id}/revisions").json()) == 1
        assert reopened.state.workspace.repository.get_events_after(project_id, 5)[0].event_id == 6
    reopened.state.workspace.repository.close()


@pytest.mark.integration
def test_complete_restart_after_modification_and_websocket_replay(tmp_path: Path) -> None:
    database = tmp_path / "workspace.db"; artifacts = tmp_path / "artifacts"
    app = create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)
    with TestClient(app) as client:
        project_id = create(client)
        response = client.post(f"/api/projects/{project_id}/modifications", json={
            "selectedComponentId": "component-driver", "request": "Replace the relay with a logic-level MOSFET driver."})
        assert response.status_code == 200
        previous_last = app.state.workspace.repository.get_events_after(project_id, 0)[-1].event_id
    app.state.workspace.repository.close()

    restarted = create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)
    with TestClient(restarted) as client:
        graph = client.get(f"/api/projects/{project_id}/graph").json()
        driver = next(item for item in graph["entities"] if item["id"] == "component-driver")
        assert driver["name"] == "Logic-level MOSFET driver"
        assert len(client.get(f"/api/projects/{project_id}/revisions").json()) == 2
        after = 12
        expected = restarted.state.workspace.repository.get_events_after(project_id, after)
        with client.websocket_connect(f"/api/projects/{project_id}/events?afterEventId={after}") as socket:
            received = [socket.receive_json() for _ in expected]
        assert [item["eventId"] for item in received] == [item.event_id for item in expected]
        assert received[-1]["eventId"] == previous_last
    restarted.state.workspace.repository.close()


@pytest.mark.unit
def test_transaction_rolls_back_and_does_not_advance_events(tmp_path: Path) -> None:
    app = create_app(storage_mode="sqlite", db_path=tmp_path / "workspace.db", artifact_dir=tmp_path / "artifacts")
    with TestClient(app) as client:
        project_id = create(client)
        repository = app.state.workspace.repository
        project = repository.get_project(project_id)
        revisions_before = repository.list_revisions(project_id)
        events_before = repository.get_events_after(project_id, 0)
        patch = revisions_before[-1]["patch"]
        with pytest.raises(PersistenceFailure):
            repository.save_commit(project, patch, {}, [{"payload": {}}])
        assert len(repository.list_revisions(project_id)) == len(revisions_before)
        assert repository.get_events_after(project_id, 0) == events_before
    app.state.workspace.repository.close()


@pytest.mark.unit
def test_artifact_metadata_file_hash_and_path_protection(tmp_path: Path) -> None:
    app = create_app(storage_mode="memory", artifact_dir=tmp_path / "artifacts")
    with TestClient(app) as client:
        project_id = create(client)
    repository = app.state.workspace.repository
    artifact = repository.create_artifact(project_id, 1, ["component-pump"], "mechanical_3d", "glb")
    assert artifact.status == "pending" and artifact.relative_path is None
    ready = repository.write_artifact(artifact.artifact_id, b"glTF", "fixture", "1")
    assert ready.status == "ready" and len(ready.content_hash) == 64
    assert not Path(ready.relative_path).is_absolute()
    assert repository.resolve_artifact_path(ready.relative_path).read_bytes() == b"glTF"
    with pytest.raises(ValueError, match="escapes"):
        repository.resolve_artifact_path("../outside.glb")
    with pytest.raises(KeyError, match="Unknown artifact"):
        repository.write_artifact("artifact-00000000000000000000000000000000", b"x", "x", "1")
    repository.close()


@pytest.mark.integration
def test_unknown_project_returns_404(tmp_path: Path) -> None:
    app = create_app(storage_mode="sqlite", db_path=tmp_path / "workspace.db", artifact_dir=tmp_path / "artifacts")
    with TestClient(app) as client:
        assert client.get("/api/projects/missing").status_code == 404
        assert client.get("/api/projects/missing/graph").status_code == 404
        missing = client.get("/api/artifacts/artifact-missing")
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "artifact_not_found"
    app.state.workspace.repository.close()
