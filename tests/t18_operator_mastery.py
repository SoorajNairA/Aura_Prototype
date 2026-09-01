"""TEST 18 - Q1 Computer Operator mastery reliability validation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.desktop.application_intelligence import ApplicationIntelligenceLayer  # noqa: E402
from aura.verification.adapters.architecture_analysis import ArchitectureIntelligenceEngine  # noqa: E402
from aura.legacy.assistant.chief_architect import ChiefArchitect  # noqa: E402
from aura.infrastructure.desktop.computer_operator import ComputerOperator, DesktopSnapshot, OperatorStep, WindowInfo  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.models import ActionRequest, ActionResult  # noqa: E402
from aura.legacy.assistant.operator_quality import BenchmarkTask, OperatorBenchmark, RecoveryLibrary, WorkflowAnalytics  # noqa: E402
from aura.safety.policies import SafetyLayer  # noqa: E402


ROOT = Path(__file__).parent.parent


class FakeExecutor:
    def __init__(self) -> None:
        self.requests: list[ActionRequest] = []

    def run(self, request: ActionRequest) -> ActionResult:
        self.requests.append(request)
        return ActionResult(
            action=request.action,
            ok=True,
            message="Opened.",
            output={"command": [request.args.get("app_name", "")]},
        )


class StateChangingPerception:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self) -> DesktopSnapshot:
        self.calls += 1
        title = "Unreal Editor - Loading Shaders" if self.calls == 1 else "Unreal Editor - Blueprint Complete"
        window = WindowInfo(
            title=title,
            process_name="unreal.exe",
            pid=77,
            foreground=True,
        )
        return DesktopSnapshot(
            timestamp="2026-07-04T00:00:00+00:00",
            foreground_window=window,
            windows=[window],
            processes=["unreal.exe"],
            cursor_position=(20, 20),
            monitors=1,
        )


class RecoverOnceVerification:
    def __init__(self) -> None:
        self.failed = False

    def verify(
        self,
        step: OperatorStep,
        before: DesktopSnapshot,
        after: DesktopSnapshot,
    ) -> tuple[bool, str]:
        if step.kind == "launch_app" and not self.failed:
            self.failed = True
            return False, "Window focus lost"
        return True, "Verified"


def main() -> None:
    print("=" * 60)
    print("TEST 18: Operator Mastery")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_operator_mastery_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        recovery_library = RecoveryLibrary(memory.memory_dir / "operator_recovery_library.json")
        analytics = WorkflowAnalytics(memory.memory_dir / "operator_analytics.json")
        operator = ComputerOperator(
            executor=FakeExecutor(),  # type: ignore[arg-type]
            memory=memory,
            safety=SafetyLayer(),
            perception=StateChangingPerception(),
            verification=RecoverOnceVerification(),
            application_intelligence=ApplicationIntelligenceLayer(memory.memory_dir / "application_profiles"),
            recovery_library=recovery_library,
            workflow_analytics=analytics,
        )

        plan = operator.plan("Create a Blueprint compile workflow in Unreal.")
        assert all(0.0 < step.confidence <= 1.0 for step in plan.steps)
        assert all(step.expected_state for step in plan.steps)
        print("  Step confidence model: PASS")

        outcome = operator.execute("Create a Blueprint compile workflow in Unreal.")
        assert outcome.ok
        assert outcome.recoveries
        assert analytics.summary()["success_rate"] == 1.0
        assert analytics.summary()["average_retries"] >= 1.0
        recovery_file = memory.memory_dir / "operator_recovery_library.json"
        assert recovery_file.is_file()
        assert "Window focus lost" in recovery_file.read_text(encoding="utf-8")
        print("  Recovery library and workflow analytics: PASS")

        workflow_file = memory.memory_dir / "operator_workflows.json"
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))[-1]
        assert "quality" in workflow
        assert "workspace_layout" in workflow["quality"]
        assert "optimization_opportunities" in workflow["quality"]
        print("  Reliability-enriched workflow memory: PASS")

        benchmark = OperatorBenchmark(memory.memory_dir / "operator_benchmarks.json")

        def fake_benchmark(task: BenchmarkTask):
            return True, 120.0, 0, 0, False, 0.92, f"{task.name} simulated"

        results = benchmark.run(fake_benchmark, tasks=[BenchmarkTask("Open Unreal", "Open Unreal", "unreal", "unreal")])
        assert results[0].success
        assert benchmark.summary()["success_rate"] == 1.0
        print("  OperatorBenchmark measurement: PASS")

        architect = ChiefArchitect(
            ROOT,
            memory,
            architecture=ArchitectureIntelligenceEngine(ROOT, memory),
            report_dir=root / "reports",
        )
        audit = architect.audit(force_refresh=True)
        assert audit.dashboard["operator_quality"]["analytics"]["success_rate"] == 1.0
        assert audit.dashboard["operator_quality"]["benchmark"]["success_rate"] == 1.0
        print("  ChiefArchitect reliability feedback: PASS")

    print("  TEST 18 PASS")


if __name__ == "__main__":
    main()
