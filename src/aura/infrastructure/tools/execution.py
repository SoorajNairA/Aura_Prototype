from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse
from urllib.parse import unquote

from aura.legacy.assistant.models import ActionRequest, ActionResult
from aura.verification.adapters.research import ResearchAgent
from aura.safety.policies import SafetyLayer

_logger = logging.getLogger("aura")


ToolHandler = Callable[[dict[str, Any]], ActionResult]


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_schema: dict[str, str]
    required: tuple[str, ...]
    handler: ToolHandler


class ToolRegistry:
    """Safe registry for all executable AURA tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        name: str,
        description: str,
        arguments_schema: dict[str, str],
        required: tuple[str, ...],
        handler: ToolHandler,
    ) -> None:
        if not name.strip():
            raise ValueError("Tool name cannot be empty")
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            arguments_schema=arguments_schema,
            required=required,
            handler=handler,
        )

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "arguments_schema": tool.arguments_schema,
                # Legacy alias for older planner code.
                "args_schema": tool.arguments_schema,
                "required": list(tool.required),
            }
            for tool in self._tools.values()
        ]

    def execute(self, tool_call: dict[str, Any]) -> ActionResult:
        tool_name = str(tool_call.get("tool", "")).strip()
        arguments = tool_call.get("arguments", tool_call.get("args", {}))
        if not isinstance(arguments, dict):
            return ActionResult(
                action=tool_name or "unknown",
                ok=False,
                message="Tool arguments must be an object.",
            )
        arguments = dict(arguments)
        if tool_name == "open_app" and "app_name" not in arguments and "app" in arguments:
            arguments["app_name"] = arguments["app"]

        tool = self.get(tool_name)
        if tool is None:
            return ActionResult(
                action=tool_name or "unknown",
                ok=False,
                message=f"Unknown or unsafe tool: {tool_name or '(none)'}",
            )

        missing = [
            key for key in tool.required
            if key not in arguments or str(arguments.get(key, "")).strip() == ""
        ]
        if missing:
            return ActionResult(
                action=tool.name,
                ok=False,
                message=f"Missing required argument(s): {', '.join(missing)}",
            )

        t0 = time.perf_counter()
        try:
            result = tool.handler(arguments)
        except Exception as exc:
            result = ActionResult(
                action=tool.name,
                ok=False,
                message=f"Tool failed: {exc}",
            )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        _logger.info(
            "TOOL: %s ARGS: %s SUCCESS: %s TIME: %.0fms",
            tool.name,
            arguments,
            str(result.ok).lower(),
            elapsed_ms,
        )
        result.output.setdefault("tool", tool.name)
        result.output.setdefault("execution_time_ms", round(elapsed_ms, 1))
        return result


class ExecutionAgent:
    def __init__(
        self,
        research_agent: Optional[ResearchAgent] = None,
        max_research_results: int = 8,
        registry: Optional[ToolRegistry] = None,
        workspace_root: str | Path | None = None,
        approved_roots: tuple[str | Path, ...] = (),
        safety: Optional[SafetyLayer] = None,
    ) -> None:
        self.research_agent = research_agent or ResearchAgent()
        self.max_research_results = max_research_results
        self.registry = registry or ToolRegistry()
        self.workspace_root = Path(workspace_root or Path.cwd()).expanduser().resolve()
        self.approved_roots = tuple(Path(root).expanduser().resolve() for root in approved_roots)
        self.safety = safety or SafetyLayer()
        self._register_default_tools()

    def run(self, request: ActionRequest) -> ActionResult:
        action = request.action
        args = request.args

        if self.registry.get(action) is not None:
            return self.registry.execute({"tool": action, "arguments": args})

        # Keep research support for existing planner flows. It is intentionally
        # outside the minimal desktop tool demo and remains non-destructive.
        if action == "research_web":
            return self._research_web(args)

        if action == "respond_directly":
            message = str(args.get("message", "")).strip()
            if not message:
                return ActionResult(action=action, ok=False, message="No response content provided")
            return ActionResult(
                action=action,
                ok=True,
                message="Delivered direct response.",
                output={"spoken_response": message},
            )

        return ActionResult(action=action, ok=False, message=f"Unknown or unsafe tool: {action}")

    def tool_catalog(self) -> list[dict[str, Any]]:
        catalog = self.registry.catalog()
        catalog.extend(
            [
                {
                    "name": "research_web",
                    "description": "Collect and summarize web sources for a research objective",
                    "arguments_schema": {
                        "query": "string",
                        "required_terms": "string[]",
                        "max_results": "int",
                    },
                    "args_schema": {
                        "query": "string",
                        "required_terms": "string[]",
                        "max_results": "int",
                    },
                    "required": ["query"],
                },
                {
                    "name": "respond_directly",
                    "description": "Provide a direct spoken response when no tool should run",
                    "arguments_schema": {"message": "string"},
                    "args_schema": {"message": "string"},
                    "required": ["message"],
                },
            ]
        )
        return catalog

    def _register_default_tools(self) -> None:
        if self.registry.get("open_app") is None:
            self.registry.register(
                name="open_app",
                description="Open a supported desktop application",
                arguments_schema={"app_name": "string"},
                required=("app_name",),
                handler=self._open_app,
            )
        if self.registry.get("open_url") is None:
            self.registry.register(
                name="open_url",
                description="Open a website URL in the default browser",
                arguments_schema={"url": "string"},
                required=("url",),
                handler=self._open_url,
            )
        if self.registry.get("create_folder") is None:
            self.registry.register(
                name="create_folder",
                description="Create a folder recursively",
                arguments_schema={"path": "string"},
                required=("path",),
                handler=self._create_folder,
            )
        if self.registry.get("create_file") is None:
            self.registry.register(
                name="create_file",
                description="Create an empty file without overwriting by default",
                arguments_schema={"path": "string", "overwrite": "bool"},
                required=("path",),
                handler=self._create_file,
            )
        if self.registry.get("write_text_file") is None:
            self.registry.register(
                name="write_text_file",
                description="Write UTF-8 text to a file",
                arguments_schema={
                    "path": "string",
                    "content": "string",
                    "overwrite": "bool",
                },
                required=("path", "content"),
                handler=self._write_text_file,
            )

    def _open_app(self, arguments: dict[str, Any]) -> ActionResult:
        raw_name = str(arguments.get("app_name", arguments.get("app", ""))).strip()
        key = raw_name.lower().replace(" ", "")
        command = _resolve_app_command(key)
        if command is None:
            return ActionResult(
                action="open_app",
                ok=False,
                message=f"Unsupported app: {raw_name}.",
            )

        try:
            process: subprocess.Popen[Any] | None = None
            if command[0].lower() == "explorer.exe":
                os.startfile(str(Path.home()))  # type: ignore[attr-defined]
            else:
                process = subprocess.Popen(command, shell=False)
        except FileNotFoundError:
            if key in {"chrome", "googlechrome"}:
                fallback_url = "https://google.com"
                webbrowser.open(fallback_url)
                return ActionResult(
                    action="open_app",
                    ok=True,
                    message="Chrome is not installed, so I opened the default browser instead.",
                    output={
                        "command": command,
                        "app_name": "Default browser",
                        "fallback_used": True,
                        "fallback_reason": "chrome_not_found",
                        "url": fallback_url,
                    },
                )
            return ActionResult(
                action="open_app",
                ok=False,
                message=f"{raw_name} is not installed or not on PATH.",
            )

        display = _display_app_name(key, raw_name)
        return ActionResult(
            action="open_app",
            ok=True,
            message=f"{display} is open.",
            output={
                "command": command,
                "app_name": display,
                "pid": process.pid if process is not None else None,
            },
        )

    def _open_url(self, arguments: dict[str, Any]) -> ActionResult:
        url = _normalize_url(str(arguments.get("url", "")).strip())
        if not url:
            return ActionResult(action="open_url", ok=False, message="URL cannot be empty.")

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return ActionResult(action="open_url", ok=False, message="Only http and https URLs are allowed.")

        opened = bool(webbrowser.open(url))
        if not opened:
            return ActionResult(
                action="open_url",
                ok=False,
                message=f"The default browser did not accept {url}.",
                output={"url": url},
            )
        return ActionResult(action="open_url", ok=True, message=f"Opened {url}.", output={"url": url})

    def _create_folder(self, arguments: dict[str, Any]) -> ActionResult:
        path = Path(str(arguments.get("path", "")).strip()).expanduser()
        if not str(path):
            return ActionResult(action="create_folder", ok=False, message="Folder path cannot be empty.")
        decision_result = self._authorize_filesystem_mutation("create_folder", path, arguments)
        if decision_result is not None:
            return decision_result
        os.makedirs(path, exist_ok=True)
        return ActionResult(action="create_folder", ok=True, message=f"Created folder: {path}.")

    def _create_file(self, arguments: dict[str, Any]) -> ActionResult:
        path = Path(str(arguments.get("path", "")).strip()).expanduser()
        overwrite = _as_bool(arguments.get("overwrite", False))
        if path.exists() and not overwrite:
            return ActionResult(
                action="create_file",
                ok=True,
                message=f"File already exists: {path}.",
                output={"already_exists": True},
            )
        decision_result = self._authorize_filesystem_mutation("create_file", path, arguments)
        if decision_result is not None:
            return decision_result
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, "")
        return ActionResult(action="create_file", ok=True, message=f"Created file: {path}.")

    def _write_text_file(self, arguments: dict[str, Any]) -> ActionResult:
        path = Path(str(arguments.get("path", "")).strip()).expanduser()
        content = str(arguments.get("content", ""))
        overwrite = _as_bool(arguments.get("overwrite", False))
        decision_result = self._authorize_filesystem_mutation("write_text_file", path, arguments)
        if decision_result is not None:
            return decision_result
        if path.exists() and path.is_file() and path.stat().st_size > 0 and not overwrite:
            return ActionResult(
                action="write_text_file",
                ok=False,
                message=f"File already contains data and was not overwritten: {path}.",
                output={"overwrite_required": True, "path": str(path)},
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_text(path, content)
        return ActionResult(action="write_text_file", ok=True, message=f"Wrote file: {path}.")

    def _research_web(self, args: dict[str, Any]) -> ActionResult:
        try:
            query = str(args.get("query", "")).strip()
            required_terms = args.get("required_terms", [])
            if not isinstance(required_terms, list):
                required_terms = []
            max_results = int(args.get("max_results", self.max_research_results))

            rows = self.research_agent.research_web(
                query=query,
                required_terms=[str(t).strip() for t in required_terms if str(t).strip()],
                max_results=max_results,
            )
            if not rows:
                return ActionResult(
                    action="research_web",
                    ok=False,
                    message="No matching web results found. Try broadening constraints or changing query terms.",
                )

            report_path = Path("./workspace/research_report.txt")
            report_path.parent.mkdir(parents=True, exist_ok=True)
            lines = [f"Research query: {query or 'unspecified'}"]
            if required_terms:
                lines.append(f"Required terms: {', '.join(required_terms)}")
            lines.append("")
            for i, row in enumerate(rows, start=1):
                lines.append(f"{i}. {row['title']}")
                lines.append(f"   Source: {row['source']}")
                lines.append(f"   URL: {row['url']}")
                lines.append(f"   Snippet: {row['snippet']}")
                lines.append("")
            report_path.write_text("\n".join(lines), encoding="utf-8")

            return ActionResult(
                action="research_web",
                ok=True,
                message=f"Found {len(rows)} matching web results.",
                output={"results": rows, "report_path": str(report_path)},
            )
        except Exception as exc:
            return ActionResult(action="research_web", ok=False, message=f"Research failed: {exc}")

    def _authorize_filesystem_mutation(
        self,
        action: str,
        path: Path,
        arguments: dict[str, Any],
    ) -> ActionResult | None:
        decision = self.safety.assess_path(
            action,
            str(path),
            self.workspace_root,
            self.approved_roots,
        )
        arguments["path"] = str(decision.target)
        if decision.denied:
            return ActionResult(
                action=action,
                ok=False,
                message=f"Denied filesystem access: {decision.reason}",
                output={
                    "path": str(decision.target),
                    "policy_decision": decision.decision,
                    "policy_reason": decision.reason,
                },
            )
        if decision.requires_confirmation and not self._has_required_filesystem_approval(action, arguments, decision.reason):
            return ActionResult(
                action=action,
                ok=False,
                message=f"Confirmation required for filesystem access: {decision.reason}",
                output={
                    "path": str(decision.target),
                    "confirmation_required": True,
                    "policy_decision": decision.decision,
                    "policy_reason": decision.reason,
                },
            )
        return None

    def _has_required_filesystem_approval(
        self,
        action: str,
        arguments: dict[str, Any],
        reason: str,
    ) -> bool:
        if "outside approved workspace" in reason:
            return _as_bool(arguments.get("allow_external_write", False))
        if action in {"create_file", "write_text_file"} and "existing" in reason.lower():
            return _as_bool(arguments.get("overwrite", False))
        return _as_bool(arguments.get("allow_external_write", False))


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return ""
    shortcuts = {
        "youtube": "https://youtube.com",
        "yt": "https://youtube.com",
        "google": "https://google.com",
        "gmail": "https://mail.google.com",
        "github": "https://github.com",
    }
    key = url.lower().strip()
    if key in shortcuts:
        return shortcuts[key]
    stripped = url.strip()
    decoded = unquote(stripped).strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in decoded):
        return ""
    parsed_decoded = urlparse(decoded)
    if parsed_decoded.scheme and parsed_decoded.scheme.lower() not in {"http", "https"}:
        return ""
    parsed = urlparse(stripped)
    if parsed.scheme and parsed.scheme.lower() not in {"http", "https"}:
        return ""
    normalized = stripped if parsed.scheme else "https://" + stripped
    final = urlparse(normalized)
    if final.scheme.lower() not in {"http", "https"} or not final.netloc:
        return ""
    if any(char.isspace() for char in final.netloc):
        return ""
    return normalized


def _resolve_app_command(key: str) -> list[str] | None:
    aliases: dict[str, list[str]] = {
        "chrome": ["chrome.exe", "chrome"],
        "googlechrome": ["chrome.exe", "chrome"],
        "edge": ["msedge.exe", "msedge"],
        "microsoftedge": ["msedge.exe", "msedge"],
        "firefox": ["firefox.exe", "firefox"],
        "vscode": ["Code.exe", "code.cmd", "code.exe", "code"],
        "visualstudiocode": ["Code.exe", "code.cmd", "code.exe", "code"],
        "notepad": ["notepad.exe"],
        "calculator": ["calc.exe"],
        "calc": ["calc.exe"],
        "explorer": ["explorer.exe"],
        "fileexplorer": ["explorer.exe"],
    }
    candidates = aliases.get(key)
    if candidates is None:
        return None

    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return [found]

    for candidate in _known_windows_app_paths(key):
        if candidate.exists():
            return [str(candidate)]

    # Windows system apps often resolve without appearing on PATH in the
    # Python environment. Let CreateProcess try the executable alias.
    if candidates:
        return [candidates[0]]
    return None


def _known_windows_app_paths(key: str) -> list[Path]:
    env = os.environ
    program_files = Path(env.get("ProgramFiles", r"C:\Program Files"))
    program_files_x86 = Path(env.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    local_app_data = Path(env.get("LOCALAPPDATA", ""))

    paths: dict[str, list[Path]] = {
        "chrome": [
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "googlechrome": [
            program_files / "Google" / "Chrome" / "Application" / "chrome.exe",
            program_files_x86 / "Google" / "Chrome" / "Application" / "chrome.exe",
            local_app_data / "Google" / "Chrome" / "Application" / "chrome.exe",
        ],
        "edge": [
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
        "microsoftedge": [
            program_files / "Microsoft" / "Edge" / "Application" / "msedge.exe",
            program_files_x86 / "Microsoft" / "Edge" / "Application" / "msedge.exe",
        ],
        "firefox": [
            program_files / "Mozilla Firefox" / "firefox.exe",
            program_files_x86 / "Mozilla Firefox" / "firefox.exe",
        ],
        "vscode": [
            local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe",
            program_files / "Microsoft VS Code" / "Code.exe",
        ],
        "visualstudiocode": [
            local_app_data / "Programs" / "Microsoft VS Code" / "Code.exe",
            program_files / "Microsoft VS Code" / "Code.exe",
        ],
    }
    return [path for path in paths.get(key, []) if str(path)]


def _display_app_name(key: str, fallback: str) -> str:
    names = {
        "chrome": "Chrome",
        "googlechrome": "Chrome",
        "edge": "Edge",
        "microsoftedge": "Edge",
        "firefox": "Firefox",
        "vscode": "VS Code",
        "visualstudiocode": "VS Code",
        "notepad": "Notepad",
        "calculator": "Calculator",
        "calc": "Calculator",
        "explorer": "Explorer",
        "fileexplorer": "Explorer",
    }
    return names.get(key, fallback)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "overwrite"}


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    try:
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)
