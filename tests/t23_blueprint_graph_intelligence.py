"""TEST 23 - Phase 5.3 Blueprint graph intelligence / CORTEX."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.domain_manager import DomainManager  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.unreal.domain import (  # noqa: E402
    BlueprintConnection,
    BlueprintGraph,
    BlueprintNode,
    BlueprintReasoningEngine,
    OutputLogIntelligence,
    UnrealDirector,
    UnrealSessionManager,
)


def messy_inventory_graph() -> BlueprintGraph:
    return BlueprintGraph(
        name="BP_InventoryCharacter.EventGraph",
        nodes=[
            BlueprintNode("begin", "Event BeginPlay", "event", ["Exec"]),
            BlueprintNode("tick", "Event Tick", "event", ["Exec", "DeltaSeconds"]),
            BlueprintNode("cast1", "Cast To BP_PlayerController", "function", ["Exec", "Object"]),
            BlueprintNode("cast2", "Cast To BP_PlayerController", "function", ["Exec", "Object"]),
            BlueprintNode("getall", "Get All Actors Of Class", "function", ["Exec", "ActorClass"]),
            BlueprintNode("branch", "Branch Has Inventory Item", "branch", ["Exec", "Condition"]),
            BlueprintNode("widget", "Create Widget W_Inventory", "function", ["Exec", "Class", "Owning Player"]),
            BlueprintNode("server", "Server RPC Add Item", "rpc", ["Exec", "Item"]),
            BlueprintNode("broadcast", "On Inventory Changed Dispatcher", "dispatcher", ["Exec"]),
            BlueprintNode("dead", "Unused Debug Print", "function", ["Exec"]),
            BlueprintNode("missing", "Missing DA_Item Reference", "variable", ["Item"]),
        ],
        connections=[
            BlueprintConnection("begin", "Exec", "cast1", "Exec"),
            BlueprintConnection("cast1", "Exec", "widget", "Exec"),
            BlueprintConnection("tick", "Exec", "cast2", "Exec"),
            BlueprintConnection("cast2", "Exec", "getall", "Exec"),
            BlueprintConnection("getall", "Exec", "branch", "Exec"),
            BlueprintConnection("branch", "True", "server", "Exec"),
            BlueprintConnection("server", "Exec", "broadcast", "Exec"),
            BlueprintConnection("broadcast", "Exec", "ghost", "Exec"),
        ],
        execution_flow=["begin", "cast1", "widget"],
        data_flow=[
            "DA_Item -> InventoryArray -> W_Inventory",
            "InventoryArray -> Server RPC Add Item -> ReplicatedInventory",
        ],
        compile_status="failed",
    )


def main() -> None:
    print("=" * 60)
    print("TEST 23: Blueprint Graph Intelligence CORTEX")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_cortex_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        graph = messy_inventory_graph()
        log_text = "LogBlueprint: Error: Failed to compile BP_InventoryCharacter missing DA_Item pin connection"
        issues = OutputLogIntelligence().classify(log_text)

        cortex = BlueprintReasoningEngine()
        report = cortex.analyze(graph, issues)
        assert report.blueprint_name == graph.name
        assert "Inventory" in report.gameplay_systems
        assert "UI" in report.gameplay_systems
        assert "Replication" in report.gameplay_systems
        assert report.execution_paths
        assert report.data_dependencies
        assert "dead" in report.dead_execution
        assert any("ghost" in chain for chain in report.broken_chains)
        assert report.invalid_references
        assert any("Event Tick" in finding for finding in report.optimization_findings)
        assert any("Repeated casts" in finding for finding in report.optimization_findings)
        assert any("Blueprint Interfaces" in item or "cached" in item.lower() for item in report.refactoring_plan)
        assert any("Compile" in item or "pin" in item.lower() for item in report.repair_plan)
        assert report.design_patterns
        assert report.visualizations["execution_flow_graph"]
        assert report.visualizations["communication_graph"]
        assert report.complexity.node_count == len(graph.nodes)
        assert report.complexity.cyclomatic_complexity >= 2
        assert report.complexity.engineering_score < 100
        assert report.confidence >= 0.75
        print("  Blueprint reasoning report: PASS")

        after = BlueprintGraph(
            name=graph.name,
            nodes=graph.nodes[:-2] + [BlueprintNode("component", "Inventory Component", "component", ["Exec"])],
            connections=graph.connections[:-1],
            execution_flow=["begin", "component", "widget"],
            data_flow=["DA_Item -> InventoryComponent -> W_Inventory"],
            compile_status="planned",
        )
        diff = cortex.diff(graph, after)
        assert diff.added_nodes == ["Inventory Component"]
        assert "Unused Debug Print" in diff.removed_nodes
        assert diff.changed_execution_paths
        assert diff.architecture_impact
        print("  Blueprint diff engine: PASS")

        unreal_memory = memory.memory_dir / "domains" / "unreal"
        project = root / "CortexProject"
        (project / "Saved" / "Logs").mkdir(parents=True)
        (project / "Content").mkdir(parents=True)
        (project / "CortexProject.uproject").write_text(json.dumps({"EngineAssociation": "5.6"}), encoding="utf-8")
        (project / "Saved" / "Logs" / "CortexProject.log").write_text(log_text, encoding="utf-8")
        state_file = unreal_memory / "live_editor_state.json"
        state_file.parent.mkdir(parents=True)
        state_file.write_text(
            json.dumps(
                {
                    "editor_running": True,
                    "active_project": "CortexProject",
                    "editor_version": "5.6",
                    "selected_blueprint": "BP_InventoryCharacter",
                    "compile_status": "failed",
                    "current_blueprint_graph": {
                        "name": graph.name,
                        "nodes": [node.__dict__ for node in graph.nodes],
                        "connections": [connection.__dict__ for connection in graph.connections],
                        "execution_flow": graph.execution_flow,
                        "data_flow": graph.data_flow,
                        "compile_status": graph.compile_status,
                    },
                }
            ),
            encoding="utf-8",
        )

        director = UnrealDirector(unreal_memory)
        director.session = UnrealSessionManager(unreal_memory, state_file=state_file, project_root=project)
        plan = director.plan("Repair and refactor the inventory Blueprint graph.", project, "5.6")
        assert plan.blueprint_reasoning
        live_report = next(item for item in plan.blueprint_reasoning if item.blueprint_name == graph.name)
        assert live_report.repair_plan
        assert live_report.optimization_findings
        assert "Analyze Blueprint Graph" in plan.verification_pipeline
        assert any("Event Tick" in risk or "Repeated casts" in risk for risk in plan.risks)
        print("  UnrealDirector CORTEX integration: PASS")

        dashboard = director.live_dashboard()
        assert dashboard["blueprint_reasoning"]["blueprint_name"] == graph.name
        assert dashboard["blueprint_reasoning"]["repair_plan"]
        print("  Live dashboard CORTEX panel: PASS")

        manager = DomainManager(memory, root / "domains", include_legacy_unreal=True)
        unreal_domain = manager.domains["unreal"]
        unreal_domain.director.session = director.session
        result = manager.execute("Repair the inventory Blueprint graph in Unreal.")
        assert result.ok
        assert any(action["action"] == "analyze_blueprint_graphs" for action in result.actions)
        observation = result.observations[0]["unreal_plan"]
        assert observation["blueprint_reasoning"]
        payload = json.loads(manager.domain_memory_path("unreal").read_text(encoding="utf-8"))
        assert payload[-1]["blueprint_reasoning"]
        project_memory = json.loads((unreal_memory / "project_memory.json").read_text(encoding="utf-8"))
        assert project_memory[-1]["blueprint_reasoning"]
        print("  ATLAS memory with CORTEX proof: PASS")

    print("  TEST 23 PASS")


if __name__ == "__main__":
    main()
