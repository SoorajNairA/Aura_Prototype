from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional, Protocol

from aura.infrastructure.persistence.memory_store import MemoryStore


@dataclass
class DomainCapability:
    name: str
    description: str
    keywords: list[str]
    applications: list[str] = field(default_factory=list)
    confidence_weight: float = 1.0


@dataclass
class DomainHealth:
    status: str = "healthy"
    architecture: float = 8.0
    maintainability: float = 8.0
    performance: float = 8.0
    reliability: float = 8.0
    coverage: float = 7.0
    recovery: float = 7.0
    documentation: float = 7.0
    benchmarks: float = 6.0
    complexity: float = 7.0
    engineering_quality: float = 7.5
    notes: list[str] = field(default_factory=list)


@dataclass
class DomainRoute:
    domain_id: str
    confidence: float
    matched_capabilities: list[str]
    required_applications: list[str]
    reason: str


@dataclass
class DomainExecutionResult:
    ok: bool
    message: str
    domain_id: str
    routes: list[DomainRoute]
    actions: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)


class DomainPack(Protocol):
    domain_id: str
    name: str
    description: str
    version: str
    dependencies: list[str]
    capabilities: list[DomainCapability]
    documentation_providers: list[str]
    workflow_library: list[str]
    verification_engine: str
    recovery_engine: str
    benchmarks: list[str]
    health: DomainHealth

    def score(self, request: str) -> DomainRoute:
        ...

    def execute(self, request: str, manager: "DomainManager", route: DomainRoute) -> DomainExecutionResult:
        ...


