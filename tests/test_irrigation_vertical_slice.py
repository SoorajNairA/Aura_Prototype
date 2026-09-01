from __future__ import annotations

from dataclasses import replace

import pytest

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.planner.schemas import ConnectionSpec, ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.results import VerificationDecision, VerificationState
from aura.verification.service import VerificationService
from aura.workspace.bridge import WorkspaceBridge
from aura.workspace.prototype import render_workspace
from aura.workspace.view_models import WorkspaceProjection


def request() -> ProjectRequest:
    return ProjectRequest(
        "Automatic Irrigation System",
        "Design a small ESP32-based automatic plant irrigation system with a soil-moisture sensor, water pump, driver or relay, power source, tubing, and a basic enclosure.",
        ("Water automatically when soil is dry", "Use low-voltage DC power", "Keep water separated from electronics"),
        assumptions=("Use a capacitive moisture sensor", "Use a splash-resistant electronics enclosure"),
    )


@pytest.mark.unit
def test_benchmark_planner_produces_complete_valid_proposal() -> None:
    plan = PlannerService().irrigation_benchmark_plan(request())
    plan.validate()
    assert len(plan.subsystems) == 4
    assert {item.id for item in plan.components} >= {"component-esp32", "component-driver", "component-pump", "component-enclosure"}
    assert len(plan.connections) == 8
    assert all(item.interfaces and item.description and item.parameters for item in plan.components)


@pytest.mark.unit
def test_malformed_reference_is_rejected() -> None:
    plan = PlannerService().irrigation_benchmark_plan(request())
    broken = replace(plan, connections=plan.connections + (ConnectionSpec("bad", "missing", "component-pump", "x", "power+", "power", "invalid"),))
    result = VerificationService().verify(broken)
    assert result.decision == VerificationDecision.REJECT
    assert "missing component" in result.reasons[0]


@pytest.mark.unit
def test_direct_pump_gpio_is_rejected() -> None:
    plan = PlannerService().irrigation_benchmark_plan(request())
    direct = ConnectionSpec("direct", "component-esp32", "component-pump", "gpio-pump", "power+", "control", "unsafe direct drive")
    result = VerificationService().verify(replace(plan, connections=plan.connections + (direct,)))
    assert result.decision == VerificationDecision.REJECT
    assert any(item.check == "direct-pump-gpio" for item in result.findings)


@pytest.mark.unit
def test_missing_driver_warning_and_voltage_mismatch() -> None:
    plan = PlannerService().irrigation_benchmark_plan(request())
    no_driver = replace(plan, components=tuple(c for c in plan.components if c.id != "component-driver"),
        connections=tuple(c for c in plan.connections if "component-driver" not in {c.source_id, c.target_id}))
    missing = VerificationService().verify(no_driver)
    assert any(item.check == "missing-driver" and item.severity == "warning" for item in missing.findings)

    pump = next(c for c in plan.components if c.id == "component-pump")
    mismatched = replace(pump, parameters={**pump.parameters, "voltage_v": 12.0})
    voltage = VerificationService().verify(replace(plan, components=tuple(mismatched if c.id == pump.id else c for c in plan.components)))
    assert voltage.decision == VerificationDecision.REJECT
    assert any(item.check == "voltage" for item in voltage.findings)


@pytest.mark.unit
def test_valid_driver_has_only_actionable_warning() -> None:
    result = VerificationService().verify(PlannerService().irrigation_benchmark_plan(request()))
    assert result.accepted
    assert result.state == VerificationState.CROSS_CHECKED
    assert any(item.check == "flyback" for item in result.findings)
    assert not any(item.severity == "critical" for item in result.findings)


@pytest.mark.unit
def test_water_separation_warning() -> None:
    plan = PlannerService().irrigation_benchmark_plan(request())
    enclosure = next(c for c in plan.components if c.id == "component-enclosure")
    unsafe = replace(enclosure, parameters={**enclosure.parameters, "waterproofing": ""})
    result = VerificationService().verify(replace(plan, components=tuple(unsafe if c.id == enclosure.id else c for c in plan.components)))
    assert any(item.check == "water-separation" for item in result.findings)


def build_project():
    plan = PlannerService().irrigation_benchmark_plan(request())
    verified = VerificationService().verify(plan)
    bridge = WorkspaceBridge()
    graph = bridge.commit(EngineeringGraph(plan.entities[0].id), verified)
    return plan, verified, bridge, graph


@pytest.mark.integration
def test_complete_flow_graph_events_projection_and_ui() -> None:
    plan, verified, bridge, graph = build_project()
    assert graph.get(graph.project_id).name == "Automatic Irrigation System"
    assert len(graph.find(kind=EntityKind.SUBSYSTEM)) == 4
    assert len(graph.find(kind=EntityKind.COMPONENT)) == 8
    assert len(graph.revisions) == 1
    types = [event.type for event in bridge.events]
    assert types[0] == "project.started"
    assert types.index("requirements.created") < types.index("verification.started")
    assert types.index("warning.created") < types.index("verification.completed")
    assert "subsystem.added" in types and "component.added" in types and "connection.added" in types
    assert "warning.created" in types
    assert types[-3:] == ["revision.committed", "project.created", "project.ready"]
    projection = WorkspaceProjection.from_graph(graph)
    for event in bridge.events: projection.apply_event(event)
    assert projection.stage == "project.ready" and projection.revision_id == graph.current_revision_id
    page = render_workspace(graph)
    assert 'data-id="component-esp32"' in page
    assert "window.auraFocus" in page and "Component information" in page


@pytest.mark.unit
def test_semantic_selection_focus_and_priority() -> None:
    _, _, bridge, graph = build_project()
    projection = WorkspaceProjection.from_graph(graph)
    projection.hover(graph, "component-pump")
    assert projection.highlight("component-pump") == "hover"
    projection.focus(graph, {"component-pump", "component-driver"}, "Inspect pump switching")
    assert projection.highlight("component-pump") == "aura-focus"
    projection.select(graph, "component-pump")
    assert projection.highlight("component-pump") == "selected"
    bridge.selection_changed(graph.project_id, "component-pump")
    bridge.focus_requested(graph.project_id, ["component-driver"], "Review flyback protection")
    assert bridge.events[-2].entity_id == "component-pump"
    with pytest.raises(KeyError): projection.select(graph, "Pump")


@pytest.mark.integration
def test_relay_to_mosfet_patch_preserves_id_and_invalidates_dependencies() -> None:
    _, _, bridge, graph = build_project()
    old_revision = graph.current_revision_id
    patch = PlannerService().propose_mosfet_replacement(graph)
    result = VerificationService().verify_modification(graph, patch)
    updated = bridge.commit(graph, result)
    driver = updated.get("component-driver")
    assert driver.name == "Logic-level MOSFET driver"
    assert driver.id == "component-driver"
    assert len(updated.revisions) == 2 and updated.current_revision_id != old_revision
    stale = [item for item in updated.find(kind=EntityKind.VERIFICATION_RESULT) if item.verification_status == "stale"]
    assert stale and all("component-driver" in item.metadata.get("entity_ids", []) for item in stale)
    assert updated.get("verification-mosfet-update").verification_status == "estimated"
    assert updated.relationships["connection-driver-pump-edge"].metadata["driver_type"] == "logic-level-mosfet"
    assert any(event.type == "component.updated" and event.entity_id == "component-driver" for event in bridge.events)
    assert sum(event.type == "connection.updated" for event in bridge.events) >= 2
    assert "MOSFET" in bridge.events[-3].payload["summary"]
