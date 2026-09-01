import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from aura.workspace.server import create_app


CORPUS=json.loads((Path(__file__).parent/"data"/"goal5_benchmarks.json").read_text())


@pytest.mark.slow
def test_fifty_deterministic_reconstruct_cycles_across_benchmarks(tmp_path):
    db=tmp_path/"soak.db"; artifacts=tmp_path/"artifacts"
    app=create_app(storage_mode="sqlite",db_path=db,artifact_dir=artifacts)
    with TestClient(app) as client:
        projects=[]
        for benchmark in CORPUS:
            response=client.post("/api/projects",json={"objective":benchmark["objective"],"planningMode":"deterministic_test","operationId":f'soak-create-{benchmark["id"]}'})
            assert response.status_code==201
            projects.append((benchmark,response.json()))
        fan=projects[1][1]
        proposal=client.post(f'/api/projects/{fan["projectId"]}/modification-proposals',json={"projectId":fan["projectId"],"baseRevision":1,"selectedSemanticIds":["component-temperature-sensor"],"request":"Turn the fan on at a lower temperature","mode":"parameter_change","operationId":"soak-change"}).json()
        assert client.post(f'/api/projects/{fan["projectId"]}/modification-proposals/{proposal["proposalId"]}/commit',headers={"Idempotency-Key":"soak-apply"}).json()["revision"]==2
        assert client.post(f'/api/projects/{fan["projectId"]}/revisions/undo',headers={"Idempotency-Key":"soak-undo"}).json()["revision"]==3
    app.state.workspace.repository.close()

    for cycle in range(50):
        app=create_app(storage_mode="sqlite",db_path=db,artifact_dir=artifacts)
        with TestClient(app) as client:
            for benchmark,project in projects:
                loaded=client.get(f'/api/projects/{project["projectId"]}').json()
                graph=client.get(f'/api/projects/{project["projectId"]}/graph').json()
                events=app.state.workspace.repository.get_events_after(project["projectId"],0)
                ids={x["id"] for x in graph["entities"]}
                # Benchmark wording is compiled into reusable semantic families, not a
                # benchmark-specific set of stable component IDs.
                assert any(item["kind"]=="component" for item in graph["entities"])
                assert len(ids)==len(graph["entities"])
                assert len({x.event_id for x in events})==len(events)
                assert [x.event_id for x in events]==sorted(x.event_id for x in events)
                assert all(set(x["semanticIds"])<=ids for x in loaded["representations"])
                assert all(x["status"]!="generating" for x in loaded["representations"])
            assert client.get(f'/api/projects/{projects[1][1]["projectId"]}').json()["revision"]==3
        app.state.workspace.repository.close()
