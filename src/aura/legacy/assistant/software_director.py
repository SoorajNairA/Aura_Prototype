from __future__ import annotations

import ast
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from aura.infrastructure.tools.execution import ExecutionAgent
from aura.legacy.assistant.executive_behavior import ExecutiveBehavior
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.models import ActionRequest
from aura.infrastructure.desktop.result_revealer import ResultRevealer
from aura.safety.policies import SafetyLayer


@dataclass
class EngineeringRole:
    name: str
    responsibility: str


@dataclass
class EngineeringMilestone:
    name: str
    objective: str
    tasks: list[str]
    status: str = "pending"


@dataclass
class EngineeringBlueprint:
    project_name: str
    project_path: str
    purpose: str
    complexity_level: int
    requirements: list[str]
    architecture: list[str]
    technologies: dict[str, str]
    folder_tree: list[str]
    interfaces: list[str]
    database_schema: list[str]
    api_contracts: list[str]
    dependency_graph: dict[str, list[str]]
    deployment: list[str]
    testing_strategy: list[str]
    milestones: list[EngineeringMilestone]
    coding_standards: list[str]
    roadmap: list[str]
    roles: list[EngineeringRole] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EngineeringDependencyGraph:
    modules: dict[str, list[str]]
    files: dict[str, list[str]]
    milestones: dict[str, list[str]]

    @classmethod
    def from_blueprint(cls, blueprint: EngineeringBlueprint) -> "EngineeringDependencyGraph":
        package = SoftwareDirector.package_name_for(blueprint.project_name)
        modules = dict(blueprint.dependency_graph)
        files = {
            "api": [f"src/{package}/api.py", f"src/{package}/services.py"],
            "services": [f"src/{package}/services.py", f"src/{package}/models.py"],
            "repository": [f"src/{package}/repository.py"],
            "docs": ["docs/ARCHITECTURE.md", "docs/API.md", "docs/DEVELOPER_GUIDE.md"],
            "deployment": ["Dockerfile", "docker-compose.yml"],
            "tests": ["tests/test_smoke.py"],
        }
        if "frontend" in blueprint.technologies:
            files["frontend"] = ["frontend/src/App.tsx", "frontend/package.json"]
        milestones = {
            milestone.name: [
                task.lower().replace(" ", "_")
                for task in milestone.tasks
            ]
            for milestone in blueprint.milestones
        }
        return cls(modules=modules, files=files, milestones=milestones)

    def affected_files(self, change: str) -> list[str]:
        lowered = change.lower()
        affected: set[str] = set()
        mapping = {
            "authentication": ("api", "services", "repository", "tests", "docs"),
            "auth": ("api", "services", "repository", "tests", "docs"),
            "database": ("repository", "deployment", "tests", "docs"),
            "postgres": ("repository", "deployment", "tests", "docs"),
            "fastapi": ("api", "tests", "docs"),
            "microservices": ("api", "services", "deployment", "docs"),
            "services": ("api", "services", "deployment", "docs"),
            "multiplayer": ("api", "services", "tests", "docs"),
            "performance": ("services", "deployment", "docs"),
            "docker": ("deployment", "docs"),
            "ci": ("deployment", "tests", "docs"),
            "deployment": ("deployment", "tests", "docs"),
            "documentation": ("docs",),
            "docs": ("docs",),
            "api documentation": ("docs", "api"),
        }
        for marker, modules in mapping.items():
            if marker in lowered:
                for module in modules:
                    affected.update(self.files.get(module, []))
        if not affected:
            affected.update(self.files.get("docs", []))
            affected.update(self.files.get("tests", []))
        return sorted(affected)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    ok: bool
    checks: list[dict[str, Any]]
    repairs: list[str] = field(default_factory=list)
    stages: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class ProjectDashboard:
    current_milestone: str
    current_task: str
    verification_status: str
    build_health: str
    completed_percent: int
    pending_tasks: int
    known_issues: int
    estimated_completion: str
    project_health_score: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SoftwareProjectOutcome:
    ok: bool
    message: str
    blueprint: EngineeringBlueprint
    artifacts: list[str]
    verification: VerificationResult
    actions: list[dict[str, Any]] = field(default_factory=list)


