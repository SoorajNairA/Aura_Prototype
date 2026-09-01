from dataclasses import replace

from fastapi.testclient import TestClient

from aura.workspace.representations import RepresentationRecord, RepresentationStatus
from aura.workspace.server import create_app


OBJECTIVE = "Design a small ESP32 irrigation controller with pump, sensor, driver, tubing, reservoir, enclosure, and low voltage power."


def create(client, operation="create-1"):
    response=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test","operationId":operation})
    assert response.status_code==201,response.text
    return response.json()


def propose(client, project, operation="proposal-1"):
    graph=client.get(f'/api/projects/{project["projectId"]}/graph').json()
    target=next(entity["id"] for entity in graph["entities"] if dict(entity["metadata"]).get("family") in {"container","reservoir"})
    response=client.post(f'/api/projects/{project["projectId"]}/modification-proposals',json={"projectId":project["projectId"],"baseRevision":project["revision"],"selectedSemanticIds":[target],"request":"Increase capacity by 40% but keep height","mode":"parameter_change","operationId":operation})
    assert response.status_code==201,response.text
    return response.json()


def test_writes_are_idempotent_and_durable_across_restart(tmp_path):
    db=tmp_path/"aura.db"; artifacts=tmp_path/"artifacts"
    app=create_app(storage_mode="sqlite",db_path=db,artifact_dir=artifacts)
    with TestClient(app) as client:
        first=create(client); second=create(client)
        assert first["projectId"]==second["projectId"] and second["revision"]==1
        proposal=propose(client,first); assert propose(client,first)["proposalId"]==proposal["proposalId"]
        url=f'/api/projects/{first["projectId"]}/modification-proposals/{proposal["proposalId"]}/commit'
        one=client.post(url,headers={"Idempotency-Key":"apply-1"}).json()
        two=client.post(url,headers={"Idempotency-Key":"apply-1"}).json()
        assert one==two and one["revision"]==2
        undo_url=f'/api/projects/{first["projectId"]}/revisions/undo'
        undone=client.post(undo_url,headers={"Idempotency-Key":"undo-1"}).json()
        repeated=client.post(undo_url,headers={"Idempotency-Key":"undo-1"}).json()
        assert undone==repeated and undone["revision"]==3
    app.state.workspace.repository.close()
    app=create_app(storage_mode="sqlite",db_path=db,artifact_dir=artifacts)
    with TestClient(app) as client:
        assert client.post(url,headers={"Idempotency-Key":"apply-1"}).json()==one
        assert client.get(f'/api/projects/{first["projectId"]}').json()["revision"]==3


def test_stale_representation_callbacks_are_ignored(tmp_path):
    app=create_app(storage_mode="sqlite",db_path=tmp_path/"db",artifact_dir=tmp_path/"a")
    with TestClient(app) as client:
        project=create(client)
        record=next(x for x in project["representations"] if x["type"]=="mechanical_3d")
        url=f'/api/projects/{project["projectId"]}/representations/{record["representationId"]}/status'
        base={"status":"generating","projectId":project["projectId"],"revision":record["revision"],"operationId":record["operationId"],"generation":record["generation"]}
        assert client.post(url,json={**base,"projectId":"another-project"}).json()["ignored"]
        assert client.post(url,json={**base,"revision":record["revision"]+1}).json()["ignored"]
        assert client.post(url,json={**base,"operationId":"old-operation"}).json()["ignored"]
        assert client.post(url,json={**base,"generation":record["generation"]-1}).json()["ignored"]
        current=client.get(f'/api/projects/{project["projectId"]}').json()
        unchanged=next(x for x in current["representations"] if x["representationId"]==record["representationId"])
        assert unchanged["status"]==record["status"]


def test_interrupted_generation_recovers_to_visible_fallback(tmp_path):
    app=create_app(storage_mode="sqlite",db_path=tmp_path/"db",artifact_dir=tmp_path/"a")
    with TestClient(app) as client:
        project=create(client)
        workspace=app.state.workspace; stored=workspace.repository.get_project(project["projectId"])
        item=RepresentationRecord.from_dict(stored.representations[1])
        stuck=replace(item,status=RepresentationStatus.GENERATING,operation_id="lost-worker",generation=item.generation+1)
        stored.representations[1]=stuck.to_dict(); workspace.repository.update_representations(stored.project_id,stored.representations)
        recovered=client.get(f'/api/projects/{stored.project_id}').json()["representations"][1]
        assert recovered["status"]=="fallback" and "interrupted" in recovered["error"].lower()
        assert recovered["generation"]==stuck.generation+1


def test_websocket_replay_is_monotonic_and_deduplicable(tmp_path):
    app=create_app(storage_mode="sqlite",db_path=tmp_path/"db",artifact_dir=tmp_path/"a")
    with TestClient(app) as client:
        project=create(client); events=app.state.workspace.repository.get_events_after(project["projectId"],0)
        after=events[-3].event_id
        with client.websocket_connect(f'/api/projects/{project["projectId"]}/events?afterEventId={after}') as socket:
            replay=[socket.receive_json() for _ in range(2)]
        assert [x["eventId"] for x in replay]==[after+1,after+2]
        assert len({x.event_id for x in events})==len(events)
