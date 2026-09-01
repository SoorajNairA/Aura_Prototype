"""TEST 22 - Phase 5.2 official Unreal documentation intelligence."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.legacy.assistant.domain_manager import DomainManager  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.unreal.domain import (  # noqa: E402
    UnrealDirector,
    UnrealDocumentationDirector,
)


def main() -> None:
    print("=" * 60)
    print("TEST 22: Unreal Documentation ORACLE")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_unreal_oracle_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        docs_dir = memory.memory_dir / "domains" / "unreal" / "docs"

        oracle = UnrealDocumentationDirector(docs_dir)
        search = oracle.semantic_search("Create Gameplay Ability replicated inventory", "5.6")
        assert search
        assert all(result.officiality == 1.0 for result in search)
        assert any("Gameplay Ability System" == result.page.title for result in search)
        assert any("Networking" in result.page.title for result in search)
        print("  Official semantic documentation search: PASS")

        widget = oracle.blueprint_node_lookup("Create Widget", "5.6")
        assert "Exec" in widget.execution_pins
        assert "Owning Player" in widget.parameters
        assert widget.examples
        assert widget.confidence >= 0.9
        print("  Blueprint node lookup: PASS")

        gas = oracle.cpp_api_lookup("UAbilitySystemComponent", "5.6")
        assert "TryActivateAbility" in gas.functions
        assert gas.confidence >= 0.9
        assert gas.documentation.url.startswith(oracle.OFFICIAL_HOST)
        print("  C++ API lookup: PASS")

        migration = oracle.compare_versions("5.1", "5.6")
        assert migration.migration_work
        assert migration.behavior_changes
        assert migration.confidence >= 0.8
        print("  Version comparison: PASS")

        branch_validation = oracle.validate_blueprint_node("Branch", "5.5")
        assert branch_validation.ok
        actor_validation = oracle.validate_cpp_api("AActor", "5.4", "BeginPlay")
        assert actor_validation.ok
        fake_validation = oracle.validate_cpp_api("FakeUnrealAPI", "5.6")
        assert not fake_validation.ok
        assert fake_validation.confidence <= 0.45
        print("  API hallucination guard: PASS")

        assert (docs_dir / "documentation_index.json").is_file()
        assert (docs_dir / "oracle_lookup_cache.json").is_file()
        offline = UnrealDocumentationDirector(docs_dir, offline=True)
        assert offline.semantic_search("replication inventory", "5.6")
        dashboard = offline.dashboard()
        assert dashboard["offline"]
        assert dashboard["indexed_pages"] >= 10
        assert "Epic Games Documentation" in dashboard["sources"]
        print("  Offline cache and dashboard: PASS")

        director = UnrealDirector(memory.memory_dir / "domains" / "unreal")
        plan = director.plan("Create a replicated inventory with Gameplay Ability support.", version="5.2")
        assert plan.documentation
        assert plan.documentation_citations
        assert plan.documentation_validations
        assert plan.version_comparison is not None
        assert plan.documentation_confidence > 0
        assert all("dev.epicgames.com" in citation for citation in plan.documentation_citations)
        print("  UnrealDirector ORACLE context: PASS")

        diagnosis = director.diagnose("Blueprint compile error: Create Widget missing Owning Player")
        assert diagnosis["documentation"]
        assert diagnosis["citations"]
        print("  Diagnostic documentation citations: PASS")

        dashboard = director.live_dashboard()
        assert dashboard["documentation"]["indexed_pages"] >= 10
        assert dashboard["documentation"]["api_validation_events"] >= 1
        print("  Live dashboard documentation panel: PASS")

        calls: list[str] = []

        def operator_executor(goal: str):
            calls.append(goal)
            return None

        manager = DomainManager(memory, root / "domains", operator_executor=operator_executor, include_legacy_unreal=True)
        result = manager.execute("Create a replicated inventory with Gameplay Ability support in Unreal.")
        assert result.ok
        assert any(action["action"] == "validate_official_documentation" for action in result.actions)
        observation = result.observations[0]["unreal_plan"]
        assert observation["documentation_citations"]
        assert observation["documentation_validations"]
        payload = json.loads(manager.domain_memory_path("unreal").read_text(encoding="utf-8"))
        assert payload[-1]["documentation_citations"]
        assert payload[-1]["documentation_validations"]
        assert payload[-1]["documentation_confidence"] > 0
        print("  ATLAS domain memory with ORACLE proof: PASS")

    print("  TEST 22 PASS")


if __name__ == "__main__":
    main()
