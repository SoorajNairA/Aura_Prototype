"""TEST 24 - Phase 5.4 Unreal autonomous engineering / ASCENSION."""
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
    UnrealDirector,
    UnrealEngineeringDirector,
    UnrealProjectScanner,
)


def combat_inventory_graph() -> BlueprintGraph:
    return BlueprintGraph(
        name="BP_CombatInventoryCharacter",
        nodes=[
            BlueprintNode("begin", "Event BeginPlay", "event", ["Exec"]),
            BlueprintNode("input", "Enhanced Input Dodge", "function", ["Exec"]),
            BlueprintNode("stamina", "Stamina Component Consume", "function", ["Exec"]),
            BlueprintNode("equip", "Equipment Component Equip Weapon", "function", ["Exec"]),
            BlueprintNode("server", "Server RPC Apply Equipment", "rpc", ["Exec"]),
            BlueprintNode("ui", "Update W_Equipment", "function", ["Exec"]),
        ],
        connections=[
            BlueprintConnection("begin", "Exec", "input", "Exec"),
            BlueprintConnection("input", "Exec", "stamina", "Exec"),
            BlueprintConnection("stamina", "Exec", "equip", "Exec"),
            BlueprintConnection("equip", "Exec", "server", "Exec"),
            BlueprintConnection("server", "Exec", "ui", "Exec"),
        ],
        execution_flow=["begin", "input", "stamina", "equip", "server", "ui"],
        data_flow=["DA_Weapon -> EquipmentComponent -> W_Equipment", "StaminaComponent -> CombatComponent -> ReplicatedState"],
        compile_status="planned",
    )


def main() -> None:
    print("=" * 60)
    print("TEST 24: Unreal Autonomous Engineering ASCENSION")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_ascension_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        project = root / "AscensionProject"
        (project / "Content" / "Blueprints").mkdir(parents=True)
        (project / "Content" / "UI").mkdir(parents=True)
        (project / "Source" / "AscensionProject").mkdir(parents=True)
        (project / "AscensionProject.uproject").write_text(
            json.dumps(
                {
                    "EngineAssociation": "5.6",
                    "Modules": [{"Name": "AscensionProject", "Type": "Runtime"}],
                    "Plugins": [{"Name": "GameplayAbilities", "Enabled": True}],
                }
            ),
            encoding="utf-8",
        )
        (project / "Content" / "Blueprints" / "BP_CombatInventoryCharacter.uasset").write_text("", encoding="utf-8")
        (project / "Content" / "UI" / "W_Equipment.uasset").write_text("", encoding="utf-8")

        scanner = UnrealProjectScanner()
        project_graph = scanner.scan(project)
        cortex_report = BlueprintReasoningEngine().analyze(combat_inventory_graph())
        director = UnrealEngineeringDirector(memory.memory_dir / "domains" / "unreal")
        autonomous = director.engineer(
            "I want a Souls-like inventory with equipment, durability and multiplayer.",
            project_graph,
            [],
            [cortex_report],
            health=UnrealDirector(memory.memory_dir / "domains" / "unreal").session.project_health(
                state=UnrealDirector(memory.memory_dir / "domains" / "unreal").session.observe(),
                issues=[],
            ),
            issues=[],
            specialists=["Gameplay Architect", "Blueprint Engineer", "Multiplayer Engineer"],
            decision=UnrealDirector(memory.memory_dir / "domains" / "unreal").decision_engine.decide("souls multiplayer inventory", project_graph),
        )
        assert autonomous.gameplay_objectives
        systems = {objective.subsystem for objective in autonomous.gameplay_objectives}
        assert "inventory" in systems
        assert "souls_combat" in systems
        assert "multiplayer" in systems
        assert autonomous.architecture_plan.dependencies.required_components
        assert "InventoryComponent" in autonomous.architecture_plan.dependencies.required_components
        assert "CombatComponent" in autonomous.architecture_plan.dependencies.required_components
        assert autonomous.architecture_plan.dependencies.implementation_order[0] == "Project baseline"
        assert len(autonomous.milestones) >= 5
        assert all(milestone.independently_verifiable for milestone in autonomous.milestones)
        assert any("Core Runtime" == milestone.name for milestone in autonomous.milestones)
        assert any("PIE" in step for step in autonomous.continuous_verification)
        assert any("Server owns authoritative state" in step for step in autonomous.gameplay_validation)
        assert "Multiplayer Engineer" in autonomous.specialist_sequence
        assert autonomous.quality_report.overall >= 80
        assert autonomous.engineering_documentation.architecture_overview
        assert autonomous.engineering_documentation.testing_results
        assert autonomous.completion_report
        assert (memory.memory_dir / "domains" / "unreal" / "unreal_experience.json").is_file()
        print("  Autonomous gameplay decomposition and scheduling: PASS")

        titan = UnrealDirector(memory.memory_dir / "domains" / "unreal")
        plan = titan.plan("Build a Souls-like inventory with equipment, durability and multiplayer.", project, "5.6")
        assert plan.autonomous_engineering is not None
        assert plan.autonomous_engineering.milestones
        assert plan.autonomous_engineering.quality_report.overall >= 80
        assert "Understand Goal" in plan.verification_pipeline
        assert "Architecture Planning" in plan.verification_pipeline
        assert any("Core Runtime: Run PIE" in step for step in plan.verification_pipeline)
        assert plan.confidence >= 0.8
        print("  UnrealDirector ASCENSION integration: PASS")

        dashboard = titan.live_dashboard()
        assert dashboard["autonomous_engineering"]["experience_records"] >= 1
        assert "Architecture" in dashboard["autonomous_engineering"]["pipeline"]
        print("  Live dashboard ASCENSION status: PASS")

        manager = DomainManager(memory, root / "domains", include_legacy_unreal=True)
        result = manager.execute("Build a Souls-like inventory with equipment and multiplayer in Unreal.")
        assert result.ok
        assert any(action["action"] == "autonomous_engineering_plan" for action in result.actions)
        observation = result.observations[0]["unreal_plan"]
        assert observation["autonomous_engineering"]["milestones"]
        payload = json.loads(manager.domain_memory_path("unreal").read_text(encoding="utf-8"))
        assert payload[-1]["autonomous_engineering"]["quality_report"]["overall"] >= 80
        project_memory = json.loads((memory.memory_dir / "domains" / "unreal" / "project_memory.json").read_text(encoding="utf-8"))
        assert project_memory[-1]["autonomous_engineering"]["engineering_documentation"]["implementation_notes"]
        print("  ATLAS memory with ASCENSION proof: PASS")

    print("  TEST 24 PASS")


if __name__ == "__main__":
    main()
