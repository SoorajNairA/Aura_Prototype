"""TEST 10 - Hierarchical ExecutiveAgent regression validation."""
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
from aura.safety.policies import SafetyLayer
from aura.legacy.assistant.conversation_context import ConversationState, WorkingMemory
from aura.legacy.assistant.orchestrator import AuraSupervisor


def build_agent(root: Path) -> ExecutiveAgent:
    llm = LLMService()
    executor = ExecutionAgent()
    return ExecutiveAgent(
        planner=PlannerAgent(llm),
        executor=executor,
        verifier=ExecutionVerifier(),
        assumption_engine=AssumptionEngine(root),
        memory=MemoryStore(root / "memory"),
        safety=SafetyLayer(),
        workspace_root=root,
    )


def main() -> None:
    print("=" * 60)
    print("TEST 10: ExecutiveAgent")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_executive_") as temp:
        root = Path(temp)
        agent = build_agent(root)

        assert not agent.can_handle("hello")
        assert not agent.can_handle("how are you")
        assert agent.can_handle("build calculator app")
        assert agent.can_handle("create a Python calculator")
        assert agent.can_handle("Make a Python Calculator")
        assert agent.can_handle("create Flask website")
        assert agent.can_handle("generate sponsor email")

        calculator = agent.execute("build calculator app")
        calculator_root = root / "Code" / "CalculatorApp"
        assert calculator.ok
        assert (calculator_root / "main.py").is_file()
        assert (calculator_root / "requirements.txt").is_file()
        assert (calculator_root / "README.md").is_file()
        assert all(row["verified"] for row in calculator.actions)
        print(f"  Calculator: PASS ({len(calculator.artifacts)} artifacts)")

        website = agent.execute("create Flask website")
        website_root = root / "Code" / "FlaskWebsite"
        assert website.ok
        assert (website_root / "app.py").is_file()
        assert (website_root / "templates" / "index.html").is_file()
        assert (website_root / "static" / "styles.css").is_file()
        assert "Flask" in (website_root / "requirements.txt").read_text(encoding="utf-8")
        print(f"  Flask website: PASS ({len(website.artifacts)} artifacts)")

        email = agent.execute("generate sponsor email")
        email_path = root / "workspace" / "sponsor_email.txt"
        assert email.ok
        assert email_path.is_file()
        assert "Sponsorship Opportunity" in email_path.read_text(encoding="utf-8")
        print(f"  Sponsor email: PASS ({len(email.artifacts)} artifacts)")

        projects = agent.memory.get_projects()
        assert "CalculatorApp" in projects
        assert "FlaskWebsite" in projects
        assert "SponsorEmail" in projects
        assert agent.memory.read_recent_logs(limit=1)
        print("  Memory integration: PASS")

        supervisor = AuraSupervisor.__new__(AuraSupervisor)
        supervisor.executive = agent
        supervisor.executor = agent.executor
        supervisor.llm = agent.planner.llm
        supervisor.memory = agent.memory
        supervisor.safety = agent.safety
        supervisor.working_memory = WorkingMemory(max_turns=30)
        supervisor.conversation_state = ConversationState.IDLE
        spoken: list[str] = []
        supervisor._speak = spoken.append

        def classification_must_not_run(*args, **kwargs):
            raise AssertionError("Executive goal reached conversation classifier")

        supervisor.llm.classify_interaction = classification_must_not_run
        assert supervisor.handle_spoken_text(
            "Make a Python Calculator named FreshCalculator",
            require_wake_word=False,
        )
        assert spoken and spoken[-1].startswith("Done. Created FreshCalculator")
        print("  Orchestrator routing: PASS")

    print("  TEST 10 PASS")


if __name__ == "__main__":
    main()
