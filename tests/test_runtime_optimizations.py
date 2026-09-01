from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.infrastructure.llm.ollama import OllamaConversationModel
from aura.legacy.assistant.executive_agent import (
    AssumptionEngine,
    ExecutiveAgent,
    ExecutionVerifier,
)
from aura.legacy.assistant.llm import LLMService
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest
from aura.legacy.assistant.orchestrator import _extract_wake_request, _is_shutdown_command
from aura.safety.policies import SafetyLayer
from aura.infrastructure.voice.xtts_backend import XTTSBackend


def test_context_does_not_duplicate_current_request() -> None:
    context = SimpleNamespace(
        recent_messages=[{"role": "user", "content": "Explain caching"}],
        to_context_block=lambda: "User mood hint: stressed.",
    )
    messages = LLMService()._build_messages(
        "Explain caching",
        context,
        "",
        "",
    )
    occurrences = sum(
        str(message.get("content", "")).count("Explain caching")
        for message in messages
    )
    assert occurrences == 1


def test_existing_text_requires_explicit_overwrite() -> None:
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "important.txt"
        path.write_text("KEEP", encoding="utf-8")
        executor = ExecutionAgent(workspace_root=Path(temp))

        rejected = executor.run(
            ActionRequest(
                action="write_text_file",
                args={"path": str(path), "content": "REPLACED"},
            )
        )
        assert not rejected.ok
        assert path.read_text(encoding="utf-8") == "KEEP"

        accepted = executor.run(
            ActionRequest(
                action="write_text_file",
                args={
                    "path": str(path),
                    "content": "REPLACED",
                    "overwrite": True,
                },
            )
        )
        assert accepted.ok
        assert path.read_text(encoding="utf-8") == "REPLACED"


def test_conversation_phrases_do_not_trigger_project_generation() -> None:
    agent = object.__new__(ExecutiveAgent)
    assert not agent.can_handle("I need advice about the opposite approach")
    assert not agent.can_handle("Could you explain this application error?")
    assert not agent.can_handle("I want to discuss AI safety")
    assert agent.can_handle("I need a portfolio website")
    assert agent.can_handle("Build an AI assistant")


def test_executive_execution_does_not_call_planner_model() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        planner = SimpleNamespace(
            create_plan=lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("planner should not be called")
            )
        )
        agent = ExecutiveAgent(
            planner=planner,
            executor=ExecutionAgent(),
            verifier=ExecutionVerifier(),
            assumption_engine=AssumptionEngine(root),
            memory=MemoryStore(root / "memory"),
            safety=SafetyLayer(),
            workspace_root=root,
        )
        outcome = agent.execute("build calculator app")
        assert outcome.ok


def test_url_open_failure_is_reported() -> None:
    with patch("aura.infrastructure.tools.execution.webbrowser.open", return_value=False):
        result = ExecutionAgent().run(
            ActionRequest(
                action="open_url",
                args={"url": "https://example.com"},
            )
        )
    assert not result.ok


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JaVaScRiPt:alert(1)",
        " data:text/plain,hello",
        "file:///C:/Windows/win.ini",
        "vbscript:msgbox(1)",
        "powershell:Start-Process calc",
        "%6aavascript:alert(1)",
        "java\nscript:alert(1)",
    ],
)
def test_dangerous_url_schemes_are_rejected(url: str) -> None:
    result = ExecutionAgent().run(ActionRequest(action="open_url", args={"url": url}))
    assert not result.ok


def test_filesystem_scope_policy_allows_workspace_and_guards_boundaries() -> None:
    root = Path.cwd().resolve()
    local_path = root / "workspace" / "aegis_scope_probe" / "allowed.txt"
    local_path.unlink(missing_ok=True)
    allowed = ExecutionAgent(workspace_root=root).run(
        ActionRequest(
            action="write_text_file",
            args={"path": str(local_path), "content": "inside"},
        )
    )
    assert allowed.ok
    assert local_path.read_text(encoding="utf-8") == "inside"

    external_path = root.parent / "aegis_external_probe.txt"
    guarded = ExecutionAgent(workspace_root=root).run(
        ActionRequest(
            action="write_text_file",
            args={"path": str(external_path), "content": "outside"},
        )
    )
    assert not guarded.ok
    assert guarded.output.get("confirmation_required") is True
    assert not external_path.exists()

    traversal = ExecutionAgent(workspace_root=root).run(
        ActionRequest(
            action="write_text_file",
            args={"path": str(root / ".." / "aegis_traversal_probe.txt"), "content": "escape"},
        )
    )
    assert not traversal.ok
    assert traversal.output.get("policy_decision") == "deny"


def test_symlink_escape_is_denied_when_supported() -> None:
    root = Path.cwd().resolve()
    link_dir = root / "workspace" / "aegis_symlink_probe"
    target_dir = root.parent
    link_dir.parent.mkdir(parents=True, exist_ok=True)
    if link_dir.exists() or link_dir.is_symlink():
        if link_dir.is_symlink():
            link_dir.unlink()
        else:
            pytest.skip("Symlink probe path already exists as a real directory.")
    try:
        link_dir.symlink_to(target_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"Symlink creation unavailable on this system: {exc}")
    try:
        result = ExecutionAgent(workspace_root=root).run(
            ActionRequest(
                action="write_text_file",
                args={"path": str(link_dir / "aegis_symlink_escape.txt"), "content": "escape"},
            )
        )
        assert not result.ok
        assert result.output.get("policy_decision") == "deny"
    finally:
        link_dir.unlink(missing_ok=True)


def test_xtts_pipeline_generates_ahead_of_playback() -> None:
    backend = XTTSBackend(device="cpu")
    second_generated = threading.Event()
    generated: list[str] = []
    played: list[str] = []

    def fake_generate(text: str) -> Path:
        generated.append(text)
        if text == "second":
            second_generated.set()
        return Path(tempfile.gettempdir()) / f"{text}.wav"

    def fake_play(path: Path) -> None:
        if path.stem == "first":
            assert second_generated.wait(timeout=1)
        played.append(path.stem)

    backend.speak_to_file = fake_generate  # type: ignore[method-assign]
    backend._play_audio_file = fake_play  # type: ignore[method-assign]
    try:
        spoken = backend.speak_pipelined(iter(("first", "second")))
    finally:
        backend.shutdown()

    assert generated == ["first", "second"]
    assert played == ["first", "second"]
    assert spoken == ["first", "second"]


def test_discussion_classification_uses_no_model_call() -> None:
    model = OllamaConversationModel(model="qwen2.5:3b")
    model.generate = lambda *args, **kwargs: (_ for _ in ()).throw(
        AssertionError("classifier model should not run")
    )
    result = LLMService(conv_model=model).classify_interaction(
        "Let's discuss game ideas."
    )
    assert result["interaction_type"] == "discussion"
    assert result["classification_method"] == "heuristic"


def test_shutdown_and_wake_word_matching_are_exact() -> None:
    assert _is_shutdown_command("shutdown aura")
    assert not _is_shutdown_command("Explain an exit strategy")
    assert _extract_wake_request("Aura open Chrome", "aura") == "open Chrome"
    assert _extract_wake_request("auratic sound", "aura") is None


def test_capability_question_uses_enabled_tools_without_model_call() -> None:
    service = LLMService()
    service.set_available_tools(
        [
            {"name": "open_app"},
            {"name": "open_url"},
            {"name": "create_file"},
        ]
    )
    reply = service.fast_path_reply("What can you do?")
    assert reply is not None
    assert "open applications" in reply
    assert "open websites" in reply
    assert "create files" in reply
    assert "create folders" not in reply
