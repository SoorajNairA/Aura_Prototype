from __future__ import annotations

import os
from uuid import uuid4

import pytest

pytestmark = pytest.mark.gcp_live


def _enabled() -> None:
    if os.getenv("AURA_RUN_GCP_LIVE") != "1": pytest.skip("Set AURA_RUN_GCP_LIVE=1 to incur cloud usage")


def test_cloud_project_persistence_artifact_vertex_and_event_replay() -> None:
    _enabled()
    from fastapi.testclient import TestClient
    from aura.workspace.server import create_app
    app = create_app()
    objective = f"Design a temperature controlled fan using an ESP32, sensor, driver, fan, and low voltage power. Test {uuid4().hex[:8]}"
    with TestClient(app) as client:
        response = client.post("/api/projects", json={"objective": objective, "planningMode": "live_model"})
        assert response.status_code == 201, response.text
        project = response.json(); project_id = project["projectId"]
        assert project["planningMode"] == "live_model"
        artifacts = [item for item in project["representations"] if item.get("artifactId")]
        assert artifacts
        content = client.get(f"/api/artifacts/{artifacts[0]['artifactId']}/content")
        assert content.status_code == 200
        durable = app.state.workspace.repository.get_events_after(project_id, 0)
        assert durable == sorted(durable, key=lambda event: event.event_id)
        after = durable[-2].event_id
        with client.websocket_connect(f"/api/projects/{project_id}/events?afterEventId={after}") as socket:
            assert socket.receive_json()["eventId"] > after
    app.state.workspace.repository.close()
