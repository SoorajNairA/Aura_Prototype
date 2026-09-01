"""TEST 19 - Phase 4 Domain Intelligence Platform validation."""
from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.tools.execution import ExecutionAgent  # noqa: E402
from aura.legacy.assistant.domain_manager import BuiltinDomainPack, DomainCapability, DomainManager  # noqa: E402
from aura.legacy.assistant.executive_agent import AssumptionEngine, ExecutiveAgent, ExecutionVerifier  # noqa: E402
from aura.legacy.assistant.llm import LLMService  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.planner import PlannerAgent  # noqa: E402
from aura.safety.policies import SafetyLayer  # noqa: E402
from aura.legacy.assistant.chief_architect import ChiefArchitect  # noqa: E402
from aura.verification.adapters.architecture_analysis import ArchitectureIntelligenceEngine  # noqa: E402


ROOT = Path(__file__).parent.parent


@dataclass
class FakeSoftwareOutcome:
    ok: bool = True
    message: str = "Software domain completed."
    actions: list[dict] = field(default_factory=lambda: [{"action": "software"}])
    artifacts: list[str] = field(default_factory=lambda: ["artifact.py"])


@dataclass
class FakeOperatorPlan:
    steps: list = field(default_factory=list)


@dataclass
class FakeOperatorOutcome:
    ok: bool = True
    message: str = "Operator domain completed."
    plan: FakeOperatorPlan = field(default_factory=FakeOperatorPlan)
    observations: list[dict] = field(default_factory=lambda: [{"observed": True}])


def main() -> None:
    print("=" * 60)
    print("TEST 19: Domain Manager")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_domains_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        domains_dir = root / "domains"
        calls: list[tuple[str, str]] = []

        def operator_executor(goal: str):
            calls.append(("operator", goal))
            return FakeOperatorOutcome()

        def software_executor(goal: str):
            calls.append(("software", goal))
            return FakeSoftwareOutcome()

        manager = DomainManager(
            memory=memory,
            domains_dir=domains_dir,
            operator_executor=operator_executor,
            software_executor=software_executor,
            include_legacy_unreal=True,
        )

        custom = BuiltinDomainPack(
            domain_id="cybersecurity",
            name="Cybersecurity Domain",
            description="Security analysis and hardening.",
            supported_tasks=["security audit"],
            capabilities=[
                DomainCapability("security", "Security review", ["security", "threat", "vulnerability"], [], 1.0)
            ],
            director="software",
        )
        manager.register(custom)
        assert "cybersecurity" in manager.domains
        assert manager.remove("cybersecurity")
        assert "cybersecurity" not in manager.domains
        print("  Register/remove domains: PASS")

        manifest_dir = domains_dir / "cad"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "domain.json").write_text(
            json.dumps(
                {
                    "domain_id": "cad",
                    "name": "CAD Domain",
                    "description": "CAD engineering workflows.",
                    "version": "1.0.0",
                    "director": "operator",
                    "capabilities": [
                        {
                            "name": "cad_modeling",
                            "description": "CAD model operations.",
                            "keywords": ["cad", "solidworks", "fusion"],
                            "applications": ["fusion"],
                        }
                    ],
                    "benchmarks": ["Open CAD project"],
                }
            ),
            encoding="utf-8",
        )
        manager.discover_domains()
        assert "cad" in manager.domains
        assert manager.domains["cad"].version == "1.0.0"
        print("  Dynamic discovery: PASS")

        unreal_route = manager.route("Create a Blueprint inventory system in Unreal.")
        assert unreal_route and unreal_route[0].domain_id == "unreal"
        blender_route = manager.route("Render an animation in Blender.")
        assert blender_route and blender_route[0].domain_id == "blender"
        assert manager.route("Create a Blueprint material graph in Unreal.")[0].confidence >= 0.5
        print("  Domain routing and conflict resolution: PASS")

        collaboration = manager.route("Build a multiplayer Unreal game and publish a release.")
        routed_ids = {route.domain_id for route in collaboration}
        assert {"unreal", "git", "networking", "documentation"} & routed_ids
        result = manager.execute("Build a multiplayer Unreal game and publish a release.")
        assert result.ok
        assert len(result.routes) >= 2
        assert calls
        print("  Multi-domain collaboration: PASS")

        unreal_memory = manager.domain_memory_path("unreal")
        git_memory = manager.domain_memory_path("git")
        assert unreal_memory.is_file()
        assert git_memory.is_file()
        assert unreal_memory.parent != git_memory.parent
        print("  Isolated domain memory: PASS")

        upgraded = BuiltinDomainPack(
            domain_id="cad",
            name="CAD Domain",
            description="Upgraded CAD workflows.",
            supported_tasks=["cad"],
            capabilities=[
                DomainCapability("cad_modeling", "CAD model operations.", ["cad", "fusion"], ["fusion"], 1.2)
            ],
            version="2.0.0",
        )
        manager.register(upgraded)
        assert manager.domains["cad"].version == "2.0.0"
        assert manager.load("cad")
        manager.unload_inactive(keep=set())
        assert "cad" not in manager.active_domains
        print("  Version upgrade and lifecycle: PASS")

        executor = ExecutionAgent()
        domain_agent = ExecutiveAgent(
            planner=PlannerAgent(LLMService()),
            executor=executor,
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(root),
            memory=memory,
            safety=SafetyLayer(),
            workspace_root=root,
            domain_manager=manager,
        )
        assert domain_agent.can_handle("Render an animation in Blender.")
        outcome = domain_agent.execute("Render an animation in Blender.")
        assert outcome.ok
        assert outcome.assumptions["domain_manager"] == "ATLAS"
        assert "blender" in outcome.assumptions["domains"]
        print("  ExecutiveAgent generic domain delegation: PASS")

        architect = ChiefArchitect(
            ROOT,
            memory,
            architecture=ArchitectureIntelligenceEngine(ROOT, memory),
            report_dir=root / "reports",
        )
        audit = architect.audit(force_refresh=True)
        assert audit.dashboard["domain_platform"]["domains_with_memory"] >= 2
        assert audit.dashboard["domain_platform"]["memory_isolated"]
        print("  ChiefArchitect domain health visibility: PASS")

    print("  TEST 19 PASS")


if __name__ == "__main__":
    main()
