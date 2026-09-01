from __future__ import annotations
import json
from pathlib import Path
from fastapi.testclient import TestClient
from aura.capabilities import CAPABILITY_MANIFEST,CapabilityStatus,classify_objective
from aura.workspace.server import create_app

CORPUS=json.loads((Path(__file__).parent/"data"/"goal5_benchmarks.json").read_text())

def test_manifest_and_structured_classification():
 assert CAPABILITY_MANIFEST["domain"]=="low_voltage_mechatronics"
 assert classify_objective("Build a temperature controlled fan")["status"]==CapabilityStatus.SUPPORTED.value
 assert classify_objective("Build me something cool.")["status"]==CapabilityStatus.NEEDS_CLARIFICATION.value
 assert classify_objective("Design a full passenger aircraft.")["status"]==CapabilityStatus.UNSUPPORTED.value

def test_benchmark_corpus_satisfies_graph_representation_and_reload_invariants(tmp_path):
 app=create_app(storage_mode="sqlite",db_path=tmp_path/"workspace.db",artifact_dir=tmp_path/"artifacts");created=[]
 with TestClient(app) as client:
  for benchmark in CORPUS:
   response=client.post("/api/projects",json={"objective":benchmark["objective"],"planningMode":"deterministic_test"});assert response.status_code==201,response.text
   project=response.json();created.append((benchmark,project));graph=client.get(f'/api/projects/{project["projectId"]}/graph').json();ids=[x["id"] for x in graph["entities"]];assert len(ids)==len(set(ids))
   components={x["id"] for x in graph["entities"] if x["kind"]=="component"};assert components and all(r["source_id"] in ids and r["target_id"] in ids for r in graph["relationships"])
   assembly=client.get(f'/api/projects/{project["projectId"]}/assembly').json();assert all(part["semanticId"] in components for part in assembly["parts"])
   for entity in (x for x in graph["entities"] if x["kind"]=="component"):
    assert all(value.get("unit") for value in entity["metadata"].get("dimensions",{}).values())
   assert all(record["status"] in {"requested","ready","fallback"} and set(record["semanticIds"])<=components for record in project["representations"])
 app.state.workspace.repository.close();app=create_app(storage_mode="sqlite",db_path=tmp_path/"workspace.db",artifact_dir=tmp_path/"artifacts")
 with TestClient(app) as client:
  for benchmark,project in created: assert client.get(f'/api/projects/{project["projectId"]}').json()["revision"]==1

def test_non_irrigation_modifications_are_selective(tmp_path):
 app=create_app(storage_mode="sqlite",db_path=tmp_path/"db",artifact_dir=tmp_path/"a")
 with TestClient(app) as client:
  fan=client.post("/api/projects",json={"objective":CORPUS[1]["objective"],"planningMode":"deterministic_test"}).json();body={"projectId":fan["projectId"],"baseRevision":1,"selectedSemanticIds":["component-temperature-sensor"],"request":"Turn the fan on at a lower temperature","mode":"parameter_change"};p=client.post(f'/api/projects/{fan["projectId"]}/modification-proposals',json=body).json();assert p["artifactsToRegenerate"]==[];assert client.post(f'/api/projects/{fan["projectId"]}/modification-proposals/{p["proposalId"]}/commit').json()["revision"]==2
  feeder=client.post("/api/projects",json={"objective":CORPUS[2]["objective"],"planningMode":"deterministic_test"}).json();body={"projectId":feeder["projectId"],"baseRevision":1,"selectedSemanticIds":["component-container"],"request":"Use a larger food container","mode":"parameter_change"};p=client.post(f'/api/projects/{feeder["projectId"]}/modification-proposals',json=body).json();assert p["artifactsToRegenerate"]==["repr-container-3d"] and "repr-system-schematic" not in p["artifactsToRegenerate"]
  out=client.post(f'/api/projects/{feeder["projectId"]}/modification-proposals/{p["proposalId"]}/commit').json();assert out["revision"]==2

def test_unsupported_and_underspecified_api_results():
 app=create_app(storage_mode="memory")
 with TestClient(app) as client:
  for objective,status in (("Design a full passenger aircraft.","UNSUPPORTED"),("Build me something cool.","NEEDS_CLARIFICATION")):
   response=client.post("/api/projects",json={"objective":objective,"planningMode":"deterministic_test"});assert response.status_code==422 and response.json()["detail"]["status"]==status
