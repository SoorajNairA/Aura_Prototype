"""TEST 20 - Phase 5 Unreal Engine Professional Domain validation."""
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
    BlueprintGraphEngine,
    UnrealDecisionEngine,
    UnrealDirector,
    UnrealDocumentationEngine,
    UnrealProfessionalDomain,
    UnrealProjectScanner,
)


@dataclass
class FakeOperatorPlan:
    steps: list = field(default_factory=list)


@dataclass
class FakeOperatorOutcome:
    ok: bool = True
    message: str = "Unreal editor workflow completed."
    plan: FakeOperatorPlan = field(default_factory=FakeOperatorPlan)
    observations: list[dict] = field(default_factory=lambda: [{"editor": "unreal"}])


def main() -> None:
    print("=" * 60)
    print("TEST 20: Unreal Professional Domain")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_unreal_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        unreal_project = root / "ShooterProject"
        (unreal_project / "Content" / "Blueprints").mkdir(parents=True)
        (unreal_project / "Content" / "UI").mkdir(parents=True)
        (unreal_project / "Source" / "ShooterProject").mkdir(parents=True)
        (unreal_project / "Config").mkdir(parents=True)
        (unreal_project / "ShooterProject.uproject").write_text(
            json.dumps(
                {
                    "EngineAssociation": "5.4",
                    "Modules": [{"Name": "ShooterProject", "Type": "Runtime"}],
                    "Plugins": [{"Name": "GameplayAbilities", "Enabled": True}],
                }
            ),
            encoding="utf-8",
        )
        (unreal_project / "Content" / "Blueprints" / "BP_Player.uasset").write_text("", encoding="utf-8")
        (unreal_project / "Content" / "UI" / "W_Inventory.uasset").write_text("", encoding="utf-8")
        (unreal_project / "Config" / "GameplayTags.ini").write_text("[GameplayTags]\n", encoding="utf-8")

        docs = UnrealDocumentationEngine(memory.memory_dir / "domains" / "unreal" / "docs")
        refs = docs.search("inventory widget blueprint enhanced input", "5.4")
        assert refs
        assert any("Blueprint" in ref.title or "UMG" in ref.title for ref in refs)
        assert (memory.memory_dir / "domains" / "unreal" / "docs" / "documentation_cache.json").is_file()
        print("  Official documentation engine: PASS")

        scanner = UnrealProjectScanner()
        graph = scanner.scan(unreal_project)
        assert graph.project_name == "ShooterProject"
        assert graph.engine_version == "5.4"
        assert "GameplayAbilities" in graph.plugins
        assert graph.blueprints
        assert graph.widgets
        assert graph.gameplay_tags
        print("  Unreal project scanner: PASS")

        decision = UnrealDecisionEngine().decide("Integrate GAS multiplayer combat.", graph)
        assert decision.implementation == "hybrid"
        print("  Blueprint vs C++ decision engine: PASS")

        blueprint_graphs = BlueprintGraphEngine().generate("Build an inventory system.")
        assert blueprint_graphs[0].nodes
        assert blueprint_graphs[0].connections
        assert "Inventory" in blueprint_graphs[0].name
        repair = BlueprintGraphEngine().repair_strategy("Broken pin connection missing variable")
        assert any("Reconnect" in step for step in repair)
        assert any("variable" in step.lower() for step in repair)
        print("  Blueprint graph intelligence: PASS")

        director = UnrealDirector(memory.memory_dir / "domains" / "unreal")
        plan = director.plan("Build an inventory system with UI and save/load.", unreal_project, "5.4")
        assert "Gameplay Designer" in plan.specialists
        assert "Blueprint Engineer" in plan.specialists
        assert "UI Engineer" in plan.specialists
        assert plan.workflow.name == "inventory_system"
        assert plan.documentation
        assert "Compile" in plan.verification_pipeline
        assert "PIE" in plan.verification_pipeline
        assert plan.confidence >= 0.8
        print("  UnrealDirector engineering plan: PASS")

        diagnosis = director.diagnose("Blueprint compile error: broken pin connection missing asset")
        assert diagnosis["repair_steps"]
        assert diagnosis["documentation"]
        assert diagnosis["confidence"] >= 0.8
        print("  Debugging and recovery diagnosis: PASS")

        calls: list[str] = []

        def operator_executor(goal: str):
            calls.append(goal)
            return FakeOperatorOutcome()

        manager = DomainManager(
            memory=memory,
            domains_dir=root / "domains",
            operator_executor=operator_executor,
            include_legacy_unreal=True,
        )
        domain = manager.domains["unreal"]
        assert isinstance(domain, UnrealProfessionalDomain)
        route = manager.route("Build an enemy AI Behavior Tree and Blackboard in Unreal.")
        assert route and route[0].domain_id == "unreal"
        result = manager.execute("Build an enemy AI Behavior Tree and Blackboard in Unreal.")
        assert result.ok
        assert calls
        assert any(action["action"] == "consult_official_docs" for action in result.actions)
        assert any(action["action"] == "decide_blueprint_vs_cpp" for action in result.actions)
        unreal_memory = manager.domain_memory_path("unreal")
        assert unreal_memory.is_file()
        payload = json.loads(unreal_memory.read_text(encoding="utf-8"))
        assert payload[-1]["director"] == "UnrealDirector"
        assert payload[-1]["documentation"]
        assert payload[-1]["blueprint_graphs"]
        assert (memory.memory_dir / "domains" / "unreal" / "unreal_benchmarks.json").is_file()
        assert (memory.memory_dir / "domains" / "unreal" / "project_memory.json").is_file()
        print("  ATLAS Unreal domain execution: PASS")

    print("  TEST 20 PASS")


if __name__ == "__main__":
    main()
