from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aura.verification.adapters.architecture_analysis import ArchitectureGraph, ArchitectureIntelligenceEngine
from aura.infrastructure.persistence.memory_store import MemoryStore
from aura.legacy.assistant.operator_quality import OperatorBenchmark, WorkflowAnalytics


@dataclass
class ModuleAudit:
    path: str
    subsystem: str
    lines: int
    imports: int
    classes: int
    functions: int
    public_interfaces: int
    branch_count: int
    complexity: int
    max_nesting: int
    fan_in: int = 0
    fan_out: int = 0
    instability: float = 0.0
    largest_functions: list[dict[str, Any]] = field(default_factory=list)
    god_objects: list[dict[str, Any]] = field(default_factory=list)
    smells: list[str] = field(default_factory=list)


@dataclass
class SubsystemScore:
    subsystem: str
    architecture: float
    maintainability: float
    performance: float
    readability: float
    complexity: float
    scalability: float
    documentation: float
    testing: float
    reliability: float
    security: float
    extensibility: float
    consistency: float
    overall: float


@dataclass
class DebtItem:
    title: str
    priority: int
    affected_modules: list[str]
    risk: str
    estimated_effort: str
    suggested_solution: str
    estimated_gain: str


@dataclass
class ChiefArchitectAudit:
    generated_at: str
    overall_score: float
    subsystem_scores: list[SubsystemScore]
    modules: list[ModuleAudit]
    dependency_graph: dict[str, Any]
    circular_dependencies: list[list[str]]
    duplicate_logic: list[str]
    dead_code_candidates: list[str]
    architecture_violations: list[str]
    security_findings: list[str]
    performance_findings: list[str]
    missing_tests: list[str]
    missing_documentation: list[str]
    technical_debt: list[DebtItem]
    optimization_roadmap: list[DebtItem]
    dashboard: dict[str, Any]


