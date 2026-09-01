"""TEST 21 - Phase 5.1 live Unreal Engine integration validation."""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.domain_manager import DomainManager  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.unreal.domain import (  # noqa: E402
    OutputLogIntelligence,
    UnrealDirector,
    UnrealSessionManager,
)


@dataclass
class FakeOperatorOutcome:
    ok: bool = True
    message: str = "Live Unreal operation completed."
    plan: object | None = None
    observations: list[dict] = field(default_factory=lambda: [{"live": True}])


def main() -> None:
    print("=" * 60)
    print("TEST 21: Live Unreal Integration")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_unreal_live_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        unreal_memory = memory.memory_dir / "domains" / "unreal"
        project = root / "LiveProject"
        (project / "Saved" / "Logs").mkdir(parents=True)
        (project / "Content").mkdir(parents=True)
        (project / "LiveProject.uproject").write_text(
            json.dumps({"EngineAssociation": "5.5", "Modules": [{"Name": "LiveProject"}]}),
            encoding="utf-8",
        )
        log_text = "\n".join(
            [
                "LogBlueprint: Error: [Compiler] Broken pin connection in BP_InventoryComponent",
                "LogBlueprint: Warning: Dead node detected in EventGraph",
                "LogPlayLevel: PIE: Play in editor started",
                "LogShaderCompilers: Display: Shader compilation finished",
            ]
        )
        (project / "Saved" / "Logs" / "LiveProject.log").write_text(log_text, encoding="utf-8")
        state_payload = {
            "editor_running": True,
            "active_project": "LiveProject",
            "editor_version": "5.5",
            "current_map": "/Game/Maps/TestMap",
            "current_mode": "BlueprintEditor",
            "selected_actors": ["BP_Player_C_0"],
            "selected_assets": ["/Game/Blueprints/BP_InventoryComponent"],
            "selected_blueprint": "BP_InventoryComponent",
            "current_tab": "EventGraph",
            "current_window": "Blueprint Editor",
            "compile_status": "failed",
            "shader_compilation_status": "idle",
            "pie_status": "running",
            "output_log_status": "errors",
            "modal_dialogs": ["Compile Results"],
            "busy": False,
            "viewport": {"mode": "Lit", "camera": [0, 0, 200]},
            "asset_browser": {"folder": "/Game/Blueprints", "assets": ["BP_InventoryComponent"]},
            "current_blueprint_graph": {
                "name": "BP_InventoryComponent.EventGraph",
                "nodes": [
                    {"id": "event", "name": "Event BeginPlay", "node_type": "event", "pins": ["Exec"]},
                    {"id": "add", "name": "Add Item", "node_type": "function", "pins": ["Exec", "Item"]},
                    {"id": "dead", "name": "Print String", "node_type": "debug", "pins": ["Exec"]},
                ],
                "connections": [
                    {"source_node": "event", "source_pin": "Exec", "target_node": "add", "target_pin": "Exec"}
                ],
                "execution_flow": ["event", "add"],
                "data_flow": ["Item -> Inventory"],
                "compile_status": "failed",
            },
        }
        state_file = unreal_memory / "live_editor_state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(json.dumps(state_payload), encoding="utf-8")

        session = UnrealSessionManager(unreal_memory, state_file=state_file, project_root=project)
        state = session.observe()
        assert state.editor_running
        assert state.active_project == "LiveProject"
        assert state.editor_version == "5.5"
        assert state.selected_blueprint == "BP_InventoryComponent"
        assert state.selected_actors == ["BP_Player_C_0"]
        assert state.pie_status == "running"
        assert state.modal_dialogs
        print("  Live editor state detection: PASS")

        issues = OutputLogIntelligence().classify(log_text)
        assert any(issue.category == "blueprint" and issue.severity == "error" for issue in issues)
        assert any("Reconnect" in step for issue in issues for step in issue.recovery)
        print("  Output Log classification: PASS")

        analysis = session.graph_analysis()
        assert analysis.graph_name == "BP_InventoryComponent.EventGraph"
        assert "dead" in analysis.dead_nodes
        assert analysis.compile_risks
        print("  Live Blueprint graph reading: PASS")

        health = session.project_health(state, issues)
        assert health.compile_health == "fail"
        assert health.blueprint_health == "fail"
        assert health.errors
        assert health.optimization_suggestions
        print("  Project health dashboard data: PASS")

        director = UnrealDirector(unreal_memory)
        director.session = session
        director.session.project_root = project
        plan = director.plan("Repair the inventory Blueprint compile failure.", project, "5.5")
        assert plan.editor_state and plan.editor_state.selected_blueprint == "BP_InventoryComponent"
        assert plan.graph_analysis and "dead" in plan.graph_analysis.dead_nodes
        assert plan.project_health and plan.project_health.compile_health == "fail"
        assert plan.output_issues
        assert "Observe Live Editor State" in plan.verification_pipeline
        assert "Monitor Output Log" in plan.verification_pipeline
        print("  Live-aware UnrealDirector plan: PASS")

        diagnosis = director.diagnose(log_text)
        assert "blueprint" in diagnosis["categories"]
        assert diagnosis["repair_steps"]
        print("  Automatic repair plan: PASS")

        dashboard = director.live_dashboard()
        assert dashboard["current_project"] == "LiveProject"
        assert dashboard["compile_status"] == "failed"
        assert dashboard["pie_status"] == "running"
        assert dashboard["errors"]
        assert dashboard["project_health"]["blueprint_health"] == "fail"
        print("  Engineering dashboard: PASS")

        calls: list[str] = []

        def operator_executor(goal: str):
            calls.append(goal)
            return FakeOperatorOutcome()

        manager = DomainManager(memory, root / "domains", operator_executor=operator_executor, include_legacy_unreal=True)
        unreal_domain = manager.domains["unreal"]
        unreal_domain.director.session = session
        result = manager.execute("Repair the inventory Blueprint compile failure in Unreal.")
        assert result.ok
        assert calls
        payload = json.loads(manager.domain_memory_path("unreal").read_text(encoding="utf-8"))
        last = payload[-1]
        assert last["live_editor_state"]["selected_blueprint"] == "BP_InventoryComponent"
        assert last["graph_analysis"]["dead_nodes"]
        assert last["project_health"]["compile_health"] == "fail"
        assert last["output_issues"]
        print("  ATLAS live Unreal execution memory: PASS")

    print("  TEST 21 PASS")


if __name__ == "__main__":
    main()
