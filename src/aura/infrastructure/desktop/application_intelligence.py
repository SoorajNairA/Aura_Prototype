from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Protocol


@dataclass
class UIElement:
    kind: str
    label: str
    role: str = ""
    confidence: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class InterfaceMap:
    application_name: str
    version: str = "unknown"
    windows: list[dict[str, Any]] = field(default_factory=list)
    panels: list[UIElement] = field(default_factory=list)
    menus: list[UIElement] = field(default_factory=list)
    toolbars: list[UIElement] = field(default_factory=list)
    dialogs: list[UIElement] = field(default_factory=list)
    search_surfaces: list[UIElement] = field(default_factory=list)
    command_surfaces: list[UIElement] = field(default_factory=list)
    status_surfaces: list[UIElement] = field(default_factory=list)
    workspace: dict[str, Any] = field(default_factory=dict)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ApplicationModel:
    name: str
    version: str = "unknown"
    process: str = ""
    windows: list[dict[str, Any]] = field(default_factory=list)
    interface_map: InterfaceMap | None = None
    semantic_actions: dict[str, list[str]] = field(default_factory=dict)
    state: str = "unknown"
    editable_objects: list[str] = field(default_factory=list)
    recent_actions: list[str] = field(default_factory=list)
    shortcuts: dict[str, str] = field(default_factory=dict)
    confidence: float = 0.5


@dataclass
class WorkflowRoute:
    goal: str
    application: str
    concepts: list[str]
    steps: list[dict[str, Any]]
    verification_strategy: str
    recovery_strategy: list[str]
    confidence: float
    reused_memory: bool = False


@dataclass
class WorkflowEvaluation:
    speed_score: float
    recovery_score: float
    verification_score: float
    interruption_score: float
    confidence_delta: float
    learning: list[str]


class InterfaceProvider(Protocol):
    def map_interface(self, snapshot: Any, application_name: str) -> InterfaceMap:
        ...


class SemanticProvider(Protocol):
    def recognize(self, goal: str, interface_map: InterfaceMap) -> dict[str, list[str]]:
        ...


class WorkflowDiscoveryProvider(Protocol):
    def discover(
        self,
        goal: str,
        model: ApplicationModel,
        memories: list[dict[str, Any]],
    ) -> WorkflowRoute:
        ...


class ConfidenceProvider(Protocol):
    def score(self, goal: str, model: ApplicationModel, route: WorkflowRoute) -> float:
        ...


class LearningProvider(Protocol):
    def learn(self, profile_path: Path, model: ApplicationModel, route: WorkflowRoute, evaluation: WorkflowEvaluation) -> None:
        ...


class StateProvider(Protocol):
    def state(self, snapshot: Any) -> str:
        ...


class InterfaceMapper:
    """Build a common map from whatever desktop evidence is available."""

    PANEL_TERMS = {
        "viewport",
        "canvas",
        "timeline",
        "hierarchy",
        "inspector",
        "properties",
        "console",
        "output",
        "explorer",
        "project",
        "scene",
        "graph",
        "details",
    }

    MENU_TERMS = {
        "file",
        "edit",
        "view",
        "window",
        "tools",
        "build",
        "run",
        "debug",
        "export",
        "render",
        "package",
        "save",
        "import",
    }

    def map_interface(self, snapshot: Any, application_name: str) -> InterfaceMap:
        windows = [self._window_row(window) for window in getattr(snapshot, "windows", [])]
        titles = " ".join(row.get("title", "") for row in windows).lower()
        panels = [
            UIElement(kind="panel", label=term.title(), role=term, confidence=0.65)
            for term in sorted(self.PANEL_TERMS)
            if term in titles
        ]
        menus = [
            UIElement(kind="menu", label=term.title(), role=term, confidence=0.6)
            for term in sorted(self.MENU_TERMS)
            if term in titles or term in application_name.lower()
        ]
        foreground = getattr(snapshot, "foreground_window", None)
        workspace = {
            "foreground_title": getattr(foreground, "title", "") if foreground else "",
            "monitor_count": getattr(snapshot, "monitors", 1),
            "cursor_position": getattr(snapshot, "cursor_position", None),
            "window_count": len(windows),
        }
        search_surfaces = [UIElement(kind="search", label="Search", role="search", confidence=0.55)]
        command_surfaces = [UIElement(kind="command_palette", label="Command Palette", role="command", confidence=0.55)]
        status_surfaces = [UIElement(kind="status", label="Status Bar", role="status", confidence=0.45)]
        return InterfaceMap(
            application_name=application_name,
            windows=windows,
            panels=panels,
            menus=menus,
            search_surfaces=search_surfaces,
            command_surfaces=command_surfaces,
            status_surfaces=status_surfaces,
            workspace=workspace,
        )

    def _window_row(self, window: Any) -> dict[str, Any]:
        return {
            "title": getattr(window, "title", ""),
            "process_name": getattr(window, "process_name", ""),
            "pid": getattr(window, "pid", None),
            "foreground": getattr(window, "foreground", False),
            "rect": getattr(window, "rect", None),
        }


