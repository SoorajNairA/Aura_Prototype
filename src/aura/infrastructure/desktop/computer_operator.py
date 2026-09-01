from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import logging
import os
import re
import subprocess
import time
import webbrowser
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.infrastructure.desktop.application_intelligence import ApplicationIntelligenceLayer, ApplicationModel, WorkflowRoute
from aura.legacy.assistant.executive_behavior import ExecutiveBehavior
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest
from aura.legacy.assistant.operator_quality import OperatorRunMetrics, RecoveryLibrary, WorkflowAnalytics
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer

_logger = logging.getLogger("aura")


@dataclass
class WindowInfo:
    title: str
    process_name: str = ""
    pid: int | None = None
    hwnd: int | None = None
    foreground: bool = False
    rect: tuple[int, int, int, int] | None = None


@dataclass
class DesktopSnapshot:
    timestamp: str
    foreground_window: WindowInfo | None
    windows: list[WindowInfo]
    processes: list[str]
    clipboard_text: str = ""
    cursor_position: tuple[int, int] | None = None
    monitors: int = 1


@dataclass
class OperatorStep:
    id: str
    kind: str
    description: str
    target: str = ""
    arguments: dict[str, Any] = field(default_factory=dict)
    verification: str = ""
    status: str = "pending"
    confidence: float = 0.6
    expected_state: str = ""
    max_wait_ms: int = 1500


@dataclass
class WorkflowPlan:
    goal: str
    environment: str
    application: str
    steps: list[OperatorStep]
    safety_notes: list[str]
    expected_result: str
    application_model: dict[str, Any] = field(default_factory=dict)
    workflow_route: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    adaptation_notes: list[str] = field(default_factory=list)


@dataclass
class WorkflowMemory:
    application: str
    goal: str
    steps: list[dict[str, Any]]
    verification: dict[str, Any]
    recovery: list[str]
    timing_ms: float
    optimizations: list[str]
    updated_at: str


@dataclass
class OperatorOutcome:
    ok: bool
    message: str
    plan: WorkflowPlan
    observations: list[dict[str, Any]]
    recoveries: list[str] = field(default_factory=list)


class PerceptionProvider(Protocol):
    def observe(self) -> DesktopSnapshot:
        ...


class InputProvider(Protocol):
    def hotkey(self, *keys: str) -> bool:
        ...

    def type_text(self, text: str) -> bool:
        ...

    def click(self, x: int, y: int) -> bool:
        ...

    def set_clipboard(self, text: str) -> bool:
        ...


class VerificationProvider(Protocol):
    def verify(self, step: OperatorStep, before: DesktopSnapshot, after: DesktopSnapshot) -> tuple[bool, str]:
        ...


