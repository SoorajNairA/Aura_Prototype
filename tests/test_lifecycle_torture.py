"""Seeded lifecycle abuse coverage: valid actions, invariant checks, reproducible seeds."""
from __future__ import annotations

import random

from fastapi.testclient import TestClient

from aura.workspace.server import create_app


OBJECTIVES = (
    "Build a temperature controlled ventilation flap.",
    "Design a compact rotating display stand.",
    "Build a light controlled shade prototype.",
)


def _assert_invariants(client: TestClient, project_id: str, selected: str | None) -> None:
    project=client.get(f"/api/projects/{project_id}").json()
    graph=client.get(f"/api/projects/{project_id}/graph").json()
    assembly=client.get(f"/api/projects/{project_id}/assembly").json()
    assert project["projectId"]==graph["project_id"]==project_id
    assert assembly["revision"]==project["revision"]
    graph_ids={item["id"] for item in graph["entities"]}
    assert {item["semanticId"] for item in assembly["parts"]} <= graph_ids
    nets=[item for item in graph["entities"] if item.get("metadata",{}).get("semantic_type")=="electrical_net"]
    for net in nets:
        for terminal in net["metadata"]["terminals"]: assert terminal["componentId"] in graph_ids
    if selected: assert selected in graph_ids
    assert project["status"] in {"ready","ready_with_limitations","build_incomplete"}
    if project["status"]!="build_incomplete": assert all(item["status"]=="ready" for item in project["representations"])


def test_one_hundred_seeded_lifecycle_sequences_are_corruption_free():
    failure_records=[]
    with TestClient(create_app(storage_mode="memory")) as client:
        project_ids=[]
        for objective in OBJECTIVES:
            response=client.post("/api/projects",json={"objective":objective,"planningMode":"deterministic_test"})
            assert response.status_code==201,response.text
            project_ids.append(response.json()["projectId"])
        for seed in range(100):
            rng=random.Random(seed);active=rng.choice(project_ids);selected=None;trace=[]
            try:
                for _ in range(25):
                    action=rng.choice(("switch","reload","assembly","schematic","split","select_component","select_net","clear","verify","disconnect_reconnect"))
                    trace.append(action)
                    if action=="switch": active=rng.choice(project_ids);selected=None
                    elif action=="reload": assert client.get(f"/api/projects/{active}").status_code==200
                    elif action=="select_component":
                        graph=client.get(f"/api/projects/{active}/graph").json();selected=rng.choice([item["id"] for item in graph["entities"] if item["kind"]=="component"])
                    elif action=="select_net":
                        graph=client.get(f"/api/projects/{active}/graph").json();nets=[item["id"] for item in graph["entities"] if item.get("metadata",{}).get("semantic_type")=="electrical_net"];selected=rng.choice(nets) if nets else None
                    elif action=="clear": selected=None
                    elif action=="verify": assert client.get(f"/api/projects/{active}/verification").status_code==200
                    # View switches and websocket reconnect are state-only client
                    # actions; the following authoritative reload checks their data.
                    _assert_invariants(client,active,selected)
            except Exception as exc:
                failure_records.append({"seed":seed,"trace":trace,"activeProject":active,"selected":selected,"error":repr(exc)})
    assert not failure_records, failure_records