class SemanticUIEngine:
    CONCEPT_ALIASES = {
        "build": ["build", "compile", "package", "run build"],
        "run": ["run", "play", "start", "execute", "preview"],
        "save": ["save", "write", "persist"],
        "export": ["export", "render", "publish", "release"],
        "import": ["import", "add", "open"],
        "search": ["search", "find", "command palette"],
        "create": ["create", "new", "add", "generate"],
        "edit": ["edit", "modify", "refactor", "configure"],
        "verify": ["verify", "test", "check", "validate"],
        "node_graph": ["blueprint", "node", "graph", "shader", "behavior tree", "niagara"],
    }

    def recognize(self, goal: str, interface_map: InterfaceMap) -> dict[str, list[str]]:
        lowered = goal.lower()
        recognized: dict[str, list[str]] = {}
        visible = " ".join(
            [element.label.lower() for element in interface_map.panels + interface_map.menus]
        )
        for concept, aliases in self.CONCEPT_ALIASES.items():
            matches = [alias for alias in aliases if alias in lowered or alias in visible]
            if matches:
                recognized[concept] = matches
        if not recognized:
            recognized["explore"] = ["unknown workflow"]
        return recognized


class StateObserver:
    BUSY_TERMS = ("loading", "busy", "rendering", "compiling", "saving", "installing")
    ERROR_TERMS = ("error", "failed", "exception", "crash", "not responding")
    CONFIRM_TERMS = ("confirm", "are you sure", "permission", "allow")
    COMPLETE_TERMS = ("complete", "done", "success", "finished")

    def state(self, snapshot: Any) -> str:
        text = " ".join(
            str(getattr(window, "title", "")) for window in getattr(snapshot, "windows", [])
        ).lower()
        if any(term in text for term in self.ERROR_TERMS):
            return "error"
        if any(term in text for term in self.CONFIRM_TERMS):
            return "confirmation"
        if any(term in text for term in self.BUSY_TERMS):
            return "busy"
        if any(term in text for term in self.COMPLETE_TERMS):
            return "completed"
        return "idle"


class WorkflowDiscoveryEngine:
    def discover(
        self,
        goal: str,
        model: ApplicationModel,
        memories: list[dict[str, Any]],
    ) -> WorkflowRoute:
        concepts = list(model.semantic_actions)
        if memories:
            previous = memories[-1]
            return WorkflowRoute(
                goal=goal,
                application=model.name,
                concepts=concepts,
                steps=[
                    {
                        "kind": "plan",
                        "description": "Reuse learned workflow route.",
                        "arguments": {"memory_id": previous.get("updated_at", "")},
                        "verification": "Known route loaded from workflow memory.",
                    },
                    {
                        "kind": "verify",
                        "description": "Verify learned workflow still matches the current interface.",
                        "verification": "Stored route remains valid after interface observation.",
                    },
                ],
                verification_strategy=str(previous.get("verification_strategy", "state and output check")),
                recovery_strategy=list(previous.get("recovery_strategy", self.default_recovery())),
                confidence=0.78,
                reused_memory=True,
            )
        return WorkflowRoute(
            goal=goal,
            application=model.name,
            concepts=concepts,
            steps=[
                {
                    "kind": "understand",
                    "description": "Build a semantic model of the current interface.",
                    "verification": "Application model has mapped windows, surfaces, and likely commands.",
                },
                {
                    "kind": "discover",
                    "description": "Search command surfaces, menus, and visible panels for the safest route.",
                    "verification": "A candidate workflow route is available.",
                },
                {
                    "kind": "verify",
                    "description": "Verify state, output, notifications, or logs before reporting completion.",
                    "verification": "Expected state is visible or recorded.",
                },
            ],
            verification_strategy=self._verification_strategy(concepts),
            recovery_strategy=self.default_recovery(),
            confidence=0.55,
        )

    def default_recovery(self) -> list[str]:
        return [
            "observe",
            "re-evaluate",
            "alternative workflow",
            "search UI",
            "command palette",
            "menu traversal",
            "keyboard shortcut",
            "vision provider",
            "accessibility provider",
            "human confirmation",
        ]

    def _verification_strategy(self, concepts: list[str]) -> str:
        if "node_graph" in concepts:
            return "graph topology, compile status, and output panel check"
        if "export" in concepts:
            return "output artifact and notification check"
        if "build" in concepts or "run" in concepts:
            return "status/output/console check"
        return "state, visible result, and status check"


