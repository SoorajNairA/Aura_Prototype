from fastapi.testclient import TestClient

from aura.workspace.server import create_app


OBJECTIVE = "Design a low-voltage irrigation controller with a pump, container, tube, enclosure, and power."


def create(client):
    response = client.post("/api/projects", json={"objective": OBJECTIVE, "planningMode": "deterministic_test"})
    assert response.status_code == 201
    return response.json()


def target(client, project, family):
    graph = client.get(f'/api/projects/{project["projectId"]}/graph').json()
    return next(item["id"] for item in graph["entities"] if dict(item["metadata"]).get("family") == family)


def proposal(client, project, semantic_id, text):
    return client.post(f'/api/projects/{project["projectId"]}/modification-proposals', json={
        "projectId": project["projectId"], "baseRevision": project["revision"],
        "selectedSemanticIds": [semantic_id], "request": text, "mode": "automatic",
    })


def test_preview_cancel_and_stale_revision(tmp_path):
    app = create_app(storage_mode="sqlite", db_path=tmp_path / "db", artifact_dir=tmp_path / "a")
    with TestClient(app) as client:
        project = create(client)
        response = proposal(client, project, target(client, project, "container"), "Increase capacity while keeping height")
        assert response.status_code == 201
        assert response.json()["artifactsToRegenerate"] == ["repr-container-3d"]
        assert client.delete(f'/api/projects/{project["projectId"]}/modification-proposals/{response.json()["proposalId"]}').json()["cancelled"]
        assert client.get(f'/api/projects/{project["projectId"]}').json()["revision"] == 1
        stale = proposal(client, {**project, "revision": 0}, target(client, project, "small_dc_pump"), "Move it farther")
        assert stale.status_code == 409


def test_commit_persists_and_undo_restores_generic_component(tmp_path):
    database, artifacts = tmp_path / "db", tmp_path / "a"
    app = create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)
    with TestClient(app) as client:
        project = create(client)
        component_id = target(client, project, "container")
        before = client.get(f'/api/projects/{project["projectId"]}/assembly').json()
        preview = proposal(client, project, component_id, "Increase capacity while keeping height").json()
        committed = client.post(f'/api/projects/{project["projectId"]}/modification-proposals/{preview["proposalId"]}/commit').json()
        assert committed["revision"] == 2
        after = client.get(f'/api/projects/{project["projectId"]}/assembly').json()
        before_part = next(item for item in before["parts"] if item["semanticId"] == component_id)
        after_part = next(item for item in after["parts"] if item["semanticId"] == component_id)
        assert after_part["dimensions"][:2] != before_part["dimensions"][:2]
    app.state.workspace.repository.close()
    with TestClient(create_app(storage_mode="sqlite", db_path=database, artifact_dir=artifacts)) as client:
        assert client.get(f'/api/projects/{project["projectId"]}/assembly').json() == after
        undo = client.post(f'/api/projects/{project["projectId"]}/revisions/undo').json()
        assert undo["revision"] == 3
