import json
from types import SimpleNamespace

from fastapi.testclient import TestClient
from aura.workspace.server import create_app

OBJECTIVE="Design a low voltage robotic arm with servo actuators and a controller"

class ScenarioProvider:
    def __init__(self):self.calls=[]
    def generate_structured(self,messages,**_kwargs):
        context=json.loads(messages[0]["content"]);self.calls.append(context)
        target=context["target"];candidate=context["candidateRequest"]["name"]
        incompatible=target["family"]=="light_sensor" and "servo" in candidate.lower()
        payload={"decision":"INCOMPATIBLE" if incompatible else "COMPATIBLE","candidateName":candidate,
            "candidateFamily":"servo" if incompatible else target["family"],
            "candidateFunctionalRoles":["controlled_motion"] if incompatible else target["functionalRoles"],
            "interfaceCompatibility":"INCOMPATIBLE" if incompatible else "COMPATIBLE","confidence":"HIGH",
            "rationale":"A servo produces motion and cannot perform ambient-light feedback." if incompatible else "The candidate preserves the target function and interfaces.",
            "missingRequiredRoles":target["functionalRoles"] if incompatible else [],"requiredChanges":[],"assumptions":[]}
        return SimpleNamespace(text=json.dumps(payload),model="test-scenario-model",input_tokens=20,output_tokens=30,total_tokens=50)

def setup(client):
    p=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"}).json();g=client.get(f"/api/projects/{p['projectId']}/graph").json()
    component=next(x for x in g["entities"] if x["kind"]=="component" and x["metadata"].get("family")=="servo")
    return p,component