class ConfidenceEngine:
    def score(self, goal: str, model: ApplicationModel, route: WorkflowRoute) -> float:
        score = route.confidence
        if model.interface_map and model.interface_map.windows:
            score += 0.1
        if route.reused_memory:
            score += 0.15
        if model.state in {"error", "confirmation"}:
            score -= 0.2
        if "explore" in model.semantic_actions:
            score -= 0.1
        return max(0.05, min(0.99, round(score, 2)))


class ApplicationProfiler:
    def profile_path(self, profile_dir: Path, application_name: str) -> Path:
        safe = re.sub(r"[^a-z0-9_.-]+", "_", application_name.lower()).strip("_") or "unknown"
        return profile_dir / f"{safe}.json"

    def read_profile(self, profile_dir: Path, application_name: str) -> dict[str, Any]:
        path = self.profile_path(profile_dir, application_name)
        if not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def write_profile(self, profile_dir: Path, application_name: str, payload: dict[str, Any]) -> None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        self.profile_path(profile_dir, application_name).write_text(
            json.dumps(payload, indent=2),
            encoding="utf-8",
        )


class LearningEngine:
    def learn(self, profile_path: Path, model: ApplicationModel, route: WorkflowRoute, evaluation: WorkflowEvaluation) -> None:
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        existing: dict[str, Any] = {}
        if profile_path.is_file():
            try:
                payload = json.loads(profile_path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    existing = payload
            except json.JSONDecodeError:
                existing = {}
        workflows = list(existing.get("workflows", []))
        workflows.append(
            {
                "goal": route.goal,
                "concepts": route.concepts,
                "steps": route.steps,
                "verification_strategy": route.verification_strategy,
                "recovery_strategy": route.recovery_strategy,
                "confidence": route.confidence,
                "evaluation": asdict(evaluation),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        existing.update(
            {
                "application": model.name,
                "version": model.version,
                "process": model.process,
                "state": model.state,
                "semantic_actions": model.semantic_actions,
                "interface_map": asdict(model.interface_map) if model.interface_map else {},
                "workflows": workflows[-50:],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        profile_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")


class AdaptationEngine:
    def compare(self, previous_profile: dict[str, Any], interface_map: InterfaceMap) -> list[str]:
        previous_map = previous_profile.get("interface_map", {}) if previous_profile else {}
        previous_windows = previous_map.get("windows", []) if isinstance(previous_map, dict) else []
        notes: list[str] = []
        if previous_windows and len(previous_windows) != len(interface_map.windows):
            notes.append("Window layout changed; rebuild route from semantic surfaces.")
        previous_workspace = previous_map.get("workspace", {}) if isinstance(previous_map, dict) else {}
        if previous_workspace.get("monitor_count") != interface_map.workspace.get("monitor_count"):
            notes.append("Monitor layout changed; avoid coordinate reuse.")
        if not notes:
            notes.append("Interface map compatible with stored profile.")
        return notes


class ApplicationIntelligenceLayer:
    def __init__(
        self,
        profile_dir: Path,
        interface_mapper: Optional[InterfaceProvider] = None,
        semantic_engine: Optional[SemanticProvider] = None,
        discovery_engine: Optional[WorkflowDiscoveryProvider] = None,
        confidence_engine: Optional[ConfidenceProvider] = None,
        learning_engine: Optional[LearningProvider] = None,
        state_observer: Optional[StateProvider] = None,
        profiler: Optional[ApplicationProfiler] = None,
        adaptation_engine: Optional[AdaptationEngine] = None,
    ) -> None:
        self.profile_dir = profile_dir
        self.interface_mapper = interface_mapper or InterfaceMapper()
        self.semantic_engine = semantic_engine or SemanticUIEngine()
        self.discovery_engine = discovery_engine or WorkflowDiscoveryEngine()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.learning_engine = learning_engine or LearningEngine()
        self.state_observer = state_observer or StateObserver()
        self.profiler = profiler or ApplicationProfiler()
        self.adaptation_engine = adaptation_engine or AdaptationEngine()

    def understand(
        self,
        goal: str,
        snapshot: Any,
        application_hint: str,
        workflow_memories: list[dict[str, Any]],
    ) -> tuple[ApplicationModel, WorkflowRoute, list[str]]:
        application_name, process = self._application_identity(snapshot, application_hint)
        interface_map = self.interface_mapper.map_interface(snapshot, application_name)
        semantic_actions = self.semantic_engine.recognize(goal, interface_map)
        model = ApplicationModel(
            name=application_name,
            process=process,
            windows=interface_map.windows,
            interface_map=interface_map,
            semantic_actions=semantic_actions,
            state=self.state_observer.state(snapshot),
            confidence=0.5,
        )
        profile = self.profiler.read_profile(self.profile_dir, application_name)
        adaptation_notes = self.adaptation_engine.compare(profile, interface_map)
        route = self.discovery_engine.discover(goal, model, workflow_memories or self._profile_workflows(profile, goal))
        route.confidence = self.confidence_engine.score(goal, model, route)
        model.confidence = route.confidence
        return model, route, adaptation_notes

    def evaluate(
        self,
        ok: bool,
        recovered: bool,
        verified: bool,
        timing_ms: float,
        user_interrupted: bool = False,
    ) -> WorkflowEvaluation:
        speed_score = 1.0 if timing_ms <= 2000 else max(0.2, 2000 / max(timing_ms, 1))
        recovery_score = 1.0 if ok and recovered else 0.75 if ok else 0.2
        verification_score = 1.0 if verified else 0.35
        interruption_score = 0.0 if user_interrupted else 1.0
        confidence_delta = 0.08 if ok else -0.12
        learning = ["Stored successful semantic workflow."] if ok else ["Stored failure case for future recovery."]
        return WorkflowEvaluation(
            speed_score=round(speed_score, 2),
            recovery_score=round(recovery_score, 2),
            verification_score=round(verification_score, 2),
            interruption_score=interruption_score,
            confidence_delta=confidence_delta,
            learning=learning,
        )

    def learn(self, model: ApplicationModel, route: WorkflowRoute, evaluation: WorkflowEvaluation) -> None:
        path = self.profiler.profile_path(self.profile_dir, model.name)
        self.learning_engine.learn(path, model, route, evaluation)

    def _profile_workflows(self, profile: dict[str, Any], goal: str) -> list[dict[str, Any]]:
        workflows = profile.get("workflows", []) if profile else []
        if not isinstance(workflows, list):
            return []
        terms = set(re.findall(r"[a-z0-9]+", goal.lower()))
        matches: list[dict[str, Any]] = []
        for workflow in workflows:
            if not isinstance(workflow, dict):
                continue
            workflow_terms = set(re.findall(r"[a-z0-9]+", str(workflow.get("goal", "")).lower()))
            concept_terms = set(str(item).lower() for item in workflow.get("concepts", []))
            if terms & workflow_terms or terms & concept_terms:
                matches.append(workflow)
        return matches[-3:]

    def _application_identity(self, snapshot: Any, application_hint: str) -> tuple[str, str]:
        foreground = getattr(snapshot, "foreground_window", None)
        process = str(getattr(foreground, "process_name", "") or "").strip()
        title = str(getattr(foreground, "title", "") or "").strip()
        if application_hint and application_hint not in {"current", "unknown"}:
            return application_hint, process
        if process:
            return re.sub(r"\.exe$", "", process, flags=re.IGNORECASE), process
        if title:
            return title.split(" - ")[0].strip() or "current"
        return application_hint or "current"