class ChiefArchitect:
    """Read-only engineering reviewer for AURA.

    ChiefArchitect can inspect, score, and report architecture quality. It does
    not modify production source files; report generation writes markdown and
    JSON artifacts only.
    """

    REPORT_FILES = {
        "ArchitectureAudit.md": "Architecture Audit",
        "PerformanceAudit.md": "Performance Audit",
        "DependencyReport.md": "Dependency Report",
        "ComplexityReport.md": "Complexity Report",
        "SecurityAudit.md": "Security Audit",
        "TestCoverageReport.md": "Test Coverage Report",
        "DeadCodeReport.md": "Dead Code Report",
        "TechnicalDebt.md": "Technical Debt",
        "OptimizationRoadmap.md": "Optimization Roadmap",
        "EngineeringScorecard.md": "Engineering Scorecard",
    }

    def __init__(
        self,
        project_root: Path,
        memory: Optional[MemoryStore] = None,
        architecture: Optional[ArchitectureIntelligenceEngine] = None,
        report_dir: Optional[Path] = None,
    ) -> None:
        self.project_root = project_root.resolve()
        self.memory = memory
        self.architecture = architecture or ArchitectureIntelligenceEngine(self.project_root, memory)
        self.report_dir = report_dir or self.project_root / "docs" / "engineering"
        self.audit_cache_path = (
            memory.memory_dir / "chief_architect_audit.json"
            if memory is not None
            else self.project_root / "logs" / "chief_architect_audit.json"
        )

    def audit(self, force_refresh: bool = False) -> ChiefArchitectAudit:
        graph = self.architecture.graph(force_refresh=force_refresh)
        modules = self._module_audits(graph)
        dependency_graph = self._dependency_graph(graph)
        circular_dependencies = self._circular_dependencies(dependency_graph)
        duplicate_logic = self._duplicate_logic(graph)
        dead_code = list(graph.health.get("dead_code_candidates", [])) or self._dead_code_candidates(graph)
        violations = self._architecture_violations(graph)
        security = self._security_findings(modules)
        performance = self._performance_findings(modules)
        missing_tests = self._missing_tests(graph)
        missing_docs = list(graph.health.get("missing_documentation", []))
        debt = self._technical_debt(
            modules,
            circular_dependencies,
            duplicate_logic,
            dead_code,
            violations,
            security,
            performance,
            missing_tests,
            missing_docs,
        )
        scores = self._subsystem_scores(graph, modules, debt)
        overall = round(sum(score.overall for score in scores) / max(len(scores), 1), 1)
        roadmap = sorted(debt, key=lambda item: item.priority)[:12]
        audit = ChiefArchitectAudit(
            generated_at=datetime.now(timezone.utc).isoformat(),
            overall_score=overall,
            subsystem_scores=scores,
            modules=modules,
            dependency_graph=dependency_graph,
            circular_dependencies=circular_dependencies,
            duplicate_logic=duplicate_logic,
            dead_code_candidates=dead_code,
            architecture_violations=violations,
            security_findings=security,
            performance_findings=performance,
            missing_tests=missing_tests,
            missing_documentation=missing_docs,
            technical_debt=debt,
            optimization_roadmap=roadmap,
            dashboard=self._dashboard(overall, graph, modules, debt, scores),
        )
        self._persist_memory(audit)
        return audit

    def generate_reports(self, audit: Optional[ChiefArchitectAudit] = None) -> dict[str, Path]:
        audit = audit or self.audit()
        self.report_dir.mkdir(parents=True, exist_ok=True)
        reports = {
            "ArchitectureAudit.md": self._architecture_report(audit),
            "PerformanceAudit.md": self._list_report(
                "Performance Audit",
                audit.performance_findings,
                "No major performance bottlenecks detected by static audit.",
            ),
            "DependencyReport.md": self._dependency_report(audit),
            "ComplexityReport.md": self._complexity_report(audit),
            "SecurityAudit.md": self._list_report(
                "Security Audit",
                audit.security_findings,
                "No high-confidence security findings detected by static audit.",
            ),
            "TestCoverageReport.md": self._list_report(
                "Test Coverage Report",
                audit.missing_tests,
                "All indexed production modules have at least one related test or acceptance path.",
            ),
            "DeadCodeReport.md": self._list_report(
                "Dead Code Report",
                audit.dead_code_candidates,
                "No strong dead-code candidates detected. Review manually before removing anything.",
            ),
            "TechnicalDebt.md": self._debt_report("Technical Debt", audit.technical_debt),
            "OptimizationRoadmap.md": self._debt_report("Optimization Roadmap", audit.optimization_roadmap),
            "EngineeringScorecard.md": self._scorecard_report(audit),
        }
        written: dict[str, Path] = {}
        for name, content in reports.items():
            path = self.report_dir / name
            path.write_text(content, encoding="utf-8")
            written[name] = path
        return written

    def review_design(self, proposal: str) -> dict[str, Any]:
        audit = self.audit()
        lowered = proposal.lower()
        affected = [
            module.path
            for module in audit.modules
            if module.path and any(token in lowered for token in module.path.lower().split("/"))
        ][:12]
        risks = []
        if "computer" in lowered or "desktop" in lowered:
            risks.append("Desktop automation changes must preserve provider boundaries and safety gating.")
        if "tool" in lowered:
            risks.append("Tool changes must keep unknown commands rejected by default.")
        if "voice" in lowered:
            risks.append("Voice changes must preserve fallback speech so AURA never becomes silent.")
        if not risks:
            risks.append("Run architecture, acceptance, and affected subsystem tests before merge.")
        return {
            "affected_modules": affected,
            "risks": risks,
            "recommended_tests": self._tests_for_proposal(proposal),
            "architecture_score_before": audit.overall_score,
            "decision": "review_required" if risks else "low_risk",
        }

    def _module_audits(self, graph: ArchitectureGraph) -> list[ModuleAudit]:
        audits: list[ModuleAudit] = []
        fan_in = Counter(edge.target for edge in graph.edges)
        fan_out = Counter(edge.source for edge in graph.edges)
        for node in graph.nodes.values():
            if node.kind != "module":
                continue
            path = self.project_root / node.path
            if not path.is_file() or path.suffix != ".py":
                continue
            metrics = self._python_metrics(path)
            incoming = fan_in[node.id]
            outgoing = fan_out[node.id]
            instability = round(outgoing / max(incoming + outgoing, 1), 2)
            smells = self._smells(node.path, metrics, incoming, outgoing)
            audits.append(
                ModuleAudit(
                    path=node.path,
                    subsystem=node.subsystem,
                    lines=metrics["lines"],
                    imports=metrics["imports"],
                    classes=metrics["classes"],
                    functions=metrics["functions"],
                    public_interfaces=len(node.public_interfaces),
                    branch_count=metrics["branch_count"],
                    complexity=metrics["complexity"],
                    max_nesting=metrics["max_nesting"],
                    fan_in=incoming,
                    fan_out=outgoing,
                    instability=instability,
                    largest_functions=metrics["largest_functions"],
                    god_objects=metrics["god_objects"],
                    smells=smells,
                )
            )
        return sorted(audits, key=lambda item: item.lines, reverse=True)

    def _python_metrics(self, path: Path) -> dict[str, Any]:
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return {
                "lines": source.count("\n") + 1,
                "imports": 0,
                "classes": 0,
                "functions": 0,
                "branch_count": 0,
                "complexity": 1,
                "max_nesting": 0,
                "largest_functions": [],
                "god_objects": [],
            }
        functions: list[dict[str, Any]] = []
        god_objects: list[dict[str, Any]] = []
        branch_nodes = tuple(
            node
            for node in (
            ast.If,
            ast.For,
            ast.AsyncFor,
            ast.While,
            ast.Try,
            ast.ExceptHandler,
            ast.With,
            ast.AsyncWith,
            ast.BoolOp,
            ast.IfExp,
            getattr(ast, "Match", None),
            )
            if node is not None
        )
        branch_count = sum(1 for node in ast.walk(tree) if isinstance(node, branch_nodes))
        imports = sum(1 for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom)))
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        top_functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                functions.append(
                    {
                        "name": node.name,
                        "line": node.lineno,
                        "lines": self._node_lines(node),
                        "branches": sum(1 for child in ast.walk(node) if isinstance(child, branch_nodes)),
                    }
                )
        for cls in classes:
            methods = [item for item in cls.body if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))]
            fields = self._class_fields(cls)
            branches = sum(1 for child in ast.walk(cls) if isinstance(child, branch_nodes))
            if len(methods) >= 18 or self._node_lines(cls) >= 450 or branches >= 80:
                god_objects.append(
                    {
                        "class": cls.name,
                        "line": cls.lineno,
                        "methods": len(methods),
                        "fields": len(fields),
                        "lines": self._node_lines(cls),
                        "decision_points": branches,
                    }
                )
        largest = sorted(functions, key=lambda item: item["lines"], reverse=True)[:5]
        return {
            "lines": source.count("\n") + 1,
            "imports": imports,
            "classes": len(classes),
            "functions": len(functions),
            "branch_count": branch_count,
            "complexity": branch_count + 1,
            "max_nesting": self._max_nesting(tree),
            "largest_functions": largest,
            "god_objects": god_objects,
            "top_level_functions": len(top_functions),
        }

    def _node_lines(self, node: ast.AST) -> int:
        end = getattr(node, "end_lineno", getattr(node, "lineno", 0))
        start = getattr(node, "lineno", end)
        return max(1, int(end) - int(start) + 1)

    def _class_fields(self, cls: ast.ClassDef) -> set[str]:
        fields: set[str] = set()
        for node in ast.walk(cls):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self":
                fields.add(node.attr)
        return fields

    def _max_nesting(self, tree: ast.AST) -> int:
        branch_types = tuple(
            node
            for node in (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.With,
                ast.AsyncWith,
                getattr(ast, "Match", None),
            )
            if node is not None
        )

        def walk(node: ast.AST, depth: int) -> int:
            next_depth = depth + 1 if isinstance(node, branch_types) else depth
            child_depths = [walk(child, next_depth) for child in ast.iter_child_nodes(node)]
            return max([next_depth, *child_depths])

        return walk(tree, 0)

    def _smells(self, path: str, metrics: dict[str, Any], fan_in: int, fan_out: int) -> list[str]:
        smells: list[str] = []
        if metrics["lines"] > 900:
            smells.append("oversized module")
        if metrics["complexity"] > 120:
            smells.append("high branch complexity")
        if metrics["max_nesting"] > 6:
            smells.append("deep nesting")
        if fan_out > 20:
            smells.append("high efferent coupling")
        if fan_in > 20:
            smells.append("high afferent coupling")
        if any(item["lines"] > 80 for item in metrics["largest_functions"]):
            smells.append("long method")
        if metrics["god_objects"]:
            smells.append("god object candidate")
        if path.endswith(("orchestrator.py", "software_director.py")) and metrics["lines"] > 700:
            smells.append("orchestration module needs decomposition watch")
        return smells

    def _dependency_graph(self, graph: ArchitectureGraph) -> dict[str, Any]:
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in graph.edges:
            if edge.relationship in {"imports", "depends_on"}:
                adjacency[edge.source].append(edge.target)
        return {key: sorted(set(value)) for key, value in sorted(adjacency.items())}

    def _circular_dependencies(self, adjacency: dict[str, list[str]]) -> list[list[str]]:
        cycles: list[list[str]] = []
        visiting: list[str] = []
        visited: set[str] = set()

        def dfs(node: str) -> None:
            if node in visiting:
                cycle = visiting[visiting.index(node):] + [node]
                if len(cycle) > 2 and cycle not in cycles:
                    cycles.append(cycle)
                return
            if node in visited:
                return
            visiting.append(node)
            for target in adjacency.get(node, []):
                dfs(target)
            visiting.pop()
            visited.add(node)

        for node in adjacency:
            dfs(node)
        return cycles[:20]

    def _duplicate_logic(self, graph: ArchitectureGraph) -> list[str]:
        by_name: dict[str, list[str]] = defaultdict(list)
        for node in graph.nodes.values():
            if node.kind in {"function", "class"}:
                by_name[node.name.lower()].append(node.id)
        duplicates = []
        for name, ids in sorted(by_name.items()):
            if len(ids) >= 3 and name not in {"main", "run", "execute", "can_handle"}:
                duplicates.append(f"{name}: {', '.join(ids[:6])}")
        return duplicates[:30]

    def _architecture_violations(self, graph: ArchitectureGraph) -> list[str]:
        violations: list[str] = []
        for edge in graph.edges:
            if edge.relationship not in {"imports", "depends_on"}:
                continue
            source = graph.nodes.get(edge.source)
            target = graph.nodes.get(edge.target)
            if source is None or target is None:
                continue
            if source.subsystem == "tools" and target.subsystem in {"gui", "voice"}:
                violations.append(f"{source.path} depends upward on {target.path}")
            if source.subsystem == "memory" and target.subsystem in {"executive", "computer_operation"}:
                violations.append(f"{source.path} depends on higher-level subsystem {target.path}")
        return violations[:30]

    def _security_findings(self, modules: list[ModuleAudit]) -> list[str]:
        findings: list[str] = []
        patterns = {
            "eval(": "Dynamic eval usage",
            "exec(": "Dynamic exec usage",
            "shell=True": "Subprocess shell=True usage",
            "subprocess.run": "Subprocess invocation requires argument review",
            "subprocess.Popen": "Process launch path requires allowlist review",
            "os.startfile": "Desktop/file launch needs safe file-type checks",
            "webbrowser.open": "URL launch should validate URL scheme",
        }
        for module in modules:
            path = self.project_root / module.path
            text = path.read_text(encoding="utf-8", errors="ignore")
            for pattern, label in patterns.items():
                if pattern in text:
                    severity = "HIGH" if pattern in {"eval(", "exec(", "shell=True"} else "REVIEW"
                    findings.append(f"{severity}: {label} in {module.path}")
        return sorted(set(findings))[:50]

    def _performance_findings(self, modules: list[ModuleAudit]) -> list[str]:
        findings: list[str] = []
        for module in modules:
            if module.lines > 900:
                findings.append(f"Oversized module may slow review and maintenance: {module.path} ({module.lines} lines)")
            if module.branch_count > 120:
                findings.append(f"High decision count in {module.path}: {module.branch_count}")
            path = self.project_root / module.path
            text = path.read_text(encoding="utf-8", errors="ignore")
            if "rglob(" in text or "os.walk(" in text:
                findings.append(f"Repeated filesystem scan candidate: {module.path}")
            if "subprocess.check_output" in text or "subprocess.run" in text:
                findings.append(f"Blocking subprocess call candidate: {module.path}")
        operator_summary = self._operator_quality_summary()
        analytics = operator_summary.get("analytics", {})
        benchmark = operator_summary.get("benchmark", {})
        if analytics.get("success_rate", 1.0) < 0.9 and analytics.get("success_rate", 0.0) > 0:
            findings.append(f"Operator success rate below Q1 target: {analytics.get('success_rate')}")
        if benchmark.get("success_rate", 1.0) < 0.9 and benchmark.get("runs", 0) > 0:
            findings.append(f"Operator benchmark success below Q1 target: {benchmark.get('success_rate')}")
        return sorted(set(findings))[:50]

    def _missing_tests(self, graph: ArchitectureGraph) -> list[str]:
        missing = []
        for node in graph.nodes.values():
            if node.kind == "module" and node.subsystem not in {"tests", "documentation"} and not node.related_tests:
                if not node.path.endswith("__init__.py"):
                    missing.append(node.path)
        return sorted(missing)[:50]

    def _dead_code_candidates(self, graph: ArchitectureGraph) -> list[str]:
        inbound = Counter()
        for edge in graph.edges:
            if edge.relationship == "imports":
                inbound.update([edge.target])
        candidates = []
        for node in graph.nodes.values():
            if node.kind != "module":
                continue
            if node.name in {"main", "__init__", "orchestrator"}:
                continue
            if node.subsystem in {"tests", "documentation"}:
                continue
            if inbound[node.id] == 0:
                candidates.append(node.path)
        return sorted(candidates)[:30]

    def _technical_debt(
        self,
        modules: list[ModuleAudit],
        cycles: list[list[str]],
        duplicates: list[str],
        dead_code: list[str],
        violations: list[str],
        security: list[str],
        performance: list[str],
        missing_tests: list[str],
        missing_docs: list[str],
    ) -> list[DebtItem]:
        debt: list[DebtItem] = []
        oversized = [module for module in modules if module.lines > 900 or module.god_objects]
        for module in oversized[:8]:
            debt.append(
                DebtItem(
                    title=f"Decompose {module.path}",
                    priority=1 if module.lines > 1400 else 2,
                    affected_modules=[module.path],
                    risk="high" if module.lines > 1400 else "medium",
                    estimated_effort="1-3 days",
                    suggested_solution="Split orchestration, domain logic, and report generation into focused collaborators.",
                    estimated_gain="+15-25% maintainability",
                )
            )
        if cycles:
            debt.append(
                DebtItem(
                    title="Remove circular dependencies",
                    priority=1,
                    affected_modules=cycles[0],
                    risk="high",
                    estimated_effort="0.5-2 days",
                    suggested_solution="Move shared contracts into lower-level modules and depend on protocols.",
                    estimated_gain="+10% reliability and testability",
                )
            )
        if duplicates:
            debt.append(
                DebtItem(
                    title="Consolidate duplicate logic",
                    priority=3,
                    affected_modules=duplicates[:5],
                    risk="medium",
                    estimated_effort="1 day",
                    suggested_solution="Extract repeated parsing/validation/reporting patterns into small local helpers.",
                    estimated_gain="+8% consistency",
                )
            )
        if security:
            debt.append(
                DebtItem(
                    title="Review unsafe execution surfaces",
                    priority=1,
                    affected_modules=security[:8],
                    risk="high",
                    estimated_effort="0.5-1 day",
                    suggested_solution="Keep allowlists, validate schemes/file types, and preserve confirmation gates.",
                    estimated_gain="+12% security posture",
                )
            )
        if performance:
            debt.append(
                DebtItem(
                    title="Reduce blocking and repeated scans",
                    priority=2,
                    affected_modules=performance[:8],
                    risk="medium",
                    estimated_effort="1-2 days",
                    suggested_solution="Cache indexes, move slow work off startup/UI paths, and reuse architecture graph data.",
                    estimated_gain="-300ms to -800ms on repeated review paths",
                )
            )
        if missing_tests:
            debt.append(
                DebtItem(
                    title="Add missing subsystem tests",
                    priority=2,
                    affected_modules=missing_tests[:10],
                    risk="medium",
                    estimated_effort="1-2 days",
                    suggested_solution="Add narrow regression tests for modules without direct coverage.",
                    estimated_gain="+10% regression confidence",
                )
            )
        if missing_docs:
            debt.append(
                DebtItem(
                    title="Document low-context modules",
                    priority=4,
                    affected_modules=missing_docs[:10],
                    risk="low",
                    estimated_effort="0.5 day",
                    suggested_solution="Add architecture notes or concise module docstrings for ownership boundaries.",
                    estimated_gain="+6% maintainability",
                )
            )
        if dead_code:
            debt.append(
                DebtItem(
                    title="Review dead-code candidates",
                    priority=4,
                    affected_modules=dead_code[:10],
                    risk="low",
                    estimated_effort="0.5 day",
                    suggested_solution="Confirm usage manually before removal; preserve compatibility shims if needed.",
                    estimated_gain="-small maintenance surface",
                )
            )
        if violations:
            debt.append(
                DebtItem(
                    title="Fix architecture layering violations",
                    priority=1,
                    affected_modules=violations[:8],
                    risk="high",
                    estimated_effort="1 day",
                    suggested_solution="Reverse dependencies through interfaces or move contracts downward.",
                    estimated_gain="+12% architecture consistency",
                )
            )
        return sorted(debt, key=lambda item: item.priority)

    def _subsystem_scores(
        self,
        graph: ArchitectureGraph,
        modules: list[ModuleAudit],
        debt: list[DebtItem],
    ) -> list[SubsystemScore]:
        modules_by_subsystem: dict[str, list[ModuleAudit]] = defaultdict(list)
        for module in modules:
            modules_by_subsystem[module.subsystem].append(module)
        debt_text = " ".join(" ".join(item.affected_modules) for item in debt).lower()
        scores: list[SubsystemScore] = []
        for subsystem, rows in sorted(modules_by_subsystem.items()):
            avg_lines = sum(row.lines for row in rows) / max(len(rows), 1)
            avg_complexity = sum(row.complexity for row in rows) / max(len(rows), 1)
            smell_count = sum(len(row.smells) for row in rows)
            tested = sum(1 for node in graph.nodes.values() if node.subsystem == subsystem and node.related_tests)
            documented = sum(1 for node in graph.nodes.values() if node.subsystem == subsystem and node.purpose)
            node_count = sum(1 for node in graph.nodes.values() if node.subsystem == subsystem)
            penalty = 0.4 * smell_count + (0.8 if subsystem in debt_text else 0)
            architecture = self._clamp_score(9.0 - penalty)
            maintainability = self._clamp_score(9.2 - avg_lines / 250 - penalty)
            performance = self._clamp_score(9.0 - avg_complexity / 80)
            readability = self._clamp_score(9.0 - avg_lines / 350 - smell_count * 0.2)
            complexity = self._clamp_score(9.5 - avg_complexity / 45)
            scalability = self._clamp_score(8.8 - penalty / 2)
            documentation = self._clamp_score(6.5 + 2.5 * documented / max(node_count, 1))
            testing = self._clamp_score(6.0 + 3.0 * tested / max(node_count, 1))
            reliability = self._clamp_score((testing + architecture) / 2)
            security = self._clamp_score(8.8 - (0.6 if subsystem in {"tools", "computer_operation"} else 0.0))
            extensibility = self._clamp_score((architecture + maintainability + scalability) / 3)
            consistency = self._clamp_score(8.8 - smell_count * 0.25)
            values = [
                architecture,
                maintainability,
                performance,
                readability,
                complexity,
                scalability,
                documentation,
                testing,
                reliability,
                security,
                extensibility,
                consistency,
            ]
            scores.append(
                SubsystemScore(
                    subsystem=subsystem,
                    architecture=architecture,
                    maintainability=maintainability,
                    performance=performance,
                    readability=readability,
                    complexity=complexity,
                    scalability=scalability,
                    documentation=documentation,
                    testing=testing,
                    reliability=reliability,
                    security=security,
                    extensibility=extensibility,
                    consistency=consistency,
                    overall=round(sum(values) / len(values), 1),
                )
            )
        return scores

    def _dashboard(
        self,
        overall: float,
        graph: ArchitectureGraph,
        modules: list[ModuleAudit],
        debt: list[DebtItem],
        scores: list[SubsystemScore],
    ) -> dict[str, Any]:
        return {
            "overall_engineering_score": overall,
            "technical_debt_items": len(debt),
            "project_health": "Watch" if overall < 8.0 else "Healthy",
            "largest_modules": [asdict(module) for module in modules[:5]],
            "highest_complexity": [
                asdict(module)
                for module in sorted(modules, key=lambda item: item.complexity, reverse=True)[:5]
            ],
            "performance_score": round(sum(score.performance for score in scores) / max(len(scores), 1), 1),
            "security_score": round(sum(score.security for score in scores) / max(len(scores), 1), 1),
            "maintainability": round(sum(score.maintainability for score in scores) / max(len(scores), 1), 1),
            "coverage_proxy": round(
                100
                * (1 - len(self._missing_tests(graph)) / max(sum(1 for n in graph.nodes.values() if n.kind == "module"), 1)),
                1,
            ),
            "trend_over_time": self._previous_score_trend(overall),
            "operator_quality": self._operator_quality_summary(),
            "domain_platform": self._domain_platform_summary(),
        }

    def _operator_quality_summary(self) -> dict[str, Any]:
        if self.memory is None:
            return {"analytics": {}, "benchmark": {}}
        analytics = WorkflowAnalytics(self.memory.memory_dir / "operator_analytics.json").summary()
        benchmark = OperatorBenchmark(self.memory.memory_dir / "operator_benchmarks.json").summary()
        return {"analytics": analytics, "benchmark": benchmark}

    def _domain_platform_summary(self) -> dict[str, Any]:
        if self.memory is None:
            return {"domains_with_memory": 0, "domain_ids": []}
        domain_root = self.memory.memory_dir / "domains"
        if not domain_root.is_dir():
            return {"domains_with_memory": 0, "domain_ids": []}
        domain_ids = sorted(path.name for path in domain_root.iterdir() if (path / "memory.json").is_file())
        return {
            "domains_with_memory": len(domain_ids),
            "domain_ids": domain_ids,
            "memory_isolated": all((domain_root / domain_id / "memory.json").is_file() for domain_id in domain_ids),
        }

    def _persist_memory(self, audit: ChiefArchitectAudit) -> None:
        self.audit_cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.audit_cache_path.write_text(json.dumps(asdict(audit), indent=2), encoding="utf-8")
        if self.memory is not None:
            self.memory.upsert_project(
                "ChiefArchitect",
                {
                    "overall_engineering_score": audit.overall_score,
                    "technical_debt": [asdict(item) for item in audit.technical_debt[:20]],
                    "dashboard": audit.dashboard,
                    "updated_at": audit.generated_at,
                },
            )

    def _previous_score_trend(self, overall: float) -> str:
        if not self.audit_cache_path.is_file():
            return "baseline"
        try:
            payload = json.loads(self.audit_cache_path.read_text(encoding="utf-8"))
            previous = float(payload.get("overall_score", overall))
        except Exception:
            return "baseline"
        if overall > previous:
            return "improving"
        if overall < previous:
            return "declining"
        return "stable"

    def _clamp_score(self, value: float) -> float:
        return round(max(1.0, min(10.0, value)), 1)

    def _tests_for_proposal(self, proposal: str) -> list[str]:
        lowered = proposal.lower()
        tests = ["tests/jarvis_acceptance.py"]
        if "computer" in lowered or "desktop" in lowered:
            tests.extend(["tests/t14_computer_operator.py", "tests/t15_application_intelligence.py"])
        if "software" in lowered or "project" in lowered:
            tests.extend(["tests/t12_software_director.py", "tests/t13_software_lifecycle.py"])
        if "tool" in lowered:
            tests.append("tests/t9_tool_calling.py")
        if "architecture" in lowered or "audit" in lowered:
            tests.extend(["tests/t16_architecture_intelligence.py", "tests/t17_chief_architect.py"])
        return sorted(set(tests))

    def _report_header(self, title: str, audit: ChiefArchitectAudit | None = None) -> str:
        generated = audit.generated_at if audit else datetime.now(timezone.utc).isoformat()
        return f"# {title}\n\nGenerated: {generated}\n\n"

    def _architecture_report(self, audit: ChiefArchitectAudit) -> str:
        lines = [
            self._report_header("Architecture Audit", audit),
            f"Overall Engineering Score: {audit.overall_score}/10",
            "",
            "## Largest Modules",
        ]
        for module in audit.modules[:10]:
            lines.append(f"- {module.path}: {module.lines} lines, complexity {module.complexity}, smells: {', '.join(module.smells) or 'none'}")
        lines.extend(["", "## Architecture Violations"])
        lines.extend(f"- {item}" for item in audit.architecture_violations) if audit.architecture_violations else lines.append("- None detected.")
        return "\n".join(lines) + "\n"

    def _dependency_report(self, audit: ChiefArchitectAudit) -> str:
        lines = [self._report_header("Dependency Report", audit), "## Circular Dependencies"]
        if audit.circular_dependencies:
            for cycle in audit.circular_dependencies:
                lines.append(f"- {' -> '.join(cycle)}")
        else:
            lines.append("- None detected.")
        lines.extend(["", "## Highest Fan-Out"])
        for module in sorted(audit.modules, key=lambda item: item.fan_out, reverse=True)[:10]:
            lines.append(f"- {module.path}: fan-out {module.fan_out}, fan-in {module.fan_in}, instability {module.instability}")
        return "\n".join(lines) + "\n"

    def _complexity_report(self, audit: ChiefArchitectAudit) -> str:
        lines = [self._report_header("Complexity Report", audit), "## Highest Complexity Modules"]
        for module in sorted(audit.modules, key=lambda item: item.complexity, reverse=True)[:15]:
            lines.append(f"- {module.path}: complexity {module.complexity}, branches {module.branch_count}, nesting {module.max_nesting}")
            for fn in module.largest_functions[:3]:
                lines.append(f"  - {fn['name']}: {fn['lines']} lines, {fn['branches']} branches")
        lines.extend(["", "## God Object Candidates"])
        found = False
        for module in audit.modules:
            for obj in module.god_objects:
                found = True
                lines.append(f"- {module.path}::{obj['class']} methods={obj['methods']} lines={obj['lines']} decisions={obj['decision_points']}")
        if not found:
            lines.append("- None detected.")
        return "\n".join(lines) + "\n"

    def _scorecard_report(self, audit: ChiefArchitectAudit) -> str:
        lines = [self._report_header("Engineering Scorecard", audit), f"Overall: {audit.overall_score}/10", "", "| Subsystem | Overall | Architecture | Performance | Testing | Security |", "|---|---:|---:|---:|---:|---:|"]
        for score in audit.subsystem_scores:
            lines.append(
                f"| {score.subsystem} | {score.overall} | {score.architecture} | {score.performance} | {score.testing} | {score.security} |"
            )
        return "\n".join(lines) + "\n"

    def _debt_report(self, title: str, items: list[DebtItem]) -> str:
        lines = [self._report_header(title), ""]
        if not items:
            lines.append("No technical debt items detected.")
            return "\n".join(lines) + "\n"
        for item in items:
            lines.extend(
                [
                    f"## P{item.priority}: {item.title}",
                    "",
                    f"- Risk: {item.risk}",
                    f"- Effort: {item.estimated_effort}",
                    f"- Estimated gain: {item.estimated_gain}",
                    f"- Suggested solution: {item.suggested_solution}",
                    "- Affected modules:",
                    *[f"  - {module}" for module in item.affected_modules],
                    "",
                ]
            )
        return "\n".join(lines)

    def _list_report(self, title: str, items: list[str], empty: str) -> str:
        lines = [self._report_header(title)]
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append(empty)
        return "\n".join(lines) + "\n"
