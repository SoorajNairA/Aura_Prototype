"""TEST 16 - Phase 3A.2 self architecture intelligence validation."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.verification.adapters.architecture_analysis import ArchitectureIntelligenceEngine  # noqa: E402
from aura.legacy.assistant.conversation_context import WorkingMemory  # noqa: E402
from aura.infrastructure.persistence.memory_store import MemoryStore  # noqa: E402
from aura.legacy.assistant.orchestrator import AuraSupervisor  # noqa: E402


ROOT = Path(__file__).parent.parent


def main() -> None:
    print("=" * 60)
    print("TEST 16: Architecture Intelligence")
    print("=" * 60)

    with tempfile.TemporaryDirectory(prefix="aura_arch_") as temp:
        memory = MemoryStore(Path(temp) / "memory")
        engine = ArchitectureIntelligenceEngine(ROOT, memory)
        graph = engine.graph(force_refresh=True)

        assert graph.nodes
        assert any("computer_operator" in node.id for node in graph.nodes.values())
        assert any("software_director" in node.id for node in graph.nodes.values())
        assert graph.health["node_count"] >= 20
        assert (memory.memory_dir / "architecture_graph.json").is_file()
        print("  Persistent graph index: PASS")

        ocr = engine.answer("Where should OCR integration be implemented?")
        assert "Application Intelligence" in ocr.answer
        assert "Computer Operator" in ocr.answer
        print("  Responsibility reasoning: PASS")

        desktop = engine.answer("What modules participate in desktop automation?")
        assert "computer_operator" in desktop.answer
        assert "actions" in desktop.answer
        assert "result_revealer" in desktop.answer
        print("  Architecture search reasoning: PASS")

        flow = engine.answer("Show the execution flow for voice commands.")
        assert "AudioIO" in flow.answer
        assert "STTService" in flow.answer
        assert "TTSService" in flow.answer
        print("  Execution flow understanding: PASS")

        impact = engine.answer("What depends on ToolRegistry?")
        assert "tests/t9_tool_calling.py" in impact.answer
        assert "jarvis_acceptance" in impact.answer
        assert impact.confidence >= 0.8
        print("  Dependency impact analysis: PASS")

        tests = engine.answer("What tests should be updated after changing ComputerOperator?")
        assert "tests/t14_computer_operator.py" in tests.answer
        assert "tests/t15_application_intelligence.py" in tests.answer
        print("  Test ownership reasoning: PASS")

        diagram = engine.answer("Generate the architecture diagram.")
        assert "flowchart TD" in diagram.diagram
        assert "ComputerOperator" in diagram.diagram
        assert "ApplicationIntelligence" in diagram.diagram
        print("  Diagram generation: PASS")

        software = engine.answer("Explain the SoftwareDirector.")
        assert "blueprints" in software.answer.lower()
        assert "verifies" in software.answer.lower()
        print("  Component explainability: PASS")

        unused = engine.answer("Identify unused modules.")
        assert unused.answer
        assert unused.confidence > 0.5
        print("  System health awareness: PASS")

        bridge = engine.answer("Explain how Executive Agent communicates with ComputerOperator.")
        assert "delegates" in bridge.answer.lower()
        assert "ComputerOperator.execute" in bridge.answer
        print("  Relationship graph reasoning: PASS")

        verification = engine.answer("Locate the verification pipeline.")
        assert "ExecutionVerifier" in verification.answer
        assert "VerificationProvider" in verification.answer
        print("  Verification pipeline location: PASS")

        supervisor = AuraSupervisor.__new__(AuraSupervisor)
        supervisor.architecture = engine
        supervisor.working_memory = WorkingMemory(max_turns=10)
        spoken: list[str] = []
        supervisor._speak = spoken.append
        assert supervisor.handle_spoken_text(
            "Where should OCR integration be implemented?",
            require_wake_word=False,
        )
        assert spoken and "Application Intelligence" in spoken[-1]
        print("  Supervisor architecture routing: PASS")

    print("  TEST 16 PASS")


if __name__ == "__main__":
    main()
