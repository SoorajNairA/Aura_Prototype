"""TEST 13 - Phase 2B Software lifecycle evolution validation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.infrastructure.persistence.memory_store import MemoryStore
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


def main() -> None:
    print("=" * 60)
    print("TEST 13: Software Lifecycle")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_lifecycle_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        director = SoftwareDirector(
            workspace_root=root,
            executor=ExecutionAgent(),
            memory=memory,
            safety=SafetyLayer(),
            result_revealer=RecordingRevealer(),
        )

        created = director.execute("Build a hospital management system.")
        project_root = root / "Code" / "HospitalManagementSystem"
        assert created.ok
        original_blueprint_mtime = (project_root / "blueprint.json").stat().st_mtime_ns
        assert (project_root / "DependencyGraph.json").is_file()
        assert (project_root / "docs" / "ProjectHealth.md").is_file()
        assert (project_root / "docs" / "VerificationReport.md").is_file()
        print("  Initial lifecycle reports: PASS")

        resumed = director.execute("Resume Hospital System.")
        assert resumed.ok
        assert resumed.blueprint.project_name == "HospitalManagementSystem"
        assert (project_root / "docs" / "MilestoneReport.md").is_file()
        assert (project_root / "blueprint.json").stat().st_mtime_ns >= original_blueprint_mtime
        assert not (root / "Code" / "ResumeHospitalSystem").exists()
        print("  Resume without regeneration: PASS")

        auth = director.execute("Add authentication to Hospital System.")
        assert auth.ok
        assert (project_root / "src" / "hospitalmanagementsystem" / "auth.py").is_file()
        assert (project_root / "tests" / "test_auth.py").is_file()
        blueprint = json.loads((project_root / "EngineeringBlueprint.json").read_text(encoding="utf-8"))
        assert "authentication" in blueprint["technologies"]
        print("  Scoped authentication evolution: PASS")

        database = director.execute("Replace database with PostgreSQL for Hospital System.")
        assert database.ok
        assert (project_root / "src" / "hospitalmanagementsystem" / "repository_postgres.py").is_file()
        blueprint = json.loads((project_root / "EngineeringBlueprint.json").read_text(encoding="utf-8"))
        assert blueprint["technologies"]["database"] == "PostgreSQL"
        print("  Database replacement evolution: PASS")

        pipeline = director.execute("Generate deployment pipeline for Hospital System.")
        assert pipeline.ok
        assert (project_root / ".github" / "workflows" / "ci.yml").is_file()
        print("  Deployment pipeline evolution: PASS")

        docs = director.execute("Generate API documentation for Hospital System.")
        assert docs.ok
        assert "POST /auth/login" in (project_root / "docs" / "API.md").read_text(encoding="utf-8")
        print("  Documentation synchronization: PASS")

        projects = memory.get_projects()
        stored = projects["HospitalManagementSystem"]
        assert stored["build_status"] == "Healthy"
        assert stored["project_health"]["verification_status"] == "passed"
        assert len(stored["development_history"]) >= 4
        assert stored["dependency_graph"]["files"]["api"]
        assert stored["verification_history"]
        print("  Persistent lifecycle memory: PASS")

    print("  TEST 13 PASS")


if __name__ == "__main__":
    main()
