from __future__ import annotations

import subprocess
import sys

import pytest

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from aura.engineering_graph.patches import GraphOperation, GraphPatch, PatchOperation, apply_patch
from aura.engineering_graph.serialization import dumps, loads
from aura.infrastructure.persistence import JsonGraphRepository
from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.results import VerificationDecision, VerificationState
from aura.verification.service import VerificationService
from aura.workspace.bridge import WorkspaceBridge


@pytest.mark.unit
def test_request_to_verified_graph_revision_and_workspace_events() -> None:
    request = ProjectRequest(
        project_name="Water Monitor",
        objective="Measure tank level and display an alert",
        requirements=("Measure water level", "Display low-level warning"),
        components=("Level sensor", "Controller", "Display"),
        assumptions=("Indoor installation",),
        representation="system_diagram",
    )
    plan = PlannerService().plan(request)
    result = VerificationService().verify(plan)

    assert result.decision == VerificationDecision.MODIFY
    # Generic planning must not promote an untooled concept to tool-verified.
    assert result.state == VerificationState.ESTIMATED
    graph = EngineeringGraph(project_id=plan.entities[0].id)
    observed = []
    bridge = WorkspaceBridge()
    unsubscribe = bridge.subscribe(observed.append)
    graph = bridge.commit(graph, result)
    unsubscribe()

    assert graph.current_revision_id is not None
    assert graph.get(graph.project_id).kind == EntityKind.PROJECT
    assert len(graph.find(kind=EntityKind.COMPONENT)) >= 3
    assert all(entity.verification_status in {"conceptual", "estimated", "source_verified", "tool_verified"} for entity in graph.entities.values())
    event_types = [event.type for event in observed]
    assert event_types[0] == "project.started"
    assert event_types.index("verification.started") < event_types.index("verification.completed")
    assert event_types[-3:] == ["revision.committed", "project.created", "project.ready"]


@pytest.mark.unit
def test_graph_serialization_patch_and_revision_round_trip() -> None:
    plan = PlannerService().plan(ProjectRequest(
        project_name="Bridge", objective="Create a structural concept",
        requirements=("Span ten metres",), components=("Deck",),
    ))
    verified = VerificationService().verify(plan)
    graph = WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id), verified)
    restored = loads(dumps(graph))
    component = restored.find(kind=EntityKind.COMPONENT)[0]
    rename = GraphPatch(
        id="rename-deck", base_revision_id=restored.current_revision_id,
        summary="Clarify component name",
        operations=(GraphOperation(
            PatchOperation.UPDATE_ENTITY, target_id=component.id,
            changes={"name": "Primary Deck"},
        ),),
    )
    updated = apply_patch(restored, rename)

    assert updated.get(component.id).name == "Primary Deck"
    assert len(updated.revisions) == 2
    assert updated.revisions[-1].parent_id == restored.current_revision_id
    assert loads(dumps(updated)).current_revision_id == updated.current_revision_id


@pytest.mark.unit
def test_graph_repository_round_trip(tmp_path) -> None:
    plan = PlannerService().plan(ProjectRequest(
        "Repository Test", "Persist the project graph", ("Survive reload",)
    ))
    graph = WorkspaceBridge().commit(
        EngineeringGraph(plan.entities[0].id), VerificationService().verify(plan)
    )
    repository = JsonGraphRepository(tmp_path)
    repository.save(graph)

    restored = repository.load(graph.project_id)
    assert restored is not None
    assert restored.current_revision_id == graph.current_revision_id
    with pytest.raises(ValueError, match="not safe"):
        repository.load("../outside")


@pytest.mark.unit
def test_planner_rejects_invalid_structured_request() -> None:
    with pytest.raises(ValueError, match="requirement"):
        PlannerService().plan(ProjectRequest("Empty", "An objective", ()))


@pytest.mark.unit
def test_core_imports_do_not_load_optional_heavy_systems() -> None:
    code = """
import sys
import aura.engineering_graph.model
import aura.planner.service
import aura.verification.service
import aura.workspace.bridge
import aura.infrastructure
blocked = ['aura.legacy.unreal.domain', 'torch', 'PySide6', 'TTS']
loaded = [name for name in blocked if name in sys.modules]
raise SystemExit('unexpected imports: ' + repr(loaded) if loaded else 0)
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=10
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
