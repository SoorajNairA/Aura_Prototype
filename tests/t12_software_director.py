"""TEST 12 - Phase 2 SoftwareDirector regression validation."""
from __future__ import annotations

import importlib.util
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.legacy.assistant.executive_agent import AssumptionEngine, ExecutiveAgent, ExecutionVerifier
from aura.legacy.assistant.llm import LLMService
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.planner import PlannerAgent
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer
from aura.legacy.assistant.software_director import SoftwareDirector


class RecordingRevealer(ResultRevealer):
    def __init__(self) -> None:
        super().__init__(enabled=True)
        self.projects: list[str] = []

    def reveal_project(self, path):
        self.projects.append(str(path))
        return True, "VS Code"


def _load_smoke(path: Path) -> None:
    spec = importlib.util.spec_from_file_location("generated_smoke", path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    module.test_core_service_creates_record()


def main() -> None:
    print("=" * 60)
    print("TEST 12: SoftwareDirector")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_director_") as temp:
        root = Path(temp)
        executor = ExecutionAgent()
        memory = MemoryStore(root / "memory")
        revealer = RecordingRevealer()
        director = SoftwareDirector(
            workspace_root=root,
            executor=executor,
            memory=memory,
            safety=SafetyLayer(),
            result_revealer=revealer,
        )

        assert director.can_handle("Build a hospital management system.")
        for phrase in (
            "Create an MMORPG backend.",
            "Develop a production-ready SaaS platform.",
            "Build a full-stack e-commerce application.",
            "Create an Unreal Engine plugin.",
            "Develop an AI desktop application.",
            "Continue yesterday's FarmSphere work.",
            "Add authentication to an existing project.",
            "Refactor the backend for scalability.",
            "Generate API documentation for the current project.",
        ):
            assert director.can_handle(phrase), phrase
        print("  PRD acceptance routing: PASS")

        outcome = director.execute("Build a hospital management system.")
        project_root = root / "Code" / "HospitalManagementSystem"
        assert outcome.ok
        assert outcome.blueprint.complexity_level == 3
        assert (project_root / "blueprint.json").is_file()
        assert (project_root / "docs" / "ARCHITECTURE.md").is_file()
        assert (project_root / "docs" / "API.md").is_file()
        assert (project_root / "src" / "hospitalmanagementsystem" / "api.py").is_file()
        assert (project_root / "frontend" / "src" / "App.tsx").is_file()
        assert "Authentication" in [m.name for m in outcome.blueprint.milestones]
        assert revealer.projects
        _load_smoke(project_root / "tests" / "test_smoke.py")
        print("  Hospital system: PASS")

        projects = memory.get_projects()
        assert "HospitalManagementSystem" in projects
        stored = projects["HospitalManagementSystem"]
        assert stored["blueprint"]["project_name"] == "HospitalManagementSystem"
        assert stored["pending_milestones"]
        print("  Persistent project memory: PASS")

        llm = LLMService()
        agent = ExecutiveAgent(
            planner=PlannerAgent(llm),
            executor=executor,
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(root),
            memory=memory,
            safety=SafetyLayer(),
            workspace_root=root,
            result_revealer=revealer,
        )
        assert agent.can_handle("Develop a production-ready SaaS platform.")
        routed = agent.execute("Develop a production-ready SaaS platform.")
        assert routed.ok
        assert "SaaSPlatform" in routed.message
        assert (root / "Code" / "SaaSPlatform" / "blueprint.json").is_file()
        print("  ExecutiveAgent delegation: PASS")

    print("  TEST 12 PASS")


if __name__ == "__main__":
    main()
