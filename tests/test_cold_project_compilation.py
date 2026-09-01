import pytest
from fastapi.testclient import TestClient

from aura.workspace.server import create_app


@pytest.mark.parametrize("objective", [
    "Build a temperature-controlled ventilation flap",
    "Build a rotating display platform",
    "Build a light-controlled window shade",
])
def test_cold_supported_projects_compile_and_reopen(objective: str):
    with TestClient(create_app(storage_mode="memory")) as client:
        created = client.post("/api/projects", json={"objective": objective, "planningMode": "deterministic_test"})
        assert created.status_code == 201, created.text
        project = created.json()
        assert project["status"] in {"ready", "ready_with_limitations"}
        assert project["representations"]
        assert all(item["status"] == "ready" for item in project["representations"])
        reopened = client.get(f'/api/projects/{project["projectId"]}')
        assert reopened.status_code == 200
        assert reopened.json()["revision"] == project["revision"]
        assert client.get(f'/api/projects/{project["projectId"]}/assembly').json()["parts"]
        assert client.get(f'/api/projects/{project["projectId"]}/graph').json()["project_id"] == project["projectId"]