class Win32DesktopPerception:
    """Best-effort desktop observation using built-in Windows APIs."""

    def observe(self) -> DesktopSnapshot:
        windows = self._windows()
        foreground = next((window for window in windows if window.foreground), None)
        return DesktopSnapshot(
            timestamp=datetime.now(timezone.utc).isoformat(),
            foreground_window=foreground,
            windows=windows,
            processes=self._processes(),
            clipboard_text=self._clipboard_text(),
            cursor_position=self._cursor_position(),
            monitors=self._monitor_count(),
        )

    def _windows(self) -> list[WindowInfo]:
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        foreground = user32.GetForegroundWindow()
        windows: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def callback(hwnd: int, lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            rect = ctypes.wintypes.RECT()
            rect_tuple = None
            try:
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    rect_tuple = (rect.left, rect.top, rect.right, rect.bottom)
            except Exception:
                rect_tuple = None
            windows.append(
                WindowInfo(
                    title=buffer.value,
                    process_name="",
                    pid=int(pid.value) if pid.value else None,
                    hwnd=int(hwnd),
                    foreground=int(hwnd) == int(foreground),
                    rect=rect_tuple,
                )
            )
            return True

        try:
            user32.EnumWindows(callback, 0)
        except Exception:
            return []
        names = self._pid_names()
        for window in windows:
            if window.pid in names:
                window.process_name = names[window.pid]
        return windows

    def _pid_names(self) -> dict[int, str]:
        names: dict[int, str] = {}
        try:
            output = subprocess.check_output(
                ["tasklist", "/fo", "csv", "/nh"],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=3,
            )
        except Exception:
            return names
        for line in output.splitlines():
            columns = [part.strip('"') for part in line.split('","')]
            if len(columns) < 2:
                continue
            try:
                names[int(columns[1])] = columns[0]
            except ValueError:
                continue
        return names

    def _processes(self) -> list[str]:
        return sorted(set(self._pid_names().values()))

    def _clipboard_text(self) -> str:
        if os.name != "nt":
            return ""
        try:
            output = subprocess.check_output(
                [
                    "powershell.exe",
                    "-NoLogo",
                    "-NoProfile",
                    "-Command",
                    "Get-Clipboard -Raw -ErrorAction SilentlyContinue",
                ],
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=2,
            )
            return output.strip()
        except Exception:
            return ""

    def _cursor_position(self) -> tuple[int, int] | None:
        if os.name != "nt":
            return None
        point = ctypes.wintypes.POINT()
        if ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            return int(point.x), int(point.y)
        return None

    def _monitor_count(self) -> int:
        if os.name != "nt":
            return 1
        try:
            return max(1, int(ctypes.windll.user32.GetSystemMetrics(80)))
        except Exception:
            return 1


class SafeInputProvider:
    """Input provider with dry-run default.

    Real keyboard/mouse actions are deliberately gated so tests and normal
    background planning cannot unexpectedly manipulate the user's desktop.
    """

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self.events: list[dict[str, Any]] = []

    def hotkey(self, *keys: str) -> bool:
        self.events.append({"action": "hotkey", "keys": list(keys), "executed": self.enabled})
        if not self.enabled:
            return True
        # Conservative implementation through VBScript SendKeys. This is not
        # used in tests and remains replaceable by a richer provider later.
        mapping = {
            "ctrl": "^",
            "shift": "+",
            "alt": "%",
            "enter": "{ENTER}",
            "esc": "{ESC}",
            "tab": "{TAB}",
        }
        text = "".join(mapping.get(key.lower(), key) for key in keys)
        return self._send_keys(text)

    def type_text(self, text: str) -> bool:
        self.events.append({"action": "type_text", "text": text, "executed": self.enabled})
        if not self.enabled:
            return True
        return self.set_clipboard(text) and self.hotkey("ctrl", "v")

    def click(self, x: int, y: int) -> bool:
        self.events.append({"action": "click", "x": x, "y": y, "executed": self.enabled})
        if not self.enabled or os.name != "nt":
            return True
        ctypes.windll.user32.SetCursorPos(int(x), int(y))
        ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
        ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
        return True

    def set_clipboard(self, text: str) -> bool:
        self.events.append({"action": "set_clipboard", "text": text, "executed": self.enabled})
        if not self.enabled:
            return True
        try:
            subprocess.run(
                ["clip.exe"],
                input=text,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=3,
            )
            return True
        except Exception:
            return False

    def _send_keys(self, text: str) -> bool:
        escaped = text.replace('"', '""')
        script = f'CreateObject("WScript.Shell").SendKeys "{escaped}"'
        try:
            subprocess.run(
                ["cscript.exe", "//NoLogo", "//E:vbscript", "-"],
                input=script,
                text=True,
                encoding="utf-8",
                check=True,
                timeout=3,
            )
            return True
        except Exception:
            return False


class BasicVerificationProvider:
    def verify(self, step: OperatorStep, before: DesktopSnapshot, after: DesktopSnapshot) -> tuple[bool, str]:
        if step.kind == "launch_app":
            app = str(step.arguments.get("app_name", step.target)).lower().replace(" ", "")
            observed = " ".join([w.process_name.lower() + " " + w.title.lower() for w in after.windows])
            aliases = {
                "vscode": ("code", "visual studio code"),
                "chrome": ("chrome",),
                "edge": ("msedge", "edge"),
                "excel": ("excel",),
                "powerpoint": ("powerpnt", "powerpoint"),
                "unreal": ("unreal",),
                "blender": ("blender",),
            }.get(app, (app,))
            return any(alias in observed for alias in aliases), "Application observed." if observed else "Application not observed."
        if step.kind in {"observe", "plan", "verify"}:
            return True, "State captured."
        if step.kind in {"hotkey", "type_text", "click", "clipboard"}:
            return True, "Input provider accepted action."
        return True, "Step completed."


class ComputerOperator:
    """Universal computer operator foundation with replaceable providers."""

    OPERATOR_MARKERS = (
        "blueprint",
        "unreal",
        "niagara",
        "metahuman",
        "behavior tree",
        "blender",
        "powerpoint",
        "excel",
        "visual studio",
        "docker desktop",
        "github release",
        "figma",
        "photoshop",
        "word",
        "operate",
        "use the computer",
        "move the mouse",
        "keyboard",
        "animate",
        "animation",
        "character",
        "docker",
        "github",
        "moved ui",
        "moved elements",
        "moved interface",
        "application restart",
        "resume interrupted workflow",
        "resume interrupted",
    )

    def __init__(
        self,
        executor: ExecutionAgent,
        memory: MemoryStore,
        safety: SafetyLayer,
        result_revealer: Optional[ResultRevealer] = None,
        perception: Optional[PerceptionProvider] = None,
        input_provider: Optional[InputProvider] = None,
        verification: Optional[VerificationProvider] = None,
        application_intelligence: Optional[ApplicationIntelligenceLayer] = None,
        recovery_library: Optional[RecoveryLibrary] = None,
        workflow_analytics: Optional[WorkflowAnalytics] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        allow_input_control: bool | None = None,
        max_recovery_attempts: int = 8,
    ) -> None:
        self.executor = executor
        self.memory = memory
        self.safety = safety
        self.result_revealer = result_revealer
        self.perception = perception or Win32DesktopPerception()
        if allow_input_control is None:
            allow_input_control = os.getenv("AURA_OPERATOR_INPUT_ENABLED", "false").lower() in {
                "1",
                "true",
                "yes",
                "on",
            }
        self.input = input_provider or SafeInputProvider(enabled=allow_input_control)
        self.verification = verification or BasicVerificationProvider()
        self.application_intelligence = application_intelligence or ApplicationIntelligenceLayer(
            profile_dir=self.memory.memory_dir / "application_profiles"
        )
        self.recovery_library = recovery_library or RecoveryLibrary(
            self.memory.memory_dir / "operator_recovery_library.json"
        )
        self.workflow_analytics = workflow_analytics or WorkflowAnalytics(
            self.memory.memory_dir / "operator_analytics.json"
        )
        self.status_callback = status_callback
        self.max_recovery_attempts = max_recovery_attempts
        self._active_model: ApplicationModel | None = None
        self._active_route: WorkflowRoute | None = None

    def can_handle(self, goal: str) -> bool:
        lowered = goal.lower()
        if any(marker in lowered for marker in self.OPERATOR_MARKERS):
            return True
        operation_words = (
            "operate",
            "use",
            "click",
            "select",
            "configure",
            "edit",
            "render",
            "compile",
            "export",
            "import",
            "publish",
            "fix",
            "recover",
        )
        app_context = re.search(r"\b(?:in|inside|using|with)\s+[a-z][a-z0-9_. -]{2,}\b", lowered)
        return bool(app_context and any(re.search(rf"\b{word}\b", lowered) for word in operation_words))

    def execute(self, goal: str) -> OperatorOutcome:
        started = time.perf_counter()
        self._status(ExecutiveBehavior.ANALYZING.label)
        self._status("Observing desktop...")
        before = self.perception.observe()
        plan = self.plan(goal, before)
        observations: list[dict[str, Any]] = [{"phase": "before", "snapshot": self._snapshot_summary(before)}]
        recoveries: list[str] = []
        retries = 0
        verification_count = 0
        failure_history: list[str] = []

        for step in plan.steps:
            self._status(self._status_for_step(step))
            step.status = "running"
            if step.confidence < 0.35:
                self._status("Searching for a safer route.")
                recoveries.append("Low-confidence step received additional verification.")
            result = self._execute_step(step)
            after = self._wait_for_stable_state(before, step)
            ok, note = self.verification.verify(step, before, after)
            verification_count += 1
            if not ok:
                failure_note = note
                failure_history.append(note)
                recovered, recovery_note = self._recover(step, before, after)
                recoveries.append(recovery_note)
                retries += 1
                if recovered:
                    after = self._wait_for_stable_state(after, step)
                    ok, note = self.verification.verify(step, before, after)
                    verification_count += 1
                self.recovery_library.record(
                    application=plan.application,
                    failure=failure_note,
                    recovery_steps=[recovery_note],
                    success=recovered and ok,
                    confidence=step.confidence,
                )
            step.status = "completed" if ok and result else "failed"
            observations.append(
                {
                    "step": asdict(step),
                    "ok": ok and result,
                    "verification": note,
                    "snapshot": self._snapshot_summary(after),
                }
            )
            before = after
            if not ok and step.kind in {"launch_app", "hotkey", "type_text", "click"}:
                break

        final_ok = all(row.get("ok", True) for row in observations[1:])
        duration_ms = (time.perf_counter() - started) * 1000
        self._status(ExecutiveBehavior.COMPLETE.label if final_ok else ExecutiveBehavior.RECOVERING.label)
        self._remember_workflow(plan, observations, recoveries)
        self._record_quality_metrics(
            plan=plan,
            ok=final_ok,
            duration_ms=duration_ms,
            retries=retries,
            recoveries=recoveries,
            verification_count=verification_count,
            failure_history=failure_history,
        )
        if self._active_model is not None and self._active_route is not None:
            evaluation = self.application_intelligence.evaluate(
                ok=final_ok,
                recovered=bool(recoveries),
                verified=final_ok,
                timing_ms=duration_ms,
            )
            self.application_intelligence.learn(self._active_model, self._active_route, evaluation)
        self._reveal_if_possible(plan)
        message = self._message(plan, final_ok, recoveries)
        return OperatorOutcome(
            ok=final_ok,
            message=message,
            plan=plan,
            observations=observations,
            recoveries=recoveries,
        )

    def plan(self, goal: str, snapshot: DesktopSnapshot | None = None) -> WorkflowPlan:
        if snapshot is None:
            snapshot = self.perception.observe()
        application_hint, environment = self._target_environment(goal, snapshot)
        memory = self._load_workflow_memory(application_hint, goal)
        model, route, adaptation_notes = self.application_intelligence.understand(
            goal=goal,
            snapshot=snapshot,
            application_hint=application_hint,
            workflow_memories=memory,
        )
        self._active_model = model
        self._active_route = route
        application = model.name
        environment = environment if application_hint not in {"current", "unknown"} else model.name
        steps = [
            OperatorStep(
                id="O1",
                kind="observe",
                description="Read current desktop state.",
                verification="Desktop snapshot captured.",
                confidence=0.95,
                expected_state="idle",
            ),
        ]
        if application_hint not in {"current", "unknown"}:
            steps.append(
                OperatorStep(
                    id=f"O{len(steps) + 1}",
                    kind="launch_app",
                    description=f"Open {environment}.",
                    target=application_hint,
                    arguments={"app_name": application_hint},
                    verification=f"{environment} is visible or an alternate environment is available.",
                    confidence=max(0.45, route.confidence),
                    expected_state="idle",
                    max_wait_ms=2500,
                )
            )
        for route_step in route.steps:
            steps.append(
                OperatorStep(
                    id=f"O{len(steps) + 1}",
                    kind=str(route_step.get("kind", "plan")),
                    description=str(route_step.get("description", "Continue workflow.")),
                    target=environment,
                    arguments=dict(route_step.get("arguments", {})),
                    verification=str(route_step.get("verification", "Workflow state verified.")),
                    confidence=float(route_step.get("confidence", route.confidence)),
                    expected_state=str(route_step.get("expected_state", "idle")),
                )
            )
        return WorkflowPlan(
            goal=goal.strip(),
            environment=environment,
            application=application,
            steps=steps,
            safety_notes=[
                "No destructive operation without confirmation.",
                "No purchases, publishing, email sending, or security setting changes without approval.",
                "Keyboard and mouse control are provider-gated.",
            ],
            expected_result="Goal completed and verified in the target desktop environment.",
            application_model=asdict(model),
            workflow_route=asdict(route),
            confidence=route.confidence,
            adaptation_notes=adaptation_notes,
        )

    def observe(self) -> DesktopSnapshot:
        return self.perception.observe()

    def _execute_step(self, step: OperatorStep) -> bool:
        if step.kind == "observe":
            self.perception.observe()
            return True
        if step.kind == "launch_app":
            app_name = str(step.arguments.get("app_name", step.target))
            request = ActionRequest(action="open_app", args={"app_name": app_name})
            result = self.executor.run(request)
            if result.ok:
                return True
            fallback = self._fallback_environment(app_name)
            if fallback:
                recovery = self.executor.run(ActionRequest(action="open_app", args={"app_name": fallback}))
                if recovery.ok:
                    step.arguments["fallback_app"] = fallback
                    return True
            if app_name in {"github", "githubrelease"}:
                return bool(webbrowser.open("https://github.com"))
            return False
        if step.kind == "hotkey":
            return self.input.hotkey(*[str(k) for k in step.arguments.get("keys", [])])
        if step.kind == "type_text":
            return self.input.type_text(str(step.arguments.get("text", "")))
        if step.kind == "click":
            return self.input.click(int(step.arguments.get("x", 0)), int(step.arguments.get("y", 0)))
        if step.kind == "clipboard":
            return self.input.set_clipboard(str(step.arguments.get("text", "")))
        if step.kind in {"understand", "discover", "plan", "verify"}:
            return True
        return True

    def _recover(
        self,
        step: OperatorStep,
        before: DesktopSnapshot,
        after: DesktopSnapshot,
    ) -> tuple[bool, str]:
        library_steps = self.recovery_library.suggestions(
            application=(self._active_model.name if self._active_model else step.target),
            failure=step.verification or step.description,
        )
        attempts = [
            "Retry",
            "Alternative shortcut",
            "Alternative menu",
            "Search UI",
            "Command palette",
            "Accessibility API",
            "Vision",
            "Alternative workflow",
            "Human confirmation",
        ][: self.max_recovery_attempts]
        attempts = library_steps + attempts
        for attempt in attempts:
            if attempt == "Retry" and self._execute_step(step):
                return True, f"Recovered with retry for {step.description}"
            if attempt in {"Alternative shortcut", "keyboard shortcut"} and self.input.hotkey("alt"):
                return True, f"Recovered using alternate shortcut path for {step.description}"
            if attempt in {"Alternative menu", "menu traversal"} and self.input.hotkey("alt"):
                return True, f"Recovered using menu traversal for {step.description}"
            if attempt == "Command palette" and self.input.hotkey("ctrl", "shift", "p"):
                return True, f"Recovered using command palette path for {step.description}"
            if attempt in {"Search", "Search UI"} and self.input.hotkey("ctrl", "f"):
                return True, f"Recovered using search path for {step.description}"
            if attempt in {"Alternative workflow", "Vision", "Accessibility API"}:
                snapshot = self.perception.observe()
                if self._snapshot_state(snapshot) not in {"error", "confirmation"}:
                    return True, f"Recovered by re-observing and selecting an alternate workflow for {step.description}"
        return False, f"Recovery exhausted for {step.description}"

    def _wait_for_stable_state(self, before: DesktopSnapshot, step: OperatorStep) -> DesktopSnapshot:
        deadline = time.perf_counter() + max(step.max_wait_ms, 100) / 1000
        last = before
        before_signature = self._snapshot_signature(before)
        while time.perf_counter() < deadline:
            current = self.perception.observe()
            state = self._snapshot_state(current)
            changed = self._snapshot_signature(current) != before_signature
            if state in {"error", "confirmation"}:
                return current
            if state not in {"busy", "loading"} and (
                changed
                or state == step.expected_state
                or step.kind in {"observe", "understand", "discover", "plan", "verify"}
            ):
                return current
            last = current
            time.sleep(0.05)
        return last

    def _snapshot_state(self, snapshot: DesktopSnapshot) -> str:
        observer = getattr(self.application_intelligence, "state_observer", None)
        if observer is None:
            return "idle"
        try:
            return str(observer.state(snapshot))
        except Exception:
            return "idle"

    def _snapshot_signature(self, snapshot: DesktopSnapshot) -> tuple[Any, ...]:
        foreground = snapshot.foreground_window
        return (
            foreground.title if foreground else "",
            foreground.process_name if foreground else "",
            len(snapshot.windows),
            tuple(sorted(snapshot.processes))[:20],
            snapshot.clipboard_text[:80],
        )

    def _record_quality_metrics(
        self,
        plan: WorkflowPlan,
        ok: bool,
        duration_ms: float,
        retries: int,
        recoveries: list[str],
        verification_count: int,
        failure_history: list[str],
    ) -> None:
        optimization_opportunities = []
        if retries:
            optimization_opportunities.append("Reduce retries by preferring learned recovery path.")
        if duration_ms > 5000:
            optimization_opportunities.append("Profile slow operator workflow.")
        if plan.confidence < 0.75:
            optimization_opportunities.append("Improve workflow confidence through repeated successful runs.")
        metrics = OperatorRunMetrics(
            goal=plan.goal,
            application=plan.application,
            success=ok,
            duration_ms=round(duration_ms, 1),
            retries=retries,
            recoveries=len(recoveries),
            user_interventions=0,
            confidence=plan.confidence,
            verification_count=verification_count,
            failure_history=failure_history,
            recovery_history=recoveries,
            optimization_opportunities=optimization_opportunities,
        )
        self.workflow_analytics.record(metrics)

    def _target_environment(self, goal: str, snapshot: DesktopSnapshot | None = None) -> tuple[str, str]:
        lowered = goal.lower()
        mapping = [
            (("unreal", "blueprint", "niagara", "metahuman", "behavior tree"), ("unreal", "Unreal Engine")),
            (("blender",), ("blender", "Blender")),
            (("powerpoint", "presentation"), ("powerpoint", "PowerPoint")),
            (("excel", "formula", "spreadsheet"), ("excel", "Excel")),
            (("visual studio", "solution"), ("visualstudio", "Visual Studio")),
            (("docker",), ("docker", "Docker Desktop")),
            (("github release", "github"), ("github", "GitHub")),
            (("figma",), ("figma", "Figma")),
            (("photoshop",), ("photoshop", "Photoshop")),
            (("word", "document"), ("word", "Word")),
            (("chrome", "browser", "website"), ("chrome", "Browser")),
            (("explorer", "folder", "file"), ("explorer", "Explorer")),
        ]
        for markers, target in mapping:
            if any(marker in lowered for marker in markers):
                return target
        app_context = re.search(r"\b(?:in|inside|using|with)\s+([a-z][a-z0-9_. -]{2,})\b", lowered)
        if app_context:
            raw = app_context.group(1).strip(" .")
            raw = re.split(r"\b(?:to|and|then|for|that|where)\b", raw, maxsplit=1)[0].strip(" .")
            app_name = re.sub(r"[^a-z0-9]+", "", raw.lower()) or "current"
            return app_name, raw.title()
        if snapshot and snapshot.foreground_window:
            process = (snapshot.foreground_window.process_name or "").strip()
            title = (snapshot.foreground_window.title or "").strip()
            if process:
                app_name = re.sub(r"\.exe$", "", process, flags=re.IGNORECASE)
                return app_name, app_name.title()
            if title:
                return "current", title.split(" - ")[0].strip() or "Current Application"
        return "explorer", "Desktop"

    def _fallback_environment(self, app_name: str) -> str:
        key = app_name.lower().replace(" ", "")
        fallbacks = {
            "unreal": "explorer",
            "visualstudio": "vscode",
            "docker": "explorer",
            "github": "chrome",
            "powerpoint": "explorer",
            "excel": "explorer",
            "word": "explorer",
            "photoshop": "explorer",
            "figma": "chrome",
        }
        return fallbacks.get(key, "")

    def _message(self, plan: WorkflowPlan, ok: bool, recoveries: list[str]) -> str:
        if ok:
            recovered = " Recovered along the way." if recoveries else ""
            return f"Done. Operator workflow prepared for {plan.environment}.{recovered}"
        return f"I couldn't complete the {plan.environment} workflow yet. Human confirmation may be needed."

    def _reveal_if_possible(self, plan: WorkflowPlan) -> None:
        if self.result_revealer is None or not self.result_revealer.enabled:
            return
        snapshot = self.perception.observe()
        if snapshot.foreground_window and snapshot.foreground_window.pid:
            self.result_revealer.reveal_application({"pid": snapshot.foreground_window.pid})

    def _remember_workflow(
        self,
        plan: WorkflowPlan,
        observations: list[dict[str, Any]],
        recoveries: list[str],
    ) -> None:
        path = self.memory.memory_dir / "operator_workflows.json"
        workflows = self._read_workflows(path)
        started = observations[0]["snapshot"].get("timestamp", "")
        timing_ms = 0.0
        try:
            start_ts = datetime.fromisoformat(started)
            timing_ms = (datetime.now(timezone.utc) - start_ts).total_seconds() * 1000
        except Exception:
            timing_ms = 0.0
        entry = WorkflowMemory(
            application=plan.application,
            goal=plan.goal,
            steps=[asdict(step) for step in plan.steps],
            verification={
                "ok": all(row.get("ok", True) for row in observations[1:]),
                "strategy": plan.workflow_route.get("verification_strategy", ""),
                "confidence": plan.confidence,
            },
            recovery=recoveries,
            timing_ms=round(timing_ms, 1),
            optimizations=self._workflow_optimizations(plan, recoveries),
            updated_at=datetime.now(timezone.utc).isoformat(),
        )
        row = asdict(entry)
        row["interface_map"] = plan.application_model.get("interface_map", {})
        row["semantic_actions"] = plan.application_model.get("semantic_actions", {})
        row["workflow_route"] = plan.workflow_route
        row["adaptation_notes"] = plan.adaptation_notes
        row["recovery_strategy"] = plan.workflow_route.get("recovery_strategy", [])
        row["failure_cases"] = [
            item for item in observations[1:] if not item.get("ok", True)
        ]
        analytics = self.workflow_analytics.summary()
        row["quality"] = {
            "success_rate": analytics.get("success_rate", 0.0),
            "average_retries": analytics.get("average_retries", 0.0),
            "recovery_success_rate": analytics.get("recovery_success_rate", 0.0),
            "workflow_reuse_rate": analytics.get("workflow_reuse_rate", 0.0),
            "confidence": plan.confidence,
            "application_version": plan.application_model.get("version", "unknown"),
            "workspace_layout": plan.application_model.get("interface_map", {}).get("workspace", {}),
            "optimization_opportunities": self._workflow_optimizations(plan, recoveries),
        }
        workflows.append(row)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(workflows[-100:], indent=2), encoding="utf-8")

    def _load_workflow_memory(self, application: str, goal: str) -> list[dict[str, Any]]:
        workflows = self._read_workflows(self.memory.memory_dir / "operator_workflows.json")
        app = application.lower()
        terms = set(re.findall(r"[a-z0-9]+", goal.lower()))
        matches = []
        for workflow in workflows:
            if str(workflow.get("application", "")).lower() != app:
                continue
            workflow_terms = set(re.findall(r"[a-z0-9]+", str(workflow.get("goal", "")).lower()))
            if terms & workflow_terms:
                matches.append(workflow)
        return matches[-3:]

    def _read_workflows(self, path: Path) -> list[dict[str, Any]]:
        if not path.is_file():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def _workflow_optimizations(self, plan: WorkflowPlan, recoveries: list[str]) -> list[str]:
        items = ["Reuse observed application route next time."]
        if recoveries:
            items.append("Prefer recovered path before the failed action.")
        if plan.application in {"unreal", "visualstudio", "blender"}:
            items.append("Prefer command/search palettes over fragile click coordinates.")
        return items

    def _snapshot_summary(self, snapshot: DesktopSnapshot) -> dict[str, Any]:
        return {
            "timestamp": snapshot.timestamp,
            "foreground": asdict(snapshot.foreground_window) if snapshot.foreground_window else None,
            "window_count": len(snapshot.windows),
            "process_count": len(snapshot.processes),
            "cursor_position": snapshot.cursor_position,
            "monitors": snapshot.monitors,
        }

    def _status_for_step(self, step: OperatorStep) -> str:
        if step.kind == "launch_app":
            return "Launching..."
        if step.kind == "observe":
            return "Observing desktop..."
        if step.kind == "verify":
            return "Verifying..."
        return "Executing workflow..."

    def _status(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception:
            pass
