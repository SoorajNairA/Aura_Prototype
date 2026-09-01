"""TEST 25 - Phase 5.5 Professional Unreal Studio Engineering / OMEGA."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.domain_manager import DomainManager  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.unreal.domain import UnrealDirector, UnrealStudioEngineeringEngine  # noqa: E402


def main() -> None:
    print("=" * 60)
    print("TEST 25: Professional Unreal Studio Engineering OMEGA")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_omega_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        project = root / "OmegaProject"
        (project / "Content" / "Blueprints").mkdir(parents=True)
        (project / "Content" / "UI").mkdir(parents=True)
        (project / "Content" / "Data").mkdir(parents=True)
        (project / "Source" / "OmegaProject").mkdir(parents=True)
        (project / "OmegaProject.uproject").write_text(
            json.dumps(
                {
                    "EngineAssociation": "5.6",
                    "Modules": [{"Name": "OmegaProject", "Type": "Runtime"}],
                    "Plugins": [
                        {"Name": "GameplayAbilities", "Enabled": True},
                        {"Name": "EnhancedInput", "Enabled": True},
                    ],
                }
            ),
            encoding="utf-8",
        )
        for rel in (
            "Content/Blueprints/BP_CombatCharacter.uasset",
            "Content/Blueprints/BP_CropPlot.uasset",
            "Content/UI/W_Inventory.uasset",
            "Content/Data/DA_Weapon.uasset",
        ):
            (project / rel).write_text("", encoding="utf-8")

        goal = "I want to make Elden Ring combat mixed with Monster Hunter weapons and Stardew farming."
        director = UnrealDirector(memory.memory_dir / "domains" / "unreal")
        plan = director.plan(goal, project, "5.6")
        assert plan.studio_engineering is not None
        omega = plan.studio_engineering
        assert omega.architecture_frozen
        assert "Soulslike" in omega.project_profile.game_genres
        assert "Farming" in omega.project_profile.game_genres
        assert "RPG" in omega.project_profile.game_genres
        assert "Combat" in omega.production_systems
        assert "Farming" in omega.production_systems
        assert "Save System" in omega.production_systems
        assert omega.project_profile.core_gameplay_loop
        assert omega.project_profile.roadmap
        assert omega.game_design.reward_systems
        assert omega.production_pipeline.discipline_sequence[0] == "Game Design"
        assert omega.production_pipeline.source_control
        assert omega.qa_report.required_passes
        assert omega.qa_report.packaging >= 80
        assert omega.documentation_package.completeness == 100.0
        assert omega.documentation_package.architecture_guide
        assert omega.documentation_package.gameplay_design_document
        assert omega.documentation_package.technical_design_document
        assert omega.documentation_package.deployment_guide
        assert omega.documentation_package.developer_handoff_guide
        assert omega.live_optimization
        assert omega.reflections
        assert "Performance" in omega.benchmark_categories
        assert "Packaging Readiness" in plan.verification_pipeline
        assert "Production QA" in plan.verification_pipeline
        assert plan.confidence >= 0.8
        print("  Studio-grade game/project intelligence: PASS")

        studio_dir = memory.memory_dir / "domains" / "unreal"
        assert (studio_dir / "studio_memory.json").is_file()
        assert (studio_dir / "professional_workflows.json").is_file()
        dashboard = director.live_dashboard()
        assert dashboard["studio_engineering"]["architecture_frozen"]
        assert dashboard["studio_engineering"]["studio_memory_records"] >= 1
        assert "Regression" in dashboard["studio_engineering"]["benchmark_categories"]
        print("  Studio memory and dashboard: PASS")

        engine = UnrealStudioEngineeringEngine(studio_dir)
        assert engine.workflow_reuse(["Combat", "Farming"])
        print("  Professional workflow reuse: PASS")

        manager = DomainManager(memory, root / "domains", include_legacy_unreal=True)
        result = manager.execute(goal + " in Unreal.")
        assert result.ok
        assert any(action["action"] == "studio_production_qa" for action in result.actions)
        observation = result.observations[0]["unreal_plan"]
        assert observation["studio_engineering"]["documentation_package"]["completeness"] == 100.0
        payload = json.loads(manager.domain_memory_path("unreal").read_text(encoding="utf-8"))
        assert payload[-1]["studio_engineering"]["qa_report"]["required_passes"]
        project_memory = json.loads((studio_dir / "project_memory.json").read_text(encoding="utf-8"))
        assert project_memory[-1]["studio_engineering"]["documentation_package"]["developer_handoff_guide"]
        print("  ATLAS memory with OMEGA proof: PASS")

    print("  TEST 25 PASS")


if __name__ == "__main__":
    main()
