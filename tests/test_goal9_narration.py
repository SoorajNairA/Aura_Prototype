from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from aura.engineering_graph.model import EngineeringEntity,EngineeringGraph,EntityKind
from aura.infrastructure.persistence.project_repository import StoredEvent
from aura.workspace.narration import (BoundedVertexPhraser,GroundedFact,NarrationCandidate,NarrationCoalescer,
    NarrationKind,NarrationPriority,NarrationService)
from aura.workspace.server import create_app

OBJECTIVE="Design a small ESP32 automatic irrigation system"


def graph():
    project=EngineeringEntity("project",EntityKind.PROJECT,"Project",verification_status="tool_verified")
    component=EngineeringEntity("component-pump",EntityKind.COMPONENT,"Pump","project",verification_status="estimated")
    finding=EngineeringEntity("verification-pump",EntityKind.VERIFICATION_RESULT,"Pump current is not specified.","project",
        {"check":"current","semanticIds":["component-pump"],"evidenceIds":["evidence-pump"]},
        source_refs=("evidence-pump",),verification_status="estimated")
    return EngineeringGraph("project",entities={x.id:x for x in (project,component,finding)})


@pytest.mark.unit
def test_committed_event_creates_grounded_narration_with_preserved_ids():
    event=StoredEvent(7,"project",2,"warning.created",["component-pump"],{"finding_id":"verification-pump"},"2026-01-01T00:00:00+00:00")
    result=NarrationService().events([event],graph(),[])[0]
    assert result.event_id==7 and result.semantic_ids==("component-pump",)
    assert result.verification_finding_ids==("verification-pump",) and result.evidence_ids==("evidence-pump",)
    assert result.priority is NarrationPriority.HIGH and len(result.text.split())<=60


class Provider:
    def __init__(self,payload):self.payload=payload
    def generate_structured(self,*_args,**_kwargs):return SimpleNamespace(text=json.dumps(self.payload))


@pytest.mark.unit
@pytest.mark.parametrize("payload",[
    {"text":"An unknown fact was used.","usedFactIds":["unknown"]},
    {"text":"The pump draws 9000 amps.","usedFactIds":["fact-1"]},
    {"text":"word "*40,"usedFactIds":["fact-1"]},
])
def test_invalid_vertex_phrasing_falls_back(payload):
    fact=GroundedFact("fact-1","Pump current remains estimated.","estimated",("component-pump",))
    candidate=NarrationCandidate(NarrationKind.VERIFICATION_EXPLANATION,"Pump current remains estimated.",("component-pump",),facts=(fact,))
    assert BoundedVertexPhraser(Provider(payload),35).phrase(candidate)==candidate.text


@pytest.mark.unit
def test_valid_vertex_phrasing_uses_only_allowed_fact():
    fact=GroundedFact("fact-1","Supply is 5 volts.","source_verified",("component-pump",),numeric_tokens=("5",))
    candidate=NarrationCandidate(NarrationKind.VERIFICATION_EXPLANATION,"The supply is 5 volts.",("component-pump",),facts=(fact,))
    assert BoundedVertexPhraser(Provider({"text":"The documented supply is 5 volts.","usedFactIds":["fact-1"]})).phrase(candidate).startswith("The documented")


@pytest.mark.unit
def test_coalescing_warning_bypass_and_queue_bound():
    queue=NarrationCoalescer(2)
    low=lambda text:NarrationCandidate(NarrationKind.PROJECT_PROGRESS,text,(),priority=NarrationPriority.LOW)
    queue.push(low("one"));queue.push(low("two"));queue.push(NarrationCandidate(NarrationKind.COMPLETION,"three",()))
    assert len(queue.flush())==2
    queue.push(low("obsolete"));urgent=NarrationCandidate(NarrationKind.WARNING,"Stop",(),priority=NarrationPriority.HIGH)
    assert queue.push(urgent)==(urgent,) and not queue.flush()


@pytest.mark.integration
def test_narration_persists_restart_and_fixed_benchmark_reopens(tmp_path:Path):
    database=tmp_path/"workspace.db";artifacts=tmp_path/"artifacts"
    with TestClient(create_app(storage_mode="sqlite",db_path=database,artifact_dir=artifacts)) as client:
        first=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"})
        assert first.status_code==201; project=first.json(); history=client.get(f"/api/projects/{project['projectId']}/narrations").json()
        assert history and any(x["kind"]=="completion" for x in history)
        second=client.post("/api/projects",json={"objective":"Design an ESP32 irrigation controller benchmark with a pump and reservoir","planningMode":"deterministic_test"})
        assert second.status_code==201 and second.json()["revision"]==1
    with TestClient(create_app(storage_mode="sqlite",db_path=database,artifact_dir=artifacts)) as client:
        restored=client.get(f"/api/projects/{project['projectId']}/narrations").json()
        assert restored==history


@pytest.mark.integration
def test_verification_evidence_and_modification_preview_narrations():
    with TestClient(create_app(storage_mode="memory")) as client:
        project=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"deterministic_test"}).json();pid=project["projectId"]
        history=client.get(f"/api/projects/{pid}/narrations").json()
        sourced=[x for x in history if x["kind"]=="verification_explanation" and x["evidenceIds"]]
        assert sourced and sourced[0]["semanticIds"]
        graph=client.get(f"/api/projects/{pid}/graph").json()
        target=next(item["id"] for item in graph["entities"] if dict(item["metadata"]).get("family") in {"container","reservoir"})
        body={"projectId":pid,"baseRevision":1,"selectedSemanticIds":[target],"request":"Increase capacity by 40% but keep height","mode":"parameter_change"}
        proposal=client.post(f"/api/projects/{pid}/modification-proposals",json=body)
        assert proposal.status_code==201
        preview=client.get(f"/api/projects/{pid}/narrations").json()[-1]
        assert preview["kind"]=="modification_summary" and target in preview["semanticIds"]
        assert "electronics unchanged" in preview["text"].lower()
