from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.planner.schemas import ConnectionSpec, ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.catalogue import CATALOGUE, get, search
from aura.verification.evidence import EvidenceKind, EvidenceRecord
from aura.verification.results import VerificationState
from aura.verification.service import VerificationService
from aura.verification.units import compatible, convert, in_range
from aura.workspace.bridge import WorkspaceBridge
from aura.workspace.modifications import propose
from aura.workspace.server import create_app


def irrigation():
    return PlannerService().irrigation_benchmark_plan(ProjectRequest("Irrigation", "Design a small ESP32 automatic irrigation system",
        ("Use low-voltage DC",), assumptions=("Exact pump model is initially generic",)))


@pytest.mark.unit
def test_catalogue_is_small_filterable_and_rejects_unknown_ids():
    assert 30 <= len(CATALOGUE) <= 50
    assert len({x.component_definition_id for x in CATALOGUE}) == len(CATALOGUE)
    assert search(family="servo", voltage=5)
    assert search(family="low_voltage_power_source", minimum_current_ma=2000)
    with pytest.raises(KeyError): get("invented-part-number")


@pytest.mark.unit
def test_units_convert_ranges_and_reject_dimensions():
    assert convert(5000, "mV", "V") == pytest.approx(5)
    assert convert(7, "cm", "mm") == pytest.approx(70)
    assert in_range(500, "mA", 0.4, 0.6, "A")
    assert not compatible(5, "V", 5, "A")


@pytest.mark.unit
def test_evidence_hash_and_property_provenance_are_structured():
    record=EvidenceRecord.curated("e",EvidenceKind.MANUFACTURER_DATASHEET,"Title","https://example.test/data","Publisher",("supply_voltage",),"v1")
    assert len(record.content_hash)==64 and record.properties==("supply_voltage",)
    assert all(fact.evidence_id in item.evidence_ids for item in CATALOGUE for fact in item.properties.values())


@pytest.mark.unit
def test_invalid_variants_fail_deterministically():
    plan=irrigation(); service=VerificationService()
    direct=ConnectionSpec("unsafe","component-esp32","component-pump","gpio-pump","power+","control","unsafe")
    assert not service.verify(replace(plan,connections=plan.connections+(direct,))).accepted
    pump=next(x for x in plan.components if x.id=="component-pump")
    assert not service.verify(replace(plan,components=tuple(replace(x,parameters=dict(x.parameters)|{"voltage_v":12}) if x.id==pump.id else x for x in plan.components))).accepted
    driver=next(x for x in plan.components if x.id=="component-driver")
    strict=replace(driver,parameters=dict(driver.parameters)|{"flyback_protection":False,"protection_required":True})
    assert not service.verify(replace(plan,components=tuple(strict if x.id==driver.id else x for x in plan.components))).accepted
    enclosure=next(x for x in plan.components if x.id=="component-enclosure")
    wet=replace(enclosure,parameters=dict(enclosure.parameters)|{"waterproofing":""})
    wet_result=service.verify(replace(plan,components=tuple(wet if x.id==enclosure.id else x for x in plan.components)))
    assert any(x.check=="water-separation" and x.state is VerificationState.FAILED for x in wet_result.findings)
    assert not wet_result.accepted
    tiny=replace(enclosure,dimensions={"width":{"value":10,"unit":"mm"},"length":{"value":10,"unit":"mm"}})
    assert not service.verify(replace(plan,components=tuple(tiny if x.id==enclosure.id else x for x in plan.components))).accepted


@pytest.mark.integration
def test_evidence_persists_restart_and_exact_upgrade_invalidates_findings(tmp_path):
    path=tmp_path/"aura.db"
    app=create_app(storage_mode="sqlite",db_path=path,artifact_dir=tmp_path/"artifacts")
    with TestClient(app) as client:
        created=client.post("/api/projects",json={"objective":"Design a small ESP32 automatic irrigation system","planningMode":"deterministic_test"}).json();pid=created["projectId"]
        before=client.get(f"/api/projects/{pid}/verification").json();assert before["evidence"]
    with TestClient(create_app(storage_mode="sqlite",db_path=path,artifact_dir=tmp_path/"artifacts")) as client:
        after=client.get(f"/api/projects/{pid}/verification").json();assert after["evidence"]==before["evidence"]
        graph=client.get(f"/api/projects/{pid}/graph").json();assert graph["revisions"]


@pytest.mark.unit
def test_generic_to_exact_upgrade_uses_modification_pipeline():
    plan=irrigation();result=VerificationService().verify(plan);graph=WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id),result)
    proposal=propose(graph,1,["component-sensor"],"Use capacitive-soil-v1", "automatic")
    verified=VerificationService().verify_modification(graph,proposal.patch)
    updated=WorkspaceBridge().commit(graph,verified)
    pump=updated.get("component-sensor")
    assert pump.metadata["component_definition_id"]=="capacitive-soil-v1"
    assert pump.verification_status=="source_verified" and pump.source_refs
    assert any(x.verification_status=="stale" for x in updated.find(kind=EntityKind.VERIFICATION_RESULT))


@pytest.mark.integration
def test_generic_driver_declares_its_required_flyback_protection():
    with TestClient(create_app(storage_mode="memory")) as client:
        created=client.post("/api/projects",json={"objective":"Design a small ESP32 automatic irrigation system","planningMode":"deterministic_test"}).json()
        verification=client.get(f"/api/projects/{created['projectId']}/verification").json()
        assert not any(item["check"]=="flyback" and item["state"]=="failed" for item in verification["findings"])