def test_candidate_isolated_discard_and_apply_revision():
    app=create_app(provider=ScenarioProvider(),storage_mode="memory")
    with TestClient(app) as client:
        project,component=setup(client);pid=project["projectId"];base=project["revision"]
        scenario=client.post(f"/api/projects/{pid}/scenarios",json={"targetSemanticId":component["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"SG90 Micro Servo","componentDefinitionId":"sg90"}})
        assert scenario.status_code==200,scenario.text; data=scenario.json();assert data["analysis"]["candidate"]["component"]["name"]=="SG90 Micro Servo"
        assert set(data["analysis"]["verification"]["delta"]) >= {"resolvedFindings","introducedFindings","unchangedFindings","severityChanges","readinessBefore","readinessAfter","classification"}
        assert next(x for x in client.get(f"/api/projects/{pid}/graph").json()["entities"] if x["id"]==component["id"])["name"]==component["name"]
        assert "confidence" in data["analysis"] and not isinstance(data["analysis"]["confidence"],(int,float))
        client.delete(f"/api/projects/{pid}/scenarios/{data['scenarioId']}")
        assert client.get(f"/api/projects/{pid}").json()["revision"]==base
        again=client.post(f"/api/projects/{pid}/scenarios",json={"targetSemanticId":component["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"SG90 Micro Servo"}}).json()
        applied=client.post(f"/api/projects/{pid}/scenarios/{again['scenarioId']}/apply")
        assert applied.status_code==200,applied.text;assert applied.json()["revision"]==base+1
        assert applied.json()["previousRevisionId"]==again["baseRevisionId"] and applied.json()["newRevisionId"]
        assert applied.json()["targetSemanticId"]==component["id"] and component["id"] in applied.json()["affectedComponentIds"]
        regenerated=[item for item in applied.json()["representations"] if component["id"] in item["semanticIds"] or item["type"]=="circuit_schematic"]
        assert regenerated and all(item["revision"]==base+1 for item in regenerated)
        assert all(item["status"] in {"ready","fallback"} for item in regenerated)
        assert applied.json()["verificationDelta"]==again["analysis"]["verification"]["delta"]
        assert next(x for x in client.get(f"/api/projects/{pid}/graph").json()["entities"] if x["id"]==component["id"])["name"]=="SG90 Micro Servo"

def test_scenario_work_and_stale_protection():
    app=create_app(provider=ScenarioProvider(),storage_mode="memory")
    with TestClient(app) as client:
        project,component=setup(client);pid=project["projectId"]
        first=client.post(f"/api/projects/{pid}/scenarios",json={"targetSemanticId":component["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"SG90 Micro Servo"}}).json()
        work=client.post(f"/api/projects/{pid}/scenarios/{first['scenarioId']}/work")
        assert work.status_code==201 and work.json()["relatedComponentIds"]==[component["id"]]
        # A normal committed modification makes the ephemeral base stale.
        proposal=client.post(f"/api/projects/{pid}/modification-proposals",json={"projectId":pid,"baseRevision":project["revision"],"selectedSemanticIds":[component["id"]],"request":"replace with SG90","mode":"automatic"})
        if proposal.status_code==200:
            client.post(f"/api/projects/{pid}/modification-proposals/{proposal.json()['proposalId']}/commit")
            stale=client.post(f"/api/projects/{pid}/scenarios/{first['scenarioId']}/apply")
            assert stale.status_code==409 and stale.json()["detail"]["code"]=="SCENARIO_STALE"

def test_scenario_project_isolation_one_active_rule_and_no_implicit_work():
    app=create_app(provider=ScenarioProvider(),storage_mode="memory")
    with TestClient(app) as client:
        first,component=setup(client);a=first["projectId"]
        scenario=client.post(f"/api/projects/{a}/scenarios",json={"targetSemanticId":component["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"Candidate servo"}}).json()
        assert client.get(f"/api/projects/{a}/work").json()["summary"]["total"]==0
        second=client.post("/api/projects",json={"objective":"Design a low voltage temperature monitor with sensor and display","planningMode":"deterministic_test"}).json();b=second["projectId"]
        graph=client.get(f"/api/projects/{b}/graph").json();target=next(x for x in graph["entities"] if x["kind"]=="component")
        replacement=client.post(f"/api/projects/{b}/scenarios",json={"targetSemanticId":target["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"Candidate sensor"}}).json()
        assert client.post(f"/api/projects/{a}/scenarios/{scenario['scenarioId']}/apply").status_code==404
        assert client.post(f"/api/projects/{a}/scenarios/{replacement['scenarioId']}/apply").status_code==404
        assert client.get(f"/api/projects/{b}/work").json()["summary"]["total"]==0

def test_ai_rejects_role_incompatible_replacement_and_server_blocks_apply():
    provider=ScenarioProvider();app=create_app(provider=provider,storage_mode="memory")
    with TestClient(app) as client:
        project=client.post("/api/projects",json={"objective":"Build a tabletop two-axis solar tracker that automatically points a small solar panel toward the brightest light source using an Arduino Nano.","planningMode":"deterministic_test"}).json();pid=project["projectId"]
        graph=client.get(f"/api/projects/{pid}/graph").json();sensor=next(item for item in graph["entities"] if item["kind"]=="component" and item["metadata"].get("family")=="light_sensor")
        response=client.post(f"/api/projects/{pid}/scenarios",json={"targetSemanticId":sensor["id"],"changeType":"REPLACE_COMPONENT","value":{"name":"servo"}})
        assert response.status_code==200,response.text
        scenario=response.json();analysis=scenario["analysis"]
        assert provider.calls and analysis["ai"]["source"]=="structured_model"
        assert analysis["semanticAssessment"]["decision"]=="INCOMPATIBLE"
        assert analysis["semanticAssessment"]["missingRequiredRoles"]==["feedback_light"]
        assert analysis["verification"]["accepted"] is False
        assert analysis["verification"]["delta"]["readinessAfter"]=="INCOMPATIBLE"
        assert scenario["applicable"] is False and analysis["applicable"] is False
        blocked=client.post(f"/api/projects/{pid}/scenarios/{scenario['scenarioId']}/apply")
        assert blocked.status_code==422 and blocked.json()["detail"]["code"]=="SCENARIO_NOT_APPLICABLE"
        current=client.get(f"/api/projects/{pid}/graph").json()
        assert next(item for item in current["entities"] if item["id"]==sensor["id"])["name"]==sensor["name"]
