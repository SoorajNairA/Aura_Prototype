"""TEST 17 - Phase Omega ChiefArchitect audit validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.verification.adapters.architecture_analysis import ArchitectureIntelligenceEngine  # noqa: E402
from aura.legacy.assistant.chief_architect import ChiefArchitect  # noqa: E402
from aura.legacy.assistant.conversation_context import WorkingMemory  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.orchestrator import AuraSupervisor  # noqa: E402


ROOT = Path(__file__).parent.parent


def main() -> None:
    print("=" * 60)
    print("TEST 17: Chief Architect")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_architect_") as temp:
        temp_root = Path(temp)
        memory = MemoryStore(temp_root / "memory")
        reports = temp_root / "engineering_reports"
        architecture = ArchitectureIntelligenceEngine(ROOT, memory)
        architect = ChiefArchitect(ROOT, memory, architecture=architecture, report_dir=reports)

        audit = architect.audit(force_refresh=True)
        assert audit.overall_score > 0
        assert audit.subsystem_scores
        assert audit.modules
        assert audit.dependency_graph
        assert audit.dashboard["overall_engineering_score"] == audit.overall_score
        assert memory.get_projects()["ChiefArchitect"]["overall_engineering_score"] == audit.overall_score
        print("  Engineering score and dashboard: PASS")

        oversized = [module for module in audit.modules if module.lines > 900]
        assert oversized
        assert any(item.god_objects or "oversized module" in item.smells for item in audit.modules)
        print("  Oversized module and smell detection: PASS")

        assert isinstance(audit.duplicate_logic, list)
        assert isinstance(audit.circular_dependencies, list)
        assert isinstance(audit.dead_code_candidates, list)
        assert audit.performance_findings
        assert audit.security_findings
        assert audit.missing_tests
        print("  Debt analyzers: PASS")

        written = architect.generate_reports(audit)
        expected = {
            "ArchitectureAudit.md",
            "PerformanceAudit.md",
            "DependencyReport.md",
            "ComplexityReport.md",
            "SecurityAudit.md",
            "TestCoverageReport.md",
            "DeadCodeReport.md",
            "TechnicalDebt.md",
            "OptimizationRoadmap.md",
            "EngineeringScorecard.md",
        }
        assert expected == set(written)
        for path in written.values():
            assert path.is_file()
            assert path.read_text(encoding="utf-8").startswith("# ")
        assert "Overall" in (reports / "EngineeringScorecard.md").read_text(encoding="utf-8")
        assert "P" in (reports / "OptimizationRoadmap.md").read_text(encoding="utf-8")
        print("  Engineering report generation: PASS")

        review = architect.review_design("Add OCR provider to ComputerOperator desktop perception.")
        assert "tests/t14_computer_operator.py" in review["recommended_tests"]
        assert "tests/t15_application_intelligence.py" in review["recommended_tests"]
        assert review["architecture_score_before"] == audit.overall_score
        print("  Future design review: PASS")

        answer = architecture.answer("Run chief architect engineering audit.")
        assert "Engineering score" in answer.answer
        assert "Technical debt" in answer.answer
        print("  Architecture query hook: PASS")

        supervisor = AuraSupervisor.__new__(AuraSupervisor)
        supervisor.architecture = architecture
        supervisor.working_memory = WorkingMemory(max_turns=10)
        spoken: list[str] = []
        supervisor._speak = spoken.append
        assert supervisor.handle_spoken_text("What is the engineering score?", require_wake_word=False)
        assert spoken and "Engineering score" in spoken[-1]
        print("  Supervisor audit routing: PASS")

    print("  TEST 17 PASS")


if __name__ == "__main__":
    main()