class BuiltinDomainPack:
    def __init__(
        self,
        domain_id: str,
        name: str,
        description: str,
        supported_tasks: list[str],
        capabilities: list[DomainCapability],
        version: str = "1.0.0",
        dependencies: Optional[list[str]] = None,
        documentation_providers: Optional[list[str]] = None,
        workflow_library: Optional[list[str]] = None,
        verification_engine: str = "domain_verification",
        recovery_engine: str = "domain_recovery",
        benchmarks: Optional[list[str]] = None,
        director: str = "operator",
    ) -> None:
        self.domain_id = domain_id
        self.name = name
        self.description = description
        self.supported_tasks = supported_tasks
        self.capabilities = capabilities
        self.version = version
        self.dependencies = dependencies or []
        self.documentation_providers = documentation_providers or []
        self.workflow_library = workflow_library or []
        self.verification_engine = verification_engine
        self.recovery_engine = recovery_engine
        self.benchmarks = benchmarks or []
        self.health = DomainHealth()
        self.director = director
        self.loaded = False

    def score(self, request: str) -> DomainRoute:
        lowered = request.lower()
        matched: list[str] = []
        applications: list[str] = []
        score = 0.0
        for capability in self.capabilities:
            hits = [keyword for keyword in capability.keywords if re.search(rf"\b{re.escape(keyword.lower())}\b", lowered)]
            if hits:
                matched.append(capability.name)
                applications.extend(capability.applications)
                score += capability.confidence_weight * len(hits)
        for task in self.supported_tasks:
            if task.lower() in lowered:
                score += 1.5
        confidence = min(0.99, round(score / 4.0, 2))
        return DomainRoute(
            domain_id=self.domain_id,
            confidence=confidence,
            matched_capabilities=sorted(set(matched)),
            required_applications=sorted(set(applications)),
            reason=f"Matched {len(matched)} domain capabilities.",
        )

    def execute(self, request: str, manager: "DomainManager", route: DomainRoute) -> DomainExecutionResult:
        self.loaded = True
        manager._write_domain_memory(
            self.domain_id,
            {
                "last_request": request,
                "matched_capabilities": route.matched_capabilities,
                "confidence": route.confidence,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if self.director == "software" and manager.software_executor is not None:
            outcome = manager.software_executor(request)
            return DomainExecutionResult(
                ok=bool(getattr(outcome, "ok", False)),
                message=str(getattr(outcome, "message", f"{self.name} completed.")),
                domain_id=self.domain_id,
                routes=[route],
                actions=list(getattr(outcome, "actions", [])),
                artifacts=list(getattr(outcome, "artifacts", [])),
            )
        if manager.operator_executor is not None:
            outcome = manager.operator_executor(request)
            plan = getattr(outcome, "plan", None)
            actions = []
            if plan is not None:
                actions = [
                    {
                        "id": step.id,
                        "action": step.kind,
                        "target": step.target,
                        "status": step.status,
                    }
                    for step in getattr(plan, "steps", [])
                ]
            return DomainExecutionResult(
                ok=bool(getattr(outcome, "ok", True)),
                message=str(getattr(outcome, "message", f"{self.name} completed.")),
                domain_id=self.domain_id,
                routes=[route],
                actions=actions,
                observations=list(getattr(outcome, "observations", [])),
            )
        return DomainExecutionResult(
            ok=True,
            message=f"{self.name} route prepared.",
            domain_id=self.domain_id,
            routes=[route],
            observations=[{"request": request, "route": asdict(route)}],
        )


class DomainManager:
    def __init__(
        self,
        memory: MemoryStore,
        domains_dir: Path,
        operator_executor: Optional[Callable[[str], Any]] = None,
        software_executor: Optional[Callable[[str], Any]] = None,
        min_confidence: float = 0.35,
        include_legacy_unreal: bool = False,
    ) -> None:
        self.memory = memory
        self.domains_dir = domains_dir
        self.operator_executor = operator_executor
        self.software_executor = software_executor
        self.min_confidence = min_confidence
        self.include_legacy_unreal = include_legacy_unreal
        self.domains: dict[str, DomainPack] = {}
        self.active_domains: set[str] = set()
        self.routing_history: list[dict[str, Any]] = []
        self.register_builtin_domains()
        self.discover_domains()

    def register(self, domain: DomainPack) -> None:
        self._validate_domain(domain)
        self.domains[domain.domain_id] = domain
        self._write_domain_memory(domain.domain_id, {"registered_at": datetime.now(timezone.utc).isoformat()})

    def remove(self, domain_id: str) -> bool:
        existed = domain_id in self.domains
        self.domains.pop(domain_id, None)
        self.active_domains.discard(domain_id)
        return existed

    def load(self, domain_id: str) -> bool:
        domain = self.domains.get(domain_id)
        if domain is None:
            return False
        self.active_domains.add(domain_id)
        setattr(domain, "loaded", True)
        return True

    def unload_inactive(self, keep: Optional[set[str]] = None) -> None:
        keep = keep or set()
        for domain_id in list(self.active_domains):
            if domain_id not in keep:
                domain = self.domains.get(domain_id)
                if domain is not None:
                    setattr(domain, "loaded", False)
                self.active_domains.discard(domain_id)

    def discover_domains(self) -> None:
        if not self.domains_dir.exists():
            return
        for manifest in sorted(self.domains_dir.glob("*/domain.json")):
            try:
                payload = json.loads(manifest.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            capabilities = [
                DomainCapability(
                    name=str(item.get("name", "")),
                    description=str(item.get("description", "")),
                    keywords=[str(keyword) for keyword in item.get("keywords", [])],
                    applications=[str(app) for app in item.get("applications", [])],
                    confidence_weight=float(item.get("confidence_weight", 1.0)),
                )
                for item in payload.get("capabilities", [])
                if isinstance(item, dict)
            ]
            domain = BuiltinDomainPack(
                domain_id=str(payload.get("domain_id", manifest.parent.name)),
                name=str(payload.get("name", manifest.parent.name)),
                description=str(payload.get("description", "")),
                supported_tasks=[str(item) for item in payload.get("supported_tasks", [])],
                capabilities=capabilities,
                version=str(payload.get("version", "1.0.0")),
                dependencies=[str(item) for item in payload.get("dependencies", [])],
                documentation_providers=[str(item) for item in payload.get("documentation_providers", [])],
                workflow_library=[str(item) for item in payload.get("workflow_library", [])],
                verification_engine=str(payload.get("verification_engine", "domain_verification")),
                recovery_engine=str(payload.get("recovery_engine", "domain_recovery")),
                benchmarks=[str(item) for item in payload.get("benchmarks", [])],
                director=str(payload.get("director", "operator")),
            )
            self.register(domain)

    def route(self, request: str) -> list[DomainRoute]:
        candidates = [domain.score(request) for domain in self.domains.values()]
        candidates = [route for route in candidates if route.confidence >= self.min_confidence]
        candidates.sort(key=lambda route: route.confidence, reverse=True)
        if not candidates:
            return []
        selected = self._collaboration_routes(request, candidates)
        self.routing_history.append(
            {
                "request": request,
                "routes": [asdict(route) for route in selected],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return selected

    def can_handle(self, request: str) -> bool:
        return bool(self.route(request))

    def execute(self, request: str) -> DomainExecutionResult:
        routes = self.route(request)
        if not routes:
            return DomainExecutionResult(False, "No suitable domain found.", "", [])
        results: list[DomainExecutionResult] = []
        active = {route.domain_id for route in routes}
        for route in routes:
            self.load(route.domain_id)
            domain = self.domains[route.domain_id]
            results.append(domain.execute(request, self, route))
        self.unload_inactive(keep=active)
        ok = all(result.ok for result in results)
        actions = [action for result in results for action in result.actions]
        artifacts = [artifact for result in results for artifact in result.artifacts]
        observations = [obs for result in results for obs in result.observations]
        primary = results[0]
        names = ", ".join(self.domains[route.domain_id].name for route in routes if route.domain_id in self.domains)
        message = primary.message if len(results) == 1 else f"Done. Coordinated {names}."
        return DomainExecutionResult(
            ok=ok,
            message=message,
            domain_id=primary.domain_id,
            routes=routes,
            actions=actions,
            artifacts=artifacts,
            observations=observations,
        )

    def health_report(self) -> dict[str, Any]:
        return {
            domain_id: {
                "name": domain.name,
                "version": domain.version,
                "status": domain.health.status,
                "engineering_quality": domain.health.engineering_quality,
                "loaded": domain_id in self.active_domains,
                "capabilities": [capability.name for capability in domain.capabilities],
            }
            for domain_id, domain in sorted(self.domains.items())
        }

    def domain_memory_path(self, domain_id: str) -> Path:
        return self.memory.memory_dir / "domains" / domain_id / "memory.json"

    def _write_domain_memory(self, domain_id: str, event: dict[str, Any]) -> None:
        path = self.domain_memory_path(domain_id)
        rows = []
        if path.is_file():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                rows = payload if isinstance(payload, list) else []
            except json.JSONDecodeError:
                rows = []
        rows.append(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows[-200:], indent=2), encoding="utf-8")

    def _validate_domain(self, domain: DomainPack) -> None:
        if not domain.domain_id or not re.match(r"^[a-z0-9_.-]+$", domain.domain_id):
            raise ValueError("Domain id must be lowercase and filesystem safe.")
        if not domain.name:
            raise ValueError("Domain name is required.")
        if not domain.capabilities:
            raise ValueError("Domain must declare at least one capability.")

    def _collaboration_routes(self, request: str, candidates: list[DomainRoute]) -> list[DomainRoute]:
        lowered = request.lower()
        collaboration_terms = {
            "multiplayer": {"unreal", "git", "networking", "documentation"},
            "publish": {"git", "documentation"},
            "asset": {"unreal", "blender"},
            "full stack": {"webdev", "git", "documentation"},
        }
        selected_ids: set[str] = {candidates[0].domain_id}
        for term, domain_ids in collaboration_terms.items():
            if term in lowered:
                selected_ids.update(domain_ids)
        selected = [route for route in candidates if route.domain_id in selected_ids]
        if len(selected) <= 1:
            return candidates[:1]
        return selected

    def register_builtin_domains(self) -> None:
        builtins: list[DomainPack] = []
        if self.include_legacy_unreal:
            # Unreal is a large legacy experiment. Import it only when a caller
            # explicitly opts in so normal AURA startup stays lightweight.
            from aura.legacy.unreal import create_unreal_domain

            builtins.append(
                create_unreal_domain(
                    memory_dir=self.memory.memory_dir / "domains" / "unreal",
                    operator_executor=self.operator_executor,
                )
            )

        builtins.extend([
            BuiltinDomainPack(
                domain_id="blender",
                name="Blender Domain",
                description="Modeling, materials, animation, rendering, nodes, and asset export.",
                supported_tasks=["blender", "render", "rigging", "uv", "material"],
                capabilities=[
                    DomainCapability("modeling", "Operate Blender modeling workflows.", ["blender", "model", "mesh", "uv"], ["blender"], 1.1),
                    DomainCapability("rendering", "Render and export visual assets.", ["render", "material", "animation"], ["blender"], 1.0),
                ],
                documentation_providers=["Blender manual cache", "Blender Python API"],
                workflow_library=["open_scene", "render_output", "export_asset"],
                benchmarks=["Render scene", "Create material", "Export FBX"],
                director="operator",
            ),
            BuiltinDomainPack(
                domain_id="webdev",
                name="Web Development Domain",
                description="Websites, web apps, dashboards, frontend, backend, and APIs.",
                supported_tasks=["web app", "dashboard", "api", "frontend", "backend", "react", "full stack"],
                capabilities=[
                    DomainCapability("static_site", "Generate static sites and landing pages.", ["landing page"], ["vscode"], 1.0),
                    DomainCapability("web_app", "Generate app/API projects.", ["web app", "dashboard", "api", "frontend", "backend", "react", "full stack"], ["vscode"], 1.0),
                ],
                documentation_providers=["Local web development notes"],
                workflow_library=["static_site", "flask_app", "dashboard"],
                benchmarks=["Create website", "Create API", "Run tests"],
                director="software",
            ),
            BuiltinDomainPack(
                domain_id="git",
                name="Git Domain",
                description="Version control, commits, merges, releases, and publishing workflows.",
                supported_tasks=["commit", "merge", "release", "push", "github"],
                capabilities=[
                    DomainCapability("version_control", "Coordinate Git and GitHub workflows.", ["git", "commit", "merge", "push", "github", "release"], ["vscode", "chrome"], 1.0),
                ],
                workflow_library=["commit", "resolve_conflict", "publish_release"],
                benchmarks=["Commit changes", "Publish release"],
                director="operator",
            ),
            BuiltinDomainPack(
                domain_id="networking",
                name="Networking Domain",
                description="Multiplayer, sockets, APIs, replication, and network architecture.",
                supported_tasks=["multiplayer", "networking", "replication", "socket"],
                capabilities=[
                    DomainCapability("multiplayer", "Reason about multiplayer and replication workflows.", ["multiplayer", "networking", "replication", "socket"], ["vscode", "unreal"], 1.0),
                ],
                workflow_library=["network_design", "replication_check"],
                benchmarks=["Create multiplayer scaffold"],
                director="software",
            ),
            BuiltinDomainPack(
                domain_id="documentation",
                name="Documentation Domain",
                description="Architecture docs, reports, README, API documentation, and release notes.",
                supported_tasks=["documentation", "docs", "release notes", "api documentation"],
                capabilities=[
                    DomainCapability("documentation", "Generate and verify docs.", ["documentation", "docs", "release notes", "api documentation"], ["vscode"], 1.0),
                ],
                workflow_library=["write_readme", "write_report", "api_docs"],
                benchmarks=["Generate report"],
                director="software",
            ),
        ])
        for domain in builtins:
            self.register(domain)
