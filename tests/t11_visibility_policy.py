"""TEST 11 - Result visibility policy without launching host GUI apps."""
from __future__ import annotations

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


class RecordingRevealer(ResultRevealer):
    def __init__(self) -> None:
        super().__init__(enabled=True)
        self.calls: list[tuple[str, str]] = []

    def reveal_file(self, path):
        self.calls.append(("file", str(path)))
        return True

    def reveal_folder(self, path, select=None):
        self.calls.append(("folder", str(path)))
        return True

    def reveal_application(self, process):
        self.calls.append(("application", str(process)))
        return True

    def reveal_url(self, url, open_url=False):
        self.calls.append(("url", str(url)))
        return True

    def reveal_project(self, path):
        self.calls.append(("project", str(path)))
        return True, "VS Code"


def main() -> None:
    print("=" * 60)
    print("TEST 11: Visibility Policy")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_visibility_") as temp:
        root = Path(temp)
        revealer = RecordingRevealer()
        llm = LLMService()
        executor = ExecutionAgent()
        agent = ExecutiveAgent(
            planner=PlannerAgent(llm),
            executor=executor,
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(root),
            memory=MemoryStore(root / "memory"),
            safety=SafetyLayer(),
            workspace_root=root,
            result_revealer=revealer,
        )

        project_cases = [
            ("Make a simple python game", "PythonGame"),
            ("Build me a weather app", "WeatherApp"),
            ("Create a snake game", "SnakeGame"),
            ("Make a portfolio website", "PortfolioWebsite"),
            ("Create a Discord bot", "DiscordBot"),
            ("Generate AI notes", "AINotes"),
            ("Build a todo app", "TodoApp"),
            ("Create a calculator app", "CalculatorApp"),
            ("Make a Flask website", "FlaskWebsite"),
            ("Build an AI assistant", "LocalAIAssistant"),
        ]
        for goal, project_name in project_cases:
            assert agent.can_handle(goal), goal
            outcome = agent.execute(goal)
            project_path = root / "Code" / project_name
            assert outcome.ok, goal
            assert project_path.is_dir(), goal
            assert outcome.artifacts, goal
            assert revealer.calls[-1] == ("project", str(project_path)), goal
            assert "opened it in VS Code" in outcome.message, goal
        print(f"  Project reveal: PASS ({len(project_cases)} goal forms)")

        assert (root / "Code" / "PythonGame" / "assets").is_dir()
        assert "pygame" in (
            root / "Code" / "PythonGame" / "requirements.txt"
        ).read_text(encoding="utf-8")
        assert (root / "Code" / "PortfolioWebsite" / "index.html").is_file()
        assert (root / "Code" / "DiscordBot" / ".env.example").is_file()
        print("  Project defaults: PASS")

        email = agent.execute("generate sponsor email")
        assert email.ok
        assert revealer.calls[-1] == ("file", str(root / "workspace" / "sponsor_email.txt"))
        assert "Saved and opened sponsor_email.txt" in email.message
        print("  Generated document reveal: PASS")

        real_revealer = ResultRevealer(enabled=True)
        unsafe = root / "dangerous.cmd"
        unsafe.write_text("echo no", encoding="utf-8")
        assert not real_revealer.reveal_file(unsafe)
        print("  Unsafe file blocked: PASS")

        disabled = ResultRevealer(enabled=False)
        safe = root / "notes.txt"
        safe.write_text("hello", encoding="utf-8")
        assert not disabled.reveal_file(safe)
        print("  Configuration disable: PASS")

    print("  TEST 11 PASS")


if __name__ == "__main__":
    main()
