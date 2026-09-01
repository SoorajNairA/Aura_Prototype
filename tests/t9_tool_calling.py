"""TEST 9 - Minimal tool calling validation.

Safe checks only:
- verifies command-to-tool selection for app/url/file commands
- executes folder and file tools in workspace/tool_call_check
- verifies unknown/destructive tools are rejected
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.legacy.assistant.llm import LLMService
from aura.legacy.assistant.models import ActionRequest


def main() -> None:
    base = Path("workspace/tool_call_check")
    shutil.rmtree(base, ignore_errors=True)

    executor = ExecutionAgent()
    llm = LLMService()
    catalog = executor.tool_catalog()

    selection_cases = [
        ("Open Chrome", "open_app", {"app_name": "chrome"}),
        ("Can you open not pad?", "open_app", {"app_name": "notepad"}),
        ("Please run calculator.", "open_app", {"app_name": "calculator"}),
        ("Open YouTube", "open_url", {"url": "https://youtube.com"}),
        ("Go to GitHub?", "open_url", {"url": "https://github.com"}),
        ("Create a folder named workspace/tool_call_check", "create_folder", {"path": "workspace/tool_call_check"}),
        ("Create a file named workspace/tool_call_check/notes.txt", "create_file", {"path": "workspace/tool_call_check/notes.txt"}),
        ("Write 'Hello World' into workspace/tool_call_check/notes.txt", "write_text_file", {"path": "workspace/tool_call_check/notes.txt", "content": "Hello World"}),
    ]

    print("=" * 60)
    print("TEST 9: Tool Calling")
    print("=" * 60)

    for user_text, expected_tool, expected_arguments in selection_cases:
        classification = llm.classify_interaction(user_text)
        assert classification["interaction_type"] == "direct_system_command"
        selected = llm.direct_command_to_action(user_text, catalog)
        print(f"  {user_text!r} -> {selected['tool']} {selected['arguments']}")
        assert selected["tool"] == expected_tool
        for key, value in expected_arguments.items():
            assert selected["arguments"][key] == value

    for user_text, _, _ in selection_cases[-3:]:
        selected = llm.direct_command_to_action(user_text, catalog)
        result = executor.run(ActionRequest(action=selected["tool"], args=selected["arguments"]))
        print(f"  EXEC {selected['tool']}: ok={result.ok} message={result.message!r}")
        assert result.ok

    assert base.is_dir()
    assert (base / "notes.txt").read_text(encoding="utf-8") == "Hello World"

    unknown = executor.run(ActionRequest(action="delete_path", args={"path": "workspace/tool_call_check/notes.txt"}))
    print(f"  UNSAFE delete_path rejected: ok={unknown.ok} message={unknown.message!r}")
    assert not unknown.ok

    print("  TEST 9 PASS")


if __name__ == "__main__":
    main()
