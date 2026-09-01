"""TEST 14 - Phase 3A autonomous computer operator validation."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.desktop.computer_operator import (  # noqa: E402
    ComputerOperator,
    DesktopSnapshot,
    OperatorStep,
    WindowInfo,
)
from aura.legacy.assistant.executive_agent import AssumptionEngine, ExecutiveAgent, ExecutionVerifier  # noqa: E402
from aura.legacy.assistant.llm import LLMService  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.models import ActionRequest, ActionResult  # noqa: E402
from aura.legacy.assistant.planner import PlannerAgent  # noqa: E402
from aura.safety.policies import SafetyLayer  # noqa: E402


class FakeExecutor:
    def __init__(self) -> None:
        self.requests: list[ActionRequest] = []

    def run(self, request: ActionRequest) -> ActionResult:
        self.requests.append(request)
        return ActionResult(
            action=request.action,
            ok=True,
            message=f"Opened {request.args.get('app_name', '')}.",
            output={"command": [request.args.get("app_name", "")]},
        )


class FakePerception:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self) -> DesktopSnapshot:
        self.calls += 1
        window = WindowInfo(
            title="Unreal Editor - TestProject",
            process_name="unreal.exe",
            pid=4242,
            foreground=True,
        )
        return DesktopSnapshot(
            timestamp="2026-07-04T00:00:00+00:00",
            foreground_window=window,
            windows=[window],
            processes=["unreal.exe", "explorer.exe"],
            clipboard_text="",
            cursor_position=(10, 10),
            monitors=1,
        )


class FakeVerification:
    def __init__(self) -> None:
        self.fail_once = True

    def verify(
        self,
        step: OperatorStep,
        before: DesktopSnapshot,
        after: DesktopSnapshot,
    ) -> tuple[bool, str]:
        if step.kind == "launch_app" and self.fail_once:
            self.fail_once = False
            return False, "Window not ready yet."
        return True, "Verified."


class FakeInput:
    def __init__(self) -> None:
        self.events: list[tuple[str, tuple[str, ...]]] = []

    def hotkey(self, *keys: str) -> bool:
        self.events.append(("hotkey", tuple(keys)))
        return True

    def type_text(self, text: str) -> bool:
        self.events.append(("type_text", (text,)))
        return True

    def click(self, x: int, y: int) -> bool:
        self.events.append(("click", (str(x), str(y))))
        return True

    def set_clipboard(self, text: str) -> bool:
        self.events.append(("clipboard", (text,)))
        return True


def main() -> None:
    print("=" * 60)
    print("TEST 14: Computer Operator")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_operator_") as temp:
        root = Path(temp)
        memory = MemoryStore(root / "memory")
        executor = FakeExecutor()
        input_provider = FakeInput()
        operator = ComputerOperator(
            executor=executor,  # type: ignore[arg-type]
            memory=memory,
            safety=SafetyLayer(),
            perception=FakePerception(),
            input_provider=input_provider,
            verification=FakeVerification(),
            allow_input_control=False,
        )

        positive_goals = [
            "Create a Blueprint inventory system in Unreal.",
            "Build an AI behavior tree.",
            "Create a Niagara effect.",
            "Configure a MetaHuman.",
            "Animate a character in Blender.",
            "Generate a PowerPoint presentation.",
            "Edit Excel formulas.",
            "Refactor a Visual Studio solution.",
            "Configure Docker.",
            "Publish a GitHub release.",
            "Recover from moved UI elements.",
            "Continue after application restart.",
            "Resume interrupted workflows.",
        ]
        for goal in positive_goals:
            assert operator.can_handle(goal), goal
        assert not operator.can_handle("Build a calculator app.")
        print("  Goal detection coverage: PASS")

        plan = operator.plan("Create a Blueprint inventory system in Unreal.")
        assert plan.application == "unreal"
        assert plan.environment == "Unreal Engine"
        assert [step.kind for step in plan.steps] == ["observe", "launch_app", "understand", "discover", "verify"]
        assert "node_graph" in plan.application_model["semantic_actions"]
        assert plan.workflow_route["confidence"] > 0.5
        assert plan.safety_notes
        print("  Provider-ready planning: PASS")

        outcome = operator.execute("Create a Blueprint inventory system in Unreal.")
        assert outcome.ok
        assert outcome.recoveries
        assert executor.requests and executor.requests[0].args["app_name"] == "unreal"
        workflow_file = root / "memory" / "operator_workflows.json"
        assert workflow_file.is_file()
        workflows = json.loads(workflow_file.read_text(encoding="utf-8"))
        assert workflows[-1]["application"] == "unreal"
        assert workflows[-1]["recovery"]
        assert workflows[-1]["interface_map"]
        assert workflows[-1]["semantic_actions"]
        assert workflows[-1]["workflow_route"]["recovery_strategy"]
        print("  Execution, recovery, and workflow memory: PASS")

        agent = ExecutiveAgent(
            planner=PlannerAgent(LLMService()),
            executor=executor,  # type: ignore[arg-type]
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(root),
            memory=memory,
            safety=SafetyLayer(),
            workspace_root=root,
            computer_operator=operator,
        )
        assert agent.can_handle("Create a Niagara effect.")
        routed = agent.execute("Create a Niagara effect.")
        assert routed.ok
        assert routed.assumptions.get("domain_manager") == "ATLAS"
        assert "unreal" in routed.assumptions.get("domains", "")
        assert any(action["action"] == "launch_app" for action in routed.actions)
        print("  ExecutiveAgent routing: PASS")

    print("  TEST 14 PASS")


if __name__ == "__main__":
    main()
