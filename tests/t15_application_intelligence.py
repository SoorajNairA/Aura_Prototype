"""TEST 15 - Phase 3A.1 universal application intelligence validation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.desktop.application_intelligence import ApplicationIntelligenceLayer  # noqa: E402
from aura.infrastructure.desktop.computer_operator import ComputerOperator, DesktopSnapshot, WindowInfo  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.models import ActionRequest, ActionResult  # noqa: E402
from aura.safety.policies import SafetyLayer  # noqa: E402


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


class UnknownAppPerception:
    def __init__(self, monitors: int = 1) -> None:
        self.monitors = monitors

    def observe(self) -> DesktopSnapshot:
        window = WindowInfo(
            title="Acme Studio - Graph Canvas Build Output",
            process_name="AcmeStudio.exe",
            pid=9001,
            foreground=True,
            rect=(0, 0, 1600, 900),
        )
        return DesktopSnapshot(
            timestamp="2026-07-04T00:00:00+00:00",
            foreground_window=window,
            windows=[window],
            processes=["AcmeStudio.exe"],
            cursor_position=(400, 300),
            monitors=self.monitors,
        )


def main() -> None:
    print("=" * 60)
    print("TEST 15: Universal Application Intelligence")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_app_intel_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        intelligence = ApplicationIntelligenceLayer(memory.memory_dir / "application_profiles")
        operator = ComputerOperator(
            executor=FakeExecutor(),  # type: ignore[arg-type]
            memory=memory,
            safety=SafetyLayer(),
            perception=UnknownAppPerception(),
            application_intelligence=intelligence,
        )

        assert operator.can_handle("Compile the graph using Acme Studio.")
        first = operator.execute("Compile the graph using Acme Studio.")
        assert first.ok
        assert first.plan.application == "acmestudio"
        assert "build" in first.plan.application_model["semantic_actions"]
        assert "node_graph" in first.plan.application_model["semantic_actions"]
        assert not first.plan.workflow_route["reused_memory"]
        print("  Unknown app discovery: PASS")

        profile_path = memory.memory_dir / "application_profiles" / "acmestudio.json"
        assert profile_path.is_file()
        profile = json.loads(profile_path.read_text(encoding="utf-8"))
        assert profile["application"] == "acmestudio"
        assert profile["workflows"]
        assert profile["interface_map"]["workspace"]["monitor_count"] == 1
        print("  Application profile learning: PASS")

        second_plan = operator.plan("Compile the graph using Acme Studio.")
        assert second_plan.workflow_route["reused_memory"]
        assert second_plan.confidence >= first.plan.confidence
        assert any(step.kind == "plan" for step in second_plan.steps)
        print("  Learned workflow reuse: PASS")

        changed_operator = ComputerOperator(
            executor=FakeExecutor(),  # type: ignore[arg-type]
            memory=memory,
            safety=SafetyLayer(),
            perception=UnknownAppPerception(monitors=2),
            application_intelligence=intelligence,
        )
        changed_plan = changed_operator.plan("Compile the graph using Acme Studio.")
        assert any("Monitor layout changed" in note for note in changed_plan.adaptation_notes)
        print("  Layout adaptation detection: PASS")

    print("  TEST 15 PASS")


if __name__ == "__main__":
    main()