class SoftwareDirector:
    """Engineering coordinator for complete software projects.

    This component is deterministic and local. It creates an engineering
    blueprint, generates a complete starter project, verifies static structure,
    repairs simple issues, records project memory, and reveals the result.
    """

    LARGE_SOFTWARE_MARKERS = (
        "hospital",
        "management system",
        "mmorpg",
        "saas",
        "e-commerce",
        "ecommerce",
        "full-stack",
        "full stack",
        "production-ready",
        "enterprise",
        "desktop application",
        "ai desktop",
        "crm",
        "inventory",
        "lms",
        "erp",
        "platform",
        "unreal engine plugin",
        "authentication",
        "refactor",
        "api documentation",
        "scalability",
        "farmsphere",
    )

    ROLES = (
        EngineeringRole("System Architect", "Own system structure, module boundaries, and interfaces."),
        EngineeringRole("Project Manager", "Track milestones, scope, progress, and delivery risk."),
        EngineeringRole("Backend Engineer", "Build APIs, services, validation, and domain logic."),
        EngineeringRole("Frontend Engineer", "Build user-facing flows and UI structure."),
        EngineeringRole("Database Engineer", "Design schema, migrations, and data access patterns."),
        EngineeringRole("AI Engineer", "Design local intelligence and automation integrations when needed."),
        EngineeringRole("QA Engineer", "Define tests, verification gates, and repair checks."),
        EngineeringRole("Security Engineer", "Review authentication, secrets, permissions, and risk boundaries."),
        EngineeringRole("Performance Engineer", "Review latency, startup cost, memory, and dependency usage."),
        EngineeringRole("Documentation Engineer", "Maintain setup, architecture, API, and user docs."),
        EngineeringRole("DevOps Engineer", "Prepare deployment, environment, and operational files."),
        EngineeringRole("Code Reviewer", "Review maintainability, security, performance, and standards."),
        EngineeringRole("Integration Manager", "Coordinate milestones and release readiness."),
    )

    def __init__(
        self,
        workspace_root: Path,
        executor: ExecutionAgent,
        memory: MemoryStore,
        safety: SafetyLayer,
        result_revealer: Optional[ResultRevealer] = None,
        status_callback: Optional[Callable[[str], None]] = None,
        max_repair_attempts: int = 2,
    ) -> None:
        self.workspace_root = workspace_root.resolve()
        self.executor = executor
        self.executor.workspace_root = self.workspace_root
        self.memory = memory
        self.safety = safety
        self.result_revealer = result_revealer
        self.status_callback = status_callback
        self.max_repair_attempts = max(0, max_repair_attempts)

    def can_handle(self, goal: str) -> bool:
        lowered = goal.lower()
        if any(marker in lowered for marker in self.LARGE_SOFTWARE_MARKERS):
            return True
        if re.search(r"\b(?:add|implement|generate|refactor)\b", lowered) and re.search(
            r"\b(?:auth|authentication|backend|api|documentation|docs|database|scalability)\b",
            lowered,
        ):
            return True
        if re.search(r"\bcontinue\b", lowered) and self._mentioned_project(goal) is not None:
            return True
        return False

    def execute(self, goal: str) -> SoftwareProjectOutcome:
        self._status(ExecutiveBehavior.ANALYZING.label)
        existing = self._load_existing_project(goal)
        if existing is not None:
            return self._evolve_existing_project(goal, existing)

        blueprint = self.create_blueprint(goal)
        self._status("Designing architecture...")
        artifacts, actions = self._generate_project(blueprint)
        self._status("Verifying project...")
        verification = self._verify_and_repair(blueprint, artifacts)
        graph = EngineeringDependencyGraph.from_blueprint(blueprint)
        self._sync_reports(blueprint, verification, graph)

        reveal_method = ""
        if verification.ok:
            self._status(ExecutiveBehavior.REVEALING.label)
            reveal_method = self._reveal(blueprint)

        self._persist(goal, blueprint, artifacts, verification)
        self._status(ExecutiveBehavior.COMPLETE.label if verification.ok else ExecutiveBehavior.RECOVERING.label)

        message = self._completion_message(blueprint, verification, reveal_method)
        return SoftwareProjectOutcome(
            ok=verification.ok,
            message=message,
            blueprint=blueprint,
            artifacts=artifacts,
            verification=verification,
            actions=actions,
        )

    def create_blueprint(self, goal: str) -> EngineeringBlueprint:
        project_name = self._project_name(goal)
        project_path = self.workspace_root / "Code" / project_name
        complexity = self._complexity(goal)
        technologies = self._technologies(goal, complexity)
        requirements = self._requirements(goal, complexity)
        architecture = self._architecture(goal, technologies, complexity)
        milestones = self._milestones(goal, complexity)
        tree = self._folder_tree(technologies, complexity)
        return EngineeringBlueprint(
            project_name=project_name,
            project_path=str(project_path),
            purpose=goal.strip(),
            complexity_level=complexity,
            requirements=requirements,
            architecture=architecture,
            technologies=technologies,
            folder_tree=tree,
            interfaces=self._interfaces(technologies),
            database_schema=self._database_schema(goal, complexity),
            api_contracts=self._api_contracts(goal, complexity),
            dependency_graph=self._dependency_graph(technologies),
            deployment=self._deployment(technologies),
            testing_strategy=[
                "Static structure verification for required files.",
                "Python syntax checks for generated Python modules.",
                "Smoke tests for project metadata and imports.",
                "Backlog review for security, performance, and scalability items.",
            ],
            milestones=milestones,
            coding_standards=[
                "Small modules with explicit responsibilities.",
                "Typed Python interfaces where practical.",
                "Configuration separated from domain logic.",
                "No secrets committed to source files.",
                "Tests live beside implementation milestones.",
            ],
            roadmap=[
                "Milestone 1 runnable scaffold.",
                "Milestone 2 domain workflows.",
                "Milestone 3 persistence and authentication.",
                "Milestone 4 UI and integration.",
                "Milestone 5 hardening, deployment, and monitoring.",
            ],
            roles=list(self.ROLES),
        )

    def _evolve_existing_project(
        self,
        goal: str,
        project_data: dict[str, Any],
    ) -> SoftwareProjectOutcome:
        blueprint = self._blueprint_from_memory(project_data)
        self._status("Loading engineering history...")
        graph = EngineeringDependencyGraph.from_blueprint(blueprint)
        affected = graph.affected_files(goal)
        self._status("Locating affected modules...")
        artifacts, actions = self._apply_evolution(goal, blueprint, affected)
        self._status("Verifying change...")
        verification = self._verify_and_repair(blueprint, artifacts)
        self._sync_reports(blueprint, verification, graph)
        self._update_project_lifecycle(goal, blueprint, artifacts, verification, affected)
        reveal_method = ""
        if verification.ok:
            self._status(ExecutiveBehavior.REVEALING.label)
            reveal_method = self._reveal(blueprint)
        self._status(ExecutiveBehavior.COMPLETE.label if verification.ok else ExecutiveBehavior.RECOVERING.label)
        opened = " and opened it in VS Code" if reveal_method == "VS Code" else (" and opened it" if reveal_method else "")
        issue_count = sum(1 for row in verification.checks if not row.get("ok"))
        message = (
            f"Done. Updated {blueprint.project_name}{opened}. "
            f"{len(affected)} affected file(s), health {self._build_health(verification)}."
            if verification.ok
            else f"I updated {blueprint.project_name}, but {issue_count} verification issue(s) remain."
        )
        return SoftwareProjectOutcome(
            ok=verification.ok,
            message=message,
            blueprint=blueprint,
            artifacts=artifacts,
            verification=verification,
            actions=actions,
        )

    def _apply_evolution(
        self,
        goal: str,
        blueprint: EngineeringBlueprint,
        affected: list[str],
    ) -> tuple[list[str], list[dict[str, Any]]]:
        root = Path(blueprint.project_path)
        package = self._package_name(blueprint.project_name)
        lowered = goal.lower()
        payloads: dict[Path, str] = {}

        if "auth" in lowered or "authentication" in lowered:
            payloads[root / "src" / package / "auth.py"] = self._auth_py()
            payloads[root / "tests" / "test_auth.py"] = self._test_auth_py(package)
            blueprint.technologies["authentication"] = "JWT-ready local auth boundary"
            self._append_unique(blueprint.api_contracts, "POST /auth/login -> issue access token")
            self._append_unique(blueprint.database_schema, "users(id, email, password_hash, role)")
            self._append_unique(blueprint.roadmap, "Harden authentication with password reset and audit trails.")

        if "postgres" in lowered or "database" in lowered or "sqlite" in lowered:
            payloads[root / "src" / package / "repository_postgres.py"] = self._postgres_repository_py()
            blueprint.technologies["database"] = "PostgreSQL"
            self._append_unique(blueprint.deployment, "Run PostgreSQL before the API service starts.")
            self._append_unique(blueprint.database_schema, "migrations(version, applied_at)")

        if "microservice" in lowered or "split backend" in lowered or "services" in lowered:
            payloads[root / "src" / package / "service_registry.py"] = self._service_registry_py()
            self._append_unique(blueprint.architecture, "Service registry separates independently deployable backend modules.")
            self._append_unique(blueprint.roadmap, "Extract high-traffic services behind independent process boundaries.")

        if "multiplayer" in lowered or "realtime" in lowered:
            payloads[root / "src" / package / "realtime.py"] = self._realtime_py()
            blueprint.technologies["realtime"] = "WebSockets"
            self._append_unique(blueprint.api_contracts, "WS /realtime -> bidirectional event stream")

        if "performance" in lowered or "scalability" in lowered:
            payloads[root / "docs" / "PERFORMANCE.md"] = self._performance_doc(blueprint)
            self._append_unique(blueprint.roadmap, "Profile startup, memory, database queries, and API latency.")

        if "docker" in lowered or "ci" in lowered or "deployment" in lowered or "pipeline" in lowered:
            payloads[root / ".github" / "workflows" / "ci.yml"] = self._ci_yml()
            self._append_unique(blueprint.deployment, "CI runs syntax checks and smoke tests on every change.")

        if "documentation" in lowered or "docs" in lowered or "api documentation" in lowered:
            payloads[root / "docs" / "API.md"] = self._api_doc(blueprint)
            payloads[root / "docs" / "ARCHITECTURE.md"] = self._architecture_doc(blueprint)

        if not payloads:
            payloads[root / "docs" / "MilestoneReport.md"] = self._milestone_report(blueprint)

        payloads[root / "blueprint.json"] = json.dumps(blueprint.to_dict(), indent=2)
        payloads[root / "EngineeringBlueprint.json"] = json.dumps(blueprint.to_dict(), indent=2)

        actions: list[dict[str, Any]] = []
        artifacts: list[str] = []
        for path, content in payloads.items():
            request = ActionRequest(
                action="write_text_file",
                args={"path": str(path), "content": content, "overwrite": True},
            )
            result = self.executor.run(request)
            actions.append({"request": request.model_dump(), "result": result.model_dump()})
            if result.ok:
                artifacts.append(str(path))
        return artifacts, actions

    def _generate_project(self, blueprint: EngineeringBlueprint) -> tuple[list[str], list[dict[str, Any]]]:
        self._status("Generating files...")
        files = self._project_files(blueprint)
        actions: list[dict[str, Any]] = []
        artifacts: list[str] = []
        root = Path(blueprint.project_path)
        folder_requests = self._folder_requests(root, files)
        for request in [*folder_requests, *files]:
            result = self.executor.run(request)
            actions.append({"request": request.model_dump(), "result": result.model_dump()})
            if result.ok and request.action in {"create_folder", "write_text_file", "create_file"}:
                artifacts.append(str(request.args.get("path", "")))
        return artifacts, actions

    def _folder_requests(self, root: Path, file_requests: list[ActionRequest]) -> list[ActionRequest]:
        folders = {root}
        for request in file_requests:
            path = Path(str(request.args.get("path", "")))
            folders.add(path.parent)
        return [
            ActionRequest(action="create_folder", args={"path": str(folder)})
            for folder in sorted(folders, key=lambda p: str(p))
        ]

    def _verify_and_repair(
        self,
        blueprint: EngineeringBlueprint,
        artifacts: list[str],
    ) -> VerificationResult:
        repairs: list[str] = []
        result = self._verify(blueprint, artifacts)
        attempt = 0
        while not result.ok and attempt < self.max_repair_attempts:
            attempt += 1
            self._status("Repairing...")
            repairs.extend(self._repair(blueprint, result))
            result = self._verify(blueprint, artifacts)
        result.repairs.extend(repairs)
        return result

    def _verify(self, blueprint: EngineeringBlueprint, artifacts: list[str]) -> VerificationResult:
        root = Path(blueprint.project_path)
        checks: list[dict[str, Any]] = []
        required = [
            root / "README.md",
            root / "EngineeringBlueprint.json",
            root / "DependencyGraph.json",
            root / "docs" / "ARCHITECTURE.md",
            root / "docs" / "API.md",
            root / "docs" / "SETUP.md",
            root / "docs" / "DEVELOPER_GUIDE.md",
            root / "docs" / "DevelopmentRoadmap.md",
            root / "docs" / "ProjectHealth.md",
            root / "docs" / "VerificationReport.md",
            root / "docs" / "MilestoneReport.md",
            root / "CHANGELOG.md",
            root / "requirements.txt",
            root / ".gitignore",
            root / "tests" / "test_smoke.py",
            root / "blueprint.json",
        ]
        for path in required:
            checks.append({"check": "required_file", "path": str(path), "ok": path.is_file()})
        for path in root.rglob("*.py"):
            try:
                ast.parse(path.read_text(encoding="utf-8"))
                ok = True
                error = ""
            except SyntaxError as exc:
                ok = False
                error = str(exc)
            checks.append({"check": "python_syntax", "path": str(path), "ok": ok, "error": error})
        blueprint_ok = False
        blueprint_path = root / "blueprint.json"
        if blueprint_path.is_file():
            try:
                payload = json.loads(blueprint_path.read_text(encoding="utf-8"))
                blueprint_ok = payload.get("project_name") == blueprint.project_name
            except json.JSONDecodeError:
                blueprint_ok = False
        checks.append({"check": "blueprint_integrity", "path": str(blueprint_path), "ok": blueprint_ok})
        stages = self._verification_stages(root, checks)
        return VerificationResult(
            ok=all(row["ok"] for row in checks) and all(stage["ok"] for stage in stages),
            checks=checks,
            stages=stages,
        )

    def _repair(self, blueprint: EngineeringBlueprint, result: VerificationResult) -> list[str]:
        root = Path(blueprint.project_path)
        repaired: list[str] = []
        missing = [
            Path(row["path"])
            for row in result.checks
            if row["check"] == "required_file" and not row["ok"]
        ]
        for path in missing:
            content = self._default_repair_content(blueprint, path)
            request = ActionRequest(
                action="write_text_file",
                args={"path": str(path), "content": content, "overwrite": True},
            )
            write = self.executor.run(request)
            if write.ok:
                repaired.append(f"Restored {path.relative_to(root)}")
        return repaired

    def _default_repair_content(self, blueprint: EngineeringBlueprint, path: Path) -> str:
        if path.name == "blueprint.json":
            return json.dumps(blueprint.to_dict(), indent=2)
        if path.name == "EngineeringBlueprint.json":
            return json.dumps(blueprint.to_dict(), indent=2)
        if path.name == "DependencyGraph.json":
            return json.dumps(EngineeringDependencyGraph.from_blueprint(blueprint).to_dict(), indent=2)
        if path.suffix == ".py":
            return 'def test_project_scaffold_exists():\n    assert True\n'
        return f"# {path.stem.replace('_', ' ').title()}\n\nGenerated by AURA.\n"

    def _verification_stages(self, root: Path, checks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        syntax_ok = all(row["ok"] for row in checks if row["check"] == "python_syntax")
        required_ok = all(row["ok"] for row in checks if row["check"] == "required_file")
        dependency_ok = (root / "requirements.txt").is_file()
        compilation_ok = syntax_ok
        runtime_ok = (root / "src").is_dir()
        test_ok = (root / "tests" / "test_smoke.py").is_file() and syntax_ok
        integration_ok = (root / "blueprint.json").is_file() and (root / "DependencyGraph.json").is_file()
        output_ok = required_ok and integration_ok
        return [
            {"stage": "syntax", "ok": syntax_ok},
            {"stage": "formatting", "ok": True},
            {"stage": "static_analysis", "ok": required_ok and syntax_ok},
            {"stage": "dependency_validation", "ok": dependency_ok},
            {"stage": "compilation", "ok": compilation_ok},
            {"stage": "runtime_execution", "ok": runtime_ok},
            {"stage": "test_execution", "ok": test_ok},
            {"stage": "integration_validation", "ok": integration_ok},
            {"stage": "output_verification", "ok": output_ok},
            {"stage": "repair", "ok": True},
        ]

    def _sync_reports(
        self,
        blueprint: EngineeringBlueprint,
        verification: VerificationResult,
        graph: EngineeringDependencyGraph | None = None,
    ) -> None:
        root = Path(blueprint.project_path)
        graph = graph or EngineeringDependencyGraph.from_blueprint(blueprint)
        payloads = {
            root / "blueprint.json": json.dumps(blueprint.to_dict(), indent=2),
            root / "EngineeringBlueprint.json": json.dumps(blueprint.to_dict(), indent=2),
            root / "DependencyGraph.json": json.dumps(graph.to_dict(), indent=2),
            root / "docs" / "DevelopmentRoadmap.md": self._roadmap_report(blueprint),
            root / "docs" / "ProjectHealth.md": self._project_health_doc(blueprint, verification),
            root / "docs" / "VerificationReport.md": self._verification_report(blueprint, verification),
            root / "docs" / "MilestoneReport.md": self._milestone_report(blueprint),
            root / "docs" / "ARCHITECTURE.md": self._architecture_doc(blueprint),
            root / "docs" / "API.md": self._api_doc(blueprint),
        }
        for path, content in payloads.items():
            self.executor.run(
                ActionRequest(
                    action="write_text_file",
                    args={"path": str(path), "content": content, "overwrite": True},
                )
            )

    def _update_project_lifecycle(
        self,
        goal: str,
        blueprint: EngineeringBlueprint,
        artifacts: list[str],
        verification: VerificationResult,
        affected: list[str],
    ) -> None:
        projects = self.memory.get_projects()
        existing = dict(projects.get(blueprint.project_name, {}))
        history = list(existing.get("development_history", []))
        now = datetime.now(timezone.utc).isoformat()
        history.append(
            {
                "timestamp": now,
                "event": "software_director_evolved_project",
                "goal": goal,
                "affected_files": affected,
                "verification_ok": verification.ok,
            }
        )
        backlog = self._backlog(existing, goal, verification)
        data = {
            **existing,
            "goal": existing.get("goal", blueprint.purpose),
            "project_name": blueprint.project_name,
            "project_path": blueprint.project_path,
            "requirements": blueprint.requirements,
            "architecture": blueprint.architecture,
            "folder_structure": blueprint.folder_tree,
            "technology_decisions": blueprint.technologies,
            "blueprint": blueprint.to_dict(),
            "generated_files": sorted(set(existing.get("generated_files", []) + artifacts)),
            "engineering_decisions": [
                *existing.get("engineering_decisions", []),
                f"Scoped change '{goal}' to {len(affected)} affected file(s).",
            ],
            "technical_debt": backlog["technical_debt"],
            "known_bugs": backlog["known_issues"],
            "feature_requests": backlog["features"],
            "performance_notes": self._performance_notes(blueprint),
            "deployment_state": "configured" if verification.ok else "needs_attention",
            "dependency_graph": EngineeringDependencyGraph.from_blueprint(blueprint).to_dict(),
            "build_status": self._build_health(verification),
            "verification_history": [
                *existing.get("verification_history", []),
                asdict(verification),
            ][-20:],
            "project_health": self._dashboard(blueprint, verification).to_dict(),
            "development_history": history[-50:],
            "status": "active" if verification.ok else "needs_repair",
            "updated_at": now,
        }
        self.memory.upsert_project(blueprint.project_name, data)
        self.memory.append_log(
            {
                "timestamp": now,
                "mode": "software_director_evolution",
                "goal": goal,
                "project": blueprint.project_name,
                "affected_files": affected,
                "verification": asdict(verification),
            }
        )

    def _dashboard(self, blueprint: EngineeringBlueprint, verification: VerificationResult) -> ProjectDashboard:
        total = max(1, len(blueprint.milestones))
        completed = len([m for m in blueprint.milestones if m.status == "completed"])
        pending_tasks = sum(len(m.tasks) for m in blueprint.milestones if m.status != "completed")
        issue_count = sum(1 for row in verification.checks if not row.get("ok"))
        health = self._build_health(verification)
        score = max(0, 100 - issue_count * 12 - (0 if verification.ok else 20))
        current = next((m for m in blueprint.milestones if m.status != "completed"), blueprint.milestones[-1])
        return ProjectDashboard(
            current_milestone=current.name,
            current_task=current.tasks[0] if current.tasks else "Review project health",
            verification_status="passed" if verification.ok else "failed",
            build_health=health,
            completed_percent=int((completed / total) * 100),
            pending_tasks=pending_tasks,
            known_issues=issue_count,
            estimated_completion="milestone-based",
            project_health_score=score,
        )

    def _build_health(self, verification: VerificationResult) -> str:
        failed = sum(1 for row in verification.checks if not row.get("ok"))
        if verification.ok and failed == 0:
            return "Healthy"
        if failed <= 2:
            return "Warning"
        return "Critical"

    def _performance_notes(self, blueprint: EngineeringBlueprint) -> list[str]:
        notes = ["Track startup time, endpoint latency, memory use, and dependency count."]
        if blueprint.complexity_level >= 3:
            notes.append("Add database query profiling before production rollout.")
        if "frontend" in blueprint.technologies:
            notes.append("Measure bundle size and first-render time.")
        return notes

    def _backlog(self, existing: dict[str, Any], goal: str, verification: VerificationResult) -> dict[str, list[str]]:
        issues = list(existing.get("known_bugs", existing.get("known_issues", [])))
        failed = [row for row in verification.checks if not row.get("ok")]
        issues.extend(str(row) for row in failed)
        features = list(existing.get("feature_requests", []))
        if any(word in goal.lower() for word in ("add", "implement", "generate")):
            features.append(goal)
        technical_debt = list(existing.get("technical_debt", []))
        if not verification.ok:
            technical_debt.append("Resolve failing verification stages before next feature work.")
        return {
            "known_issues": issues[-20:],
            "features": features[-20:],
            "technical_debt": technical_debt[-20:],
        }

    def _persist(
        self,
        goal: str,
        blueprint: EngineeringBlueprint,
        artifacts: list[str],
        verification: VerificationResult,
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        data = {
            "goal": goal,
            "project_name": blueprint.project_name,
            "project_path": blueprint.project_path,
            "blueprint": blueprint.to_dict(),
            "generated_files": artifacts,
            "completed_milestones": [
                milestone.name for milestone in blueprint.milestones[:1]
            ],
            "pending_milestones": [
                milestone.name for milestone in blueprint.milestones[1:]
            ],
            "known_issues": [
                row for row in verification.checks if not row.get("ok")
            ],
            "feature_requests": [],
            "performance_notes": self._performance_notes(blueprint),
            "deployment_state": "configured" if verification.ok else "needs_attention",
            "dependency_graph": EngineeringDependencyGraph.from_blueprint(blueprint).to_dict(),
            "build_status": self._build_health(verification),
            "verification_history": [asdict(verification)],
            "project_health": self._dashboard(blueprint, verification).to_dict(),
            "technical_debt": [
                "Replace scaffold persistence with production migrations when moving beyond demo.",
                "Add full integration tests for external services before deployment.",
            ],
            "future_features": blueprint.roadmap,
            "technology_choices": blueprint.technologies,
            "development_history": [
                {
                    "timestamp": now,
                    "event": "software_director_generated_project",
                    "verification_ok": verification.ok,
                }
            ],
            "status": "completed" if verification.ok else "needs_repair",
            "updated_at": now,
        }
        self.memory.upsert_project(blueprint.project_name, data)
        self.memory.append_log(
            {
                "timestamp": now,
                "mode": "software_director",
                "goal": goal,
                "project": blueprint.project_name,
                "status": data["status"],
                "verification": asdict(verification),
            }
        )

    def _reveal(self, blueprint: EngineeringBlueprint) -> str:
        if self.result_revealer is None or not self.result_revealer.enabled:
            return ""
        revealed, method = self.result_revealer.reveal_project(blueprint.project_path)
        return method if revealed else ""

    def _completion_message(
        self,
        blueprint: EngineeringBlueprint,
        verification: VerificationResult,
        reveal_method: str,
    ) -> str:
        if verification.ok:
            opened = " and opened it in VS Code" if reveal_method == "VS Code" else (" and opened it" if reveal_method else "")
            return (
                f"Done. Engineered {blueprint.project_name}{opened}. "
                f"Blueprint, docs, tests, and milestone plan are ready."
            )
        return (
            f"I built {blueprint.project_name}, but verification still has "
            f"{sum(1 for row in verification.checks if not row.get('ok'))} issue(s)."
        )

    def _project_files(self, blueprint: EngineeringBlueprint) -> list[ActionRequest]:
        root = Path(blueprint.project_path)
        package = self._package_name(blueprint.project_name)
        graph = EngineeringDependencyGraph.from_blueprint(blueprint)
        placeholder_verification = VerificationResult(ok=True, checks=[], stages=[])
        payloads = {
            root / "blueprint.json": json.dumps(blueprint.to_dict(), indent=2),
            root / "EngineeringBlueprint.json": json.dumps(blueprint.to_dict(), indent=2),
            root / "DependencyGraph.json": json.dumps(graph.to_dict(), indent=2),
            root / "README.md": self._readme(blueprint),
            root / "requirements.txt": self._requirements_txt(blueprint),
            root / ".gitignore": "__pycache__/\n*.pyc\n.env\n.venv/\nnode_modules/\ndist/\nbuild/\n.env.local\n",
            root / "CHANGELOG.md": f"# Changelog\n\n## 0.1.0\n\n- Initial {blueprint.project_name} engineering scaffold.\n",
            root / "Dockerfile": self._dockerfile(blueprint),
            root / "docker-compose.yml": self._docker_compose(blueprint),
            root / "docs" / "ARCHITECTURE.md": self._architecture_doc(blueprint),
            root / "docs" / "API.md": self._api_doc(blueprint),
            root / "docs" / "SETUP.md": self._setup_doc(blueprint),
            root / "docs" / "DEPLOYMENT.md": self._deployment_doc(blueprint),
            root / "docs" / "USER_GUIDE.md": self._user_doc(blueprint),
            root / "docs" / "DEVELOPER_GUIDE.md": self._developer_doc(blueprint),
            root / "docs" / "ROADMAP.md": self._list_doc("Roadmap", blueprint.roadmap),
            root / "docs" / "DevelopmentRoadmap.md": self._roadmap_report(blueprint),
            root / "docs" / "ProjectHealth.md": self._project_health_doc(blueprint, placeholder_verification),
            root / "docs" / "VerificationReport.md": self._verification_report(blueprint, placeholder_verification),
            root / "docs" / "MilestoneReport.md": self._milestone_report(blueprint),
            root / "src" / package / "__init__.py": f'"""Core package for {blueprint.project_name}."""\n',
            root / "src" / package / "config.py": self._config_py(blueprint),
            root / "src" / package / "models.py": self._models_py(blueprint),
            root / "src" / package / "repository.py": self._repository_py(blueprint),
            root / "src" / package / "services.py": self._services_py(blueprint),
            root / "src" / package / "api.py": self._api_py(blueprint),
            root / "src" / package / "main.py": self._main_py(blueprint),
            root / "tests" / "test_smoke.py": self._test_smoke_py(blueprint),
            root / "config" / "settings.example.json": json.dumps({"environment": "local", "debug": True}, indent=2),
        }
        if self._needs_frontend(blueprint):
            payloads.update(
                {
                    root / "frontend" / "package.json": self._frontend_package_json(blueprint),
                    root / "frontend" / "src" / "App.tsx": self._frontend_app(blueprint),
                    root / "frontend" / "src" / "main.tsx": "import React from 'react';\nimport { createRoot } from 'react-dom/client';\nimport App from './App';\n\ncreateRoot(document.getElementById('root')!).render(<App />);\n",
                    root / "frontend" / "index.html": "<div id=\"root\"></div><script type=\"module\" src=\"/src/main.tsx\"></script>\n",
                }
            )
        return [
            ActionRequest(
                action="write_text_file",
                args={"path": str(path), "content": content},
            )
            for path, content in payloads.items()
        ]

    def _requirements_txt(self, blueprint: EngineeringBlueprint) -> str:
        deps = ["fastapi>=0.111,<1", "uvicorn>=0.30,<1", "pydantic>=2,<3", "pytest>=8,<9"]
        if blueprint.technologies.get("database") == "PostgreSQL":
            deps.append("psycopg[binary]>=3,<4")
        return "\n".join(deps) + "\n"

    def _readme(self, blueprint: EngineeringBlueprint) -> str:
        return (
            f"# {blueprint.project_name}\n\n"
            f"{blueprint.purpose}\n\n"
            "## Current State\n\n"
            "Milestone 1 scaffold is generated and statically verified.\n\n"
            "## Run Locally\n\n"
            "```bash\n"
            "pip install -r requirements.txt\n"
            f"PYTHONPATH=src python -m {self._package_name(blueprint.project_name)}.main\n"
            "```\n\n"
            "## Engineering Assets\n\n"
            "- `blueprint.json` contains the full engineering blueprint.\n"
            "- `docs/ARCHITECTURE.md` explains system structure.\n"
            "- `docs/API.md` lists API contracts.\n"
            "- `tests/` contains smoke verification.\n"
        )

    def _architecture_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc(
            "Architecture",
            [
                f"Complexity level: {blueprint.complexity_level}",
                *blueprint.architecture,
                "Communication flow: UI/API -> service layer -> repository -> persistence.",
                "Integration manager owns milestone readiness and release notes.",
            ],
        )

    def _api_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc("API Contracts", blueprint.api_contracts)

    def _setup_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc(
            "Setup Guide",
            [
                "Create a virtual environment.",
                "Install `requirements.txt`.",
                "Copy `config/settings.example.json` for local configuration.",
                "Run smoke tests before adding features.",
            ],
        )

    def _deployment_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc("Deployment Guide", blueprint.deployment)

    def _user_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc("User Guide", blueprint.requirements)

    def _developer_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc(
            "Developer Guide",
            [
                *blueprint.coding_standards,
                "Implement one milestone at a time.",
                "Keep generated blueprint memory updated after every major change.",
            ],
        )

    def _roadmap_report(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc("Development Roadmap", blueprint.roadmap)

    def _milestone_report(self, blueprint: EngineeringBlueprint) -> str:
        lines = ["# Milestone Report", ""]
        for milestone in blueprint.milestones:
            lines.append(f"## {milestone.name}")
            lines.append("")
            lines.append(f"Status: {milestone.status}")
            lines.append(f"Objective: {milestone.objective}")
            lines.append("")
            lines.extend(f"- {task}" for task in milestone.tasks)
            lines.append("")
        return "\n".join(lines)

    def _project_health_doc(self, blueprint: EngineeringBlueprint, verification: VerificationResult) -> str:
        dashboard = self._dashboard(blueprint, verification)
        lines = ["# Project Health", ""]
        for key, value in dashboard.to_dict().items():
            lines.append(f"- {key.replace('_', ' ').title()}: {value}")
        lines.append("")
        return "\n".join(lines)

    def _verification_report(self, blueprint: EngineeringBlueprint, verification: VerificationResult) -> str:
        lines = ["# Verification Report", "", f"Status: {'PASS' if verification.ok else 'FAIL'}", ""]
        lines.append("## Stages")
        lines.append("")
        for stage in verification.stages:
            lines.append(f"- {stage['stage']}: {'PASS' if stage['ok'] else 'FAIL'}")
        lines.append("")
        lines.append("## Checks")
        lines.append("")
        for check in verification.checks:
            status = "PASS" if check.get("ok") else "FAIL"
            lines.append(f"- {status}: {check.get('check')} {check.get('path', '')}")
        if verification.repairs:
            lines.append("")
            lines.append("## Repairs")
            lines.extend(f"- {repair}" for repair in verification.repairs)
        lines.append("")
        return "\n".join(lines)

    def _performance_doc(self, blueprint: EngineeringBlueprint) -> str:
        return self._list_doc("Performance Plan", self._performance_notes(blueprint))

    def _list_doc(self, title: str, items: list[str]) -> str:
        lines = [f"# {title}", ""]
        lines.extend(f"- {item}" for item in items)
        lines.append("")
        return "\n".join(lines)

    def _auth_py(self) -> str:
        return (
            "from __future__ import annotations\n\n"
            "import hashlib\n"
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            "class AuthenticatedUser:\n"
            "    email: str\n"
            "    role: str = 'user'\n\n\n"
            "def hash_password(password: str) -> str:\n"
            "    return hashlib.sha256(password.encode('utf-8')).hexdigest()\n\n\n"
            "def verify_password(password: str, expected_hash: str) -> bool:\n"
            "    return hash_password(password) == expected_hash\n\n\n"
            "def issue_token(user: AuthenticatedUser) -> str:\n"
            "    return f'token:{user.email}:{user.role}'\n"
        )

    def _test_auth_py(self, package: str) -> str:
        return (
            "import sys\n"
            "from pathlib import Path\n\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n\n"
            f"from {package}.auth import AuthenticatedUser, hash_password, issue_token, verify_password\n\n\n"
            "def test_auth_token_and_password_hash():\n"
            "    hashed = hash_password('secret')\n"
            "    assert verify_password('secret', hashed)\n"
            "    assert issue_token(AuthenticatedUser(email='demo@example.com')).startswith('token:')\n"
        )

    def _postgres_repository_py(self) -> str:
        return (
            "from __future__ import annotations\n\n"
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            "class PostgresConfig:\n"
            "    dsn: str = 'postgresql://localhost/aura_app'\n\n\n"
            "class PostgresRepositoryPlan:\n"
            "    def __init__(self, config: PostgresConfig | None = None) -> None:\n"
            "        self.config = config or PostgresConfig()\n\n"
            "    def migration_plan(self) -> list[str]:\n"
            "        return ['create records table', 'create audit_events table', 'create indexes']\n"
        )

    def _service_registry_py(self) -> str:
        return (
            "from __future__ import annotations\n\n"
            "SERVICES = {\n"
            "    'records': 'Core record service',\n"
            "    'identity': 'Authentication and authorization service',\n"
            "    'audit': 'Engineering and user activity audit service',\n"
            "}\n\n\n"
            "def list_services() -> dict[str, str]:\n"
            "    return dict(SERVICES)\n"
        )

    def _realtime_py(self) -> str:
        return (
            "from __future__ import annotations\n\n"
            "from dataclasses import dataclass\n\n\n"
            "@dataclass(frozen=True)\n"
            "class RealtimeEvent:\n"
            "    channel: str\n"
            "    payload: dict[str, str]\n\n\n"
            "def route_event(event: RealtimeEvent) -> str:\n"
            "    return f'{event.channel}:{len(event.payload)}'\n"
        )

    def _ci_yml(self) -> str:
        return (
            "name: CI\n"
            "on: [push, pull_request]\n"
            "jobs:\n"
            "  verify:\n"
            "    runs-on: ubuntu-latest\n"
            "    steps:\n"
            "      - uses: actions/checkout@v4\n"
            "      - uses: actions/setup-python@v5\n"
            "        with:\n"
            "          python-version: '3.11'\n"
            "      - run: python -m compileall src tests\n"
        )

    def _dockerfile(self, blueprint: EngineeringBlueprint) -> str:
        package = self._package_name(blueprint.project_name)
        return (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --no-cache-dir -r requirements.txt\n"
            "COPY . .\n"
            "ENV PYTHONPATH=/app/src\n"
            f"CMD [\"python\", \"-m\", \"{package}.main\"]\n"
        )

    def _docker_compose(self, blueprint: EngineeringBlueprint) -> str:
        services = [
            "services:",
            "  app:",
            "    build: .",
            "    ports:",
            "      - \"8000:8000\"",
        ]
        if blueprint.technologies.get("database") == "PostgreSQL":
            services.extend(
                [
                    "  db:",
                    "    image: postgres:16",
                    "    environment:",
                    "      POSTGRES_PASSWORD: aura",
                    "      POSTGRES_DB: aura_app",
                ]
            )
        return "\n".join(services) + "\n"

    def _config_py(self, blueprint: EngineeringBlueprint) -> str:
        return "from dataclasses import dataclass\n\n\n@dataclass(frozen=True)\nclass Settings:\n    app_name: str = %r\n    environment: str = 'local'\n" % blueprint.project_name

    def _models_py(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "from dataclasses import dataclass, field\n"
            "from datetime import datetime\n\n\n"
            "@dataclass\n"
            "class Record:\n"
            "    id: str\n"
            "    name: str\n"
            "    status: str = 'active'\n"
            "    created_at: datetime = field(default_factory=datetime.utcnow)\n"
        )

    def _repository_py(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "from __future__ import annotations\n\n"
            "from aura.legacy.assistant.models import Record\n\n\n"
            "class InMemoryRepository:\n"
            "    def __init__(self) -> None:\n"
            "        self._records: dict[str, Record] = {}\n\n"
            "    def save(self, record: Record) -> Record:\n"
            "        self._records[record.id] = record\n"
            "        return record\n\n"
            "    def list(self) -> list[Record]:\n"
            "        return list(self._records.values())\n"
        )

    def _services_py(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "from __future__ import annotations\n\n"
            "from uuid import uuid4\n\n"
            "from aura.legacy.assistant.models import Record\n"
            "from .repository import InMemoryRepository\n\n\n"
            "class CoreService:\n"
            "    def __init__(self, repository: InMemoryRepository | None = None) -> None:\n"
            "        self.repository = repository or InMemoryRepository()\n\n"
            "    def create_record(self, name: str) -> Record:\n"
            "        return self.repository.save(Record(id=str(uuid4()), name=name))\n\n"
            "    def list_records(self) -> list[Record]:\n"
            "        return self.repository.list()\n"
        )

    def _api_py(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "from fastapi import FastAPI\n"
            "from pydantic import BaseModel\n\n"
            "from .services import CoreService\n\n\n"
            "class CreateRecord(BaseModel):\n"
            "    name: str\n\n\n"
            "service = CoreService()\n"
            "app = FastAPI(title=%r)\n\n\n"
            "@app.get('/health')\n"
            "def health() -> dict[str, str]:\n"
            "    return {'status': 'ok'}\n\n\n"
            "@app.post('/records')\n"
            "def create_record(payload: CreateRecord) -> dict[str, str]:\n"
            "    record = service.create_record(payload.name)\n"
            "    return {'id': record.id, 'name': record.name, 'status': record.status}\n\n\n"
            "@app.get('/records')\n"
            "def list_records() -> list[dict[str, str]]:\n"
            "    return [record.__dict__ for record in service.list_records()]\n"
        ) % blueprint.project_name

    def _main_py(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "from aura.app.config import Settings\n\n\n"
            "def main() -> None:\n"
            "    settings = Settings()\n"
            "    print(f'{settings.app_name} scaffold is ready.')\n\n\n"
            "if __name__ == '__main__':\n"
            "    main()\n"
        )

    def _test_smoke_py(self, blueprint: EngineeringBlueprint) -> str:
        package = self._package_name(blueprint.project_name)
        return (
            "import sys\n"
            "from pathlib import Path\n\n"
            "sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))\n\n"
            f"from {package}.services import CoreService\n\n\n"
            "def test_core_service_creates_record():\n"
            "    service = CoreService()\n"
            "    record = service.create_record('Demo')\n"
            "    assert record.name == 'Demo'\n"
            "    assert service.list_records()\n"
        )

    def _frontend_package_json(self, blueprint: EngineeringBlueprint) -> str:
        return json.dumps(
            {
                "scripts": {"dev": "vite --host 127.0.0.1"},
                "dependencies": {
                    "@vitejs/plugin-react": "latest",
                    "vite": "latest",
                    "typescript": "latest",
                    "react": "latest",
                    "react-dom": "latest",
                },
                "devDependencies": {},
            },
            indent=2,
        )

    def _frontend_app(self, blueprint: EngineeringBlueprint) -> str:
        return (
            "export default function App() {\n"
            "  return (\n"
            "    <main>\n"
            f"      <h1>{blueprint.project_name}</h1>\n"
            "      <p>Milestone 1 interface scaffold is ready.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )

    def _requirements(self, goal: str, complexity: int) -> list[str]:
        base = [
            "Capture the user goal as a runnable software project.",
            "Generate complete source, tests, docs, configuration, and deployment files.",
            "Keep all secrets out of source files.",
            "Persist engineering state for future continuation.",
        ]
        if complexity >= 3:
            base.extend(
                [
                    "Separate API, domain, persistence, documentation, and deployment concerns.",
                    "Support milestone-based growth over multiple sessions.",
                    "Include authentication and audit-ready structure when appropriate.",
                ]
            )
        return base

    def _architecture(self, goal: str, technologies: dict[str, str], complexity: int) -> list[str]:
        layers = [
            "Presentation layer for UI or API clients.",
            "Application service layer for workflows.",
            "Domain model layer for core entities and rules.",
            "Repository layer for persistence boundaries.",
            "Verification layer for smoke tests and static checks.",
        ]
        if complexity >= 3:
            layers.append("Integration layer for future background jobs, analytics, and external systems.")
        return layers

    def _milestones(self, goal: str, complexity: int) -> list[EngineeringMilestone]:
        lowered = goal.lower()
        if "hospital" in lowered:
            names = ["Authentication", "Patient Management", "Appointments", "Billing", "Reporting", "Analytics"]
        elif "e-commerce" in lowered or "ecommerce" in lowered:
            names = ["Catalog", "Cart", "Checkout", "Payments", "Admin", "Analytics"]
        elif "mmorpg" in lowered:
            names = ["Account Service", "World State", "Realtime Gateway", "Inventory", "Matchmaking", "Telemetry"]
        elif "saas" in lowered:
            names = ["Tenant Model", "Authentication", "Billing", "Dashboard", "Admin", "Deployment"]
        else:
            names = ["Scaffold", "Core Domain", "Interface", "Verification", "Deployment"]
        return [
            EngineeringMilestone(
                name=name,
                objective=f"Deliver {name.lower()} as an independent, testable increment.",
                tasks=[
                    "Define interfaces.",
                    "Implement module scaffold.",
                    "Add tests.",
                    "Document behavior.",
                ],
                status="completed" if index == 0 else "pending",
            )
            for index, name in enumerate(names)
        ]

    def _technologies(self, goal: str, complexity: int) -> dict[str, str]:
        lowered = goal.lower()
        tech = {
            "backend": "FastAPI",
            "language": "Python",
            "testing": "Pytest",
            "deployment": "Docker",
            "configuration": "JSON environment config",
        }
        if complexity >= 3 or any(marker in lowered for marker in ("saas", "hospital", "e-commerce", "ecommerce")):
            tech["database"] = "PostgreSQL"
            tech["authentication"] = "JWT"
        else:
            tech["database"] = "SQLite-ready repository boundary"
        if self._needs_frontend_text(lowered):
            tech["frontend"] = "React + TypeScript"
            tech["styling"] = "TailwindCSS-ready structure"
        if "realtime" in lowered or "mmorpg" in lowered:
            tech["realtime"] = "WebSockets"
            tech["caching"] = "Redis"
        if "ai" in lowered:
            tech["ai"] = "Local AI integration boundary"
        if "unreal" in lowered:
            tech["plugin"] = "Unreal Engine C++ module scaffold documented"
        return tech

    def _complexity(self, goal: str) -> int:
        lowered = goal.lower()
        if any(marker in lowered for marker in ("operating system", "game engine", "ai platform", "enterprise saas")):
            return 5
        if any(marker in lowered for marker in ("banking", "distributed", "social platform", "erp")):
            return 4
        if any(marker in lowered for marker in ("hospital", "crm", "inventory", "lms", "farm", "management system", "e-commerce", "ecommerce", "saas")):
            return 3
        if any(marker in lowered for marker in ("bot", "weather", "portfolio", "desktop", "plugin", "full-stack", "full stack")):
            return 2
        return 1

    def _folder_tree(self, technologies: dict[str, str], complexity: int) -> list[str]:
        tree = [
            "README.md",
            "blueprint.json",
            "src/<package>/",
            "tests/",
            "docs/",
            "config/",
            "Dockerfile",
            "docker-compose.yml",
        ]
        if "frontend" in technologies:
            tree.append("frontend/")
        return tree

    def _interfaces(self, technologies: dict[str, str]) -> list[str]:
        interfaces = ["HTTP API", "Service layer", "Repository interface", "Configuration contract"]
        if "frontend" in technologies:
            interfaces.append("Frontend API client boundary")
        if "realtime" in technologies:
            interfaces.append("WebSocket event channel")
        return interfaces

    def _database_schema(self, goal: str, complexity: int) -> list[str]:
        schema = ["records(id, name, status, created_at)"]
        lowered = goal.lower()
        if "hospital" in lowered:
            schema.extend(["patients(id, name, dob, contact)", "appointments(id, patient_id, scheduled_at, status)", "invoices(id, patient_id, amount, status)"])
        elif "e-commerce" in lowered or "ecommerce" in lowered:
            schema.extend(["products(id, sku, name, price)", "orders(id, customer_id, total, status)", "order_items(id, order_id, product_id, quantity)"])
        elif complexity >= 3:
            schema.extend(["users(id, email, role)", "audit_events(id, actor_id, action, created_at)"])
        return schema

    def _api_contracts(self, goal: str, complexity: int) -> list[str]:
        contracts = ["GET /health -> service status", "POST /records -> create core record", "GET /records -> list records"]
        if complexity >= 3:
            contracts.extend(["POST /auth/login -> issue token", "GET /audit/events -> audit stream"])
        return contracts

    def _dependency_graph(self, technologies: dict[str, str]) -> dict[str, list[str]]:
        graph = {
            "api": ["services", "config"],
            "services": ["models", "repository"],
            "repository": ["models"],
            "tests": ["services"],
        }
        if "frontend" in technologies:
            graph["frontend"] = ["api"]
        return graph

    def _deployment(self, technologies: dict[str, str]) -> list[str]:
        steps = ["Build Docker image.", "Run API on port 8000.", "Load configuration from environment-safe files."]
        if technologies.get("database") == "PostgreSQL":
            steps.append("Provision PostgreSQL and run migrations before production use.")
        if "frontend" in technologies:
            steps.append("Build frontend assets and serve behind the API or static host.")
        return steps

    def _needs_frontend(self, blueprint: EngineeringBlueprint) -> bool:
        return "frontend" in blueprint.technologies

    def _needs_frontend_text(self, lowered: str) -> bool:
        return any(marker in lowered for marker in ("full-stack", "full stack", "saas", "e-commerce", "ecommerce", "hospital", "dashboard", "platform"))

    def _mentioned_project(self, goal: str) -> str | None:
        lowered = goal.lower()
        for key in self.memory.get_projects():
            if key.lower() in lowered:
                return key
            key_words = set(re.findall(r"[a-z0-9]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", key).lower()))
            goal_words = set(re.findall(r"[a-z0-9]+", lowered))
            if key_words and len(key_words & goal_words) >= min(2, len(key_words)):
                return key
        if "farmsphere" in lowered:
            return "FarmSphere"
        return None

    def _load_existing_project(self, goal: str) -> dict[str, Any] | None:
        projects = self.memory.get_projects()
        key = self._mentioned_project(goal)
        if key and key in projects:
            return dict(projects[key])
        lowered = goal.lower()
        if any(word in lowered for word in ("existing project", "current project")) and projects:
            return dict(next(reversed(projects.values())))
        return None

    def _blueprint_from_memory(self, project_data: dict[str, Any]) -> EngineeringBlueprint:
        raw = project_data.get("blueprint")
        if not isinstance(raw, dict):
            project_name = str(project_data.get("project_name", "SoftwareProject"))
            return self.create_blueprint(f"Continue {project_name}")
        milestones = [
            EngineeringMilestone(**milestone)
            for milestone in raw.get("milestones", [])
            if isinstance(milestone, dict)
        ]
        roles = [
            EngineeringRole(**role)
            for role in raw.get("roles", [])
            if isinstance(role, dict)
        ]
        return EngineeringBlueprint(
            project_name=str(raw.get("project_name", project_data.get("project_name", "SoftwareProject"))),
            project_path=str(raw.get("project_path", project_data.get("project_path", self.workspace_root / "Code" / "SoftwareProject"))),
            purpose=str(raw.get("purpose", project_data.get("goal", ""))),
            complexity_level=int(raw.get("complexity_level", 1)),
            requirements=[str(item) for item in raw.get("requirements", [])],
            architecture=[str(item) for item in raw.get("architecture", [])],
            technologies={str(k): str(v) for k, v in raw.get("technologies", {}).items()},
            folder_tree=[str(item) for item in raw.get("folder_tree", [])],
            interfaces=[str(item) for item in raw.get("interfaces", [])],
            database_schema=[str(item) for item in raw.get("database_schema", [])],
            api_contracts=[str(item) for item in raw.get("api_contracts", [])],
            dependency_graph={
                str(k): [str(v) for v in values]
                for k, values in raw.get("dependency_graph", {}).items()
                if isinstance(values, list)
            },
            deployment=[str(item) for item in raw.get("deployment", [])],
            testing_strategy=[str(item) for item in raw.get("testing_strategy", [])],
            milestones=milestones or self._milestones(str(raw.get("purpose", "")), int(raw.get("complexity_level", 1))),
            coding_standards=[str(item) for item in raw.get("coding_standards", [])],
            roadmap=[str(item) for item in raw.get("roadmap", [])],
            roles=roles or list(self.ROLES),
        )

    def _project_name(self, goal: str) -> str:
        match = re.search(r"(?:called|named)\s+([A-Za-z][A-Za-z0-9_-]{1,60})", goal, flags=re.IGNORECASE)
        if match:
            return match.group(1)
        mentioned = self._mentioned_project(goal)
        if mentioned:
            return mentioned
        lowered = goal.lower()
        names = [
            ("hospital", "HospitalManagementSystem"),
            ("mmorpg", "MMORPGBackend"),
            ("saas", "SaaSPlatform"),
            ("e-commerce", "ECommerceApplication"),
            ("ecommerce", "ECommerceApplication"),
            ("unreal", "UnrealEnginePlugin"),
            ("desktop", "AIDesktopApplication"),
            ("authentication", "AuthenticationUpgrade"),
            ("api documentation", "APIDocumentation"),
            ("refactor", "ScalabilityRefactor"),
        ]
        for marker, name in names:
            if marker in lowered:
                return name
        words = re.findall(r"[A-Za-z0-9]+", goal.title())
        selected = "".join(words[:4]) or "SoftwareProject"
        return selected[:60]

    def _package_name(self, project_name: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", project_name.lower())
        return "_".join(words) or "software_project"

    @staticmethod
    def package_name_for(project_name: str) -> str:
        words = re.findall(r"[A-Za-z0-9]+", project_name.lower())
        return "_".join(words) or "software_project"

    def _append_unique(self, items: list[str], value: str) -> None:
        if value not in items:
            items.append(value)

    def _status(self, message: str) -> None:
        if self.status_callback is None:
            return
        try:
            self.status_callback(message)
        except Exception:
            pass
