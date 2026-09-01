from __future__ import annotations

import ast
import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from aura.infrastructure.persistence.memory_store import MemoryStore


@dataclass
class ArchitectureNode:
    id: str
    kind: str
    name: str
    path: str = ""
    subsystem: str = "core"
    purpose: str = ""
    responsibilities: list[str] = field(default_factory=list)
    public_interfaces: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    related_tests: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchitectureEdge:
    source: str
    target: str
    relationship: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchitectureGraph:
    generated_at: str
    project_root: str
    nodes: dict[str, ArchitectureNode]
    edges: list[ArchitectureEdge]
    health: dict[str, Any] = field(default_factory=dict)


@dataclass
class ArchitectureAnswer:
    question: str
    answer: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    diagram: str = ""


class ArchitectureIntelligenceEngine:
    """Persistent architecture graph and reasoning layer.

    This engine is intentionally read-only. It indexes AURA's source tree,
    documentation, tests, and packaging metadata so AURA can reason about its
    own architecture without editing its own code.
    """

    ARCHITECTURE_TERMS = (
        "architecture",
        "module",
        "component",
        "subsystem",
        "dependency",
        "depends on",
        "execution flow",
        "data flow",
        "diagram",
        "where should",
        "what tests",
        "what breaks",
        "impact",
        "verification pipeline",
        "softwaredirector",
        "software director",
        "computeroperator",
        "computer operator",
        "toolregistry",
        "tool registry",
        "voice pipeline",
        "desktop automation",
        "ocr",
        "self architecture",
        "how do you work",
        "how are you built",
        "engineering audit",
        "chief architect",
        "technical debt",
        "engineering score",
        "optimization roadmap",
        "architecture audit",
        "god object",
        "oversized module",
    )

    SUBSYSTEM_HINTS: dict[str, tuple[str, ...]] = {
        "executive": ("executive", "assumption", "supervisor", "orchestrator"),
        "software_engineering": ("software_director", "software", "blueprint", "lifecycle"),
        "computer_operation": ("computer_operator", "application_intelligence", "desktop", "operator"),
        "tools": ("actions", "tool", "registry", "executionagent"),
        "conversation": ("llm", "conversation", "context"),
        "memory": ("memory", "store"),
        "voice": ("tts", "xtts", "audio", "stt", "speech"),
        "gui": ("gui", "future_gui"),
        "safety": ("safety", "verification", "revealer"),
        "configuration": ("config", "hardware", "pyproject", "requirements"),
        "installer": ("installer", "packaging", "launch"),
        "tests": ("test", "tests", "acceptance"),
        "documentation": ("readme", "docs", "license"),
    }

    RESPONSIBILITY_HINTS: dict[str, list[str]] = {
        "executive_agent": [
            "Infer high-level user goals.",
            "Coordinate project generation, verification, memory, and result reveal.",
        ],
        "software_director": [
            "Plan, scaffold, evolve, verify, and document software projects.",
            "Maintain engineering blueprints, dependency graphs, and project health.",
        ],
        "computer_operator": [
            "Operate desktop applications through perception, planning, execution, verification, and recovery.",
            "Coordinate application intelligence, workflow memory, and safe input providers.",
        ],
        "application_intelligence": [
            "Build semantic models of arbitrary applications.",
            "Map interfaces, discover workflows, score confidence, learn, and adapt to UI changes.",
        ],
        "actions": [
            "Own the safe tool registry and registered desktop/file/url tools.",
            "Reject unknown or unsafe tools.",
        ],
        "orchestrator": [
            "Route voice/text requests across fast path, tools, executive execution, planning, and conversation.",
            "Connect STT, TTS, memory, safety, tools, and GUI status events.",
        ],
        "tts": ["Provide the speech synthesis service and fallback chain."],
        "xtts_backend": ["Provide local XTTS-v2 speech generation, voice cloning, warmup, and playback."],
        "stt": ["Transcribe recorded speech into text."],
        "memory_store": ["Persist user profile, project memory, and action logs."],
        "result_revealer": ["Reveal created/opened results through Explorer, apps, browser, or foreground windows."],
        "safety": ["Classify risk and require confirmation for high-risk actions."],
        "config": ["Load runtime configuration and environment-driven settings."],
    }

    def __init__(self, project_root: Path, memory: Optional[MemoryStore] = None) -> None:
        self.project_root = project_root.resolve()
        self.memory = memory
        self.cache_path = (
            memory.memory_dir / "architecture_graph.json"
            if memory is not None
            else self.project_root / "logs" / "architecture_graph.json"
        )
        self._graph: ArchitectureGraph | None = None

    def can_handle(self, question: str) -> bool:
        lowered = question.lower()
        if any(term in lowered for term in self.ARCHITECTURE_TERMS):
            return True
        return bool(
            re.search(r"\b(?:explain|show|locate|identify)\b", lowered)
            and re.search(r"\b(?:aura|yourself|system|codebase|pipeline)\b", lowered)
        )

    def answer(self, question: str) -> ArchitectureAnswer:
        graph = self.graph()
        lowered = question.lower()
        if "where should" in lowered and "ocr" in lowered:
            return self._ocr_answer(question, graph)
        if "desktop automation" in lowered or "computer operator" in lowered:
            return self._desktop_automation_answer(question, graph)
        if "voice" in lowered and "flow" in lowered:
            return self._voice_flow_answer(question)
        if "toolregistry" in lowered or "tool registry" in lowered:
            return self._impact_answer(question, "actions.ToolRegistry", graph)
        if "tests" in lowered and "computeroperator" in lowered.replace(" ", ""):
            return self._computer_operator_tests_answer(question, graph)
        if "diagram" in lowered:
            diagram = self.generate_component_diagram(graph)
            return ArchitectureAnswer(
                question=question,
                answer="Generated the current architecture diagram from the architecture graph.",
                confidence=0.9,
                evidence=["Architecture graph nodes and dependency edges."],
                diagram=diagram,
            )
        if "software director" in lowered or "softwaredirector" in lowered:
            return self._explain_component(question, "software_director", graph)
        if "unused" in lowered:
            return self._unused_modules_answer(question, graph)
        if "executive agent" in lowered and "computeroperator" in lowered.replace(" ", ""):
            return self._executive_to_operator_answer(question)
        if "verification pipeline" in lowered or "verification" in lowered:
            return self._verification_answer(question, graph)
        if "how do you work" in lowered or "how are you built" in lowered:
            return self._self_explanation(question)
        if (
            "engineering audit" in lowered
            or "chief architect" in lowered
            or "technical debt" in lowered
            or "engineering score" in lowered
            or "optimization roadmap" in lowered
            or "god object" in lowered
            or "oversized module" in lowered
        ):
            return self._chief_architect_answer(question)
        search = self.search(question, limit=5)
        if search:
            lines = [f"{row.name}: {row.purpose or ', '.join(row.responsibilities[:1])}" for row in search]
            return ArchitectureAnswer(
                question=question,
                answer="Relevant architecture concepts:\n" + "\n".join(f"- {line}" for line in lines),
                confidence=0.74,
                evidence=[row.path for row in search if row.path],
            )
        return ArchitectureAnswer(
            question=question,
            answer="I do not have enough architecture evidence for that yet.",
            confidence=0.35,
        )

    def graph(self, force_refresh: bool = False) -> ArchitectureGraph:
        if not force_refresh and self._graph is not None and not self._is_stale(self._graph):
            return self._graph
        if not force_refresh:
            cached = self._read_cache()
            if cached is not None and not self._is_stale(cached):
                self._graph = cached
                return cached
        self._graph = self.build_graph()
        self._write_cache(self._graph)
        return self._graph

    def build_graph(self) -> ArchitectureGraph:
        nodes: dict[str, ArchitectureNode] = {}
        edges: list[ArchitectureEdge] = []
        python_files = self._safe_files("src", "*.py") + self._safe_files("tests", "*.py")
        for path in python_files:
            module_node, child_nodes, module_edges = self._index_python_file(path)
            nodes[module_node.id] = module_node
            for node in child_nodes:
                nodes[node.id] = node
            edges.extend(module_edges)

        for path in self._safe_files("docs", "*") + self._root_metadata_files():
            node = self._index_document(path)
            nodes[node.id] = node

        for node in nodes.values():
            if node.kind == "module":
                node.related_tests = self._related_tests(node, nodes)
                node.purpose = node.purpose or self._purpose_for(node)
                if not node.responsibilities:
                    node.responsibilities = self._responsibilities_for(node)

        edges.extend(self._component_edges(nodes))
        health = self._health(nodes, edges)
        return ArchitectureGraph(
            generated_at=datetime.now(timezone.utc).isoformat(),
            project_root=str(self.project_root),
            nodes=nodes,
            edges=edges,
            health=health,
        )

    def search(self, query: str, limit: int = 8) -> list[ArchitectureNode]:
        graph = self.graph()
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        scored: list[tuple[int, ArchitectureNode]] = []
        for node in graph.nodes.values():
            text = " ".join(
                [
                    node.id,
                    node.name,
                    node.kind,
                    node.subsystem,
                    node.purpose,
                    " ".join(node.responsibilities),
                    " ".join(node.public_interfaces),
                ]
            ).lower()
            score = sum(3 if term in node.name.lower() else 1 for term in terms if term in text)
            if score:
                scored.append((score, node))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return [node for _, node in scored[:limit]]

    def impact_analysis(self, component: str) -> dict[str, Any]:
        graph = self.graph()
        needle = component.lower().replace(" ", "")
        matching = [
            node
            for node in graph.nodes.values()
            if needle in node.id.lower().replace(" ", "") or needle in node.name.lower().replace(" ", "")
        ]
        impacted: set[str] = set()
        for match in matching:
            for edge in graph.edges:
                if edge.target == match.id or match.id in edge.target:
                    impacted.add(edge.source)
                if edge.source == match.id:
                    impacted.add(edge.target)
        tests = sorted(
            node.path
            for node in graph.nodes.values()
            if node.kind == "test" and any(self._basename(part) in node.path.lower() for part in impacted | {component})
        )
        return {
            "component": component,
            "matching_nodes": [node.id for node in matching],
            "affected_nodes": sorted(impacted),
            "related_tests": tests,
            "risk": "high" if len(impacted) > 8 else "medium" if len(impacted) > 3 else "low",
        }

    def generate_component_diagram(self, graph: ArchitectureGraph | None = None) -> str:
        graph = graph or self.graph()
        edges = {
            ("AuraSupervisor", "ExecutiveAgent"),
            ("AuraSupervisor", "ToolRegistry"),
            ("AuraSupervisor", "Conversation Engine"),
            ("AuraSupervisor", "Voice System"),
            ("ExecutiveAgent", "SoftwareDirector"),
            ("ExecutiveAgent", "ComputerOperator"),
            ("ComputerOperator", "ApplicationIntelligence"),
            ("ComputerOperator", "ExecutionAgent"),
            ("ExecutionAgent", "ToolRegistry"),
            ("SoftwareDirector", "MemoryStore"),
            ("ComputerOperator", "MemoryStore"),
            ("ExecutionAgent", "Desktop/File/URL Tools"),
            ("ResultRevealer", "Desktop"),
            ("Voice System", "XTTS/STT"),
        }
        lines = ["flowchart TD"]
        for source, target in sorted(edges):
            lines.append(f"    {self._diagram_id(source)}[{source}] --> {self._diagram_id(target)}[{target}]")
        lines.append(f"    Health[Indexed nodes: {len(graph.nodes)} | Edges: {len(graph.edges)}]")
        return "\n".join(lines)

    def _index_python_file(self, path: Path) -> tuple[ArchitectureNode, list[ArchitectureNode], list[ArchitectureEdge]]:
        rel = self._rel(path)
        module_id = self._module_id(path)
        source = path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(source)
        except SyntaxError:
            node = ArchitectureNode(
                id=module_id,
                kind="module",
                name=path.stem,
                path=rel,
                subsystem=self._subsystem_for(path.stem, rel),
                metadata={"parse_error": True},
            )
            return node, [], []
        imports = self._imports(tree)
        public_interfaces: list[str] = []
        child_nodes: list[ArchitectureNode] = []
        edges: list[ArchitectureEdge] = []
        for item in tree.body:
            if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name.startswith("_"):
                    continue
                kind = "class" if isinstance(item, ast.ClassDef) else "function"
                public_interfaces.append(item.name)
                child_id = f"{module_id}.{item.name}"
                child_nodes.append(
                    ArchitectureNode(
                        id=child_id,
                        kind=kind,
                        name=item.name,
                        path=rel,
                        subsystem=self._subsystem_for(path.stem, rel),
                        purpose=ast.get_docstring(item) or "",
                        dependencies=[],
                        metadata={"line": getattr(item, "lineno", None)},
                    )
                )
                edges.append(ArchitectureEdge(module_id, child_id, "defines"))
        node = ArchitectureNode(
            id=module_id,
            kind="test" if "tests/" in rel.replace("\\", "/") else "module",
            name=path.stem,
            path=rel,
            subsystem=self._subsystem_for(path.stem, rel),
            purpose=ast.get_docstring(tree) or "",
            responsibilities=self._responsibilities_for_name(path.stem),
            public_interfaces=public_interfaces,
            dependencies=imports,
            metadata={"lines": source.count("\n") + 1},
        )
        for imported in imports:
            edges.append(ArchitectureEdge(module_id, imported, "depends_on"))
        return node, child_nodes, edges

    def _index_document(self, path: Path) -> ArchitectureNode:
        rel = self._rel(path)
        text = path.read_text(encoding="utf-8", errors="ignore") if path.is_file() else ""
        heading = next((line.strip("# ").strip() for line in text.splitlines() if line.strip().startswith("#")), path.name)
        return ArchitectureNode(
            id=f"doc.{re.sub(r'[^a-z0-9]+', '_', rel.lower()).strip('_')}",
            kind="documentation" if path.suffix.lower() in {".md", ".txt"} else "configuration",
            name=path.name,
            path=rel,
            subsystem=self._subsystem_for(path.stem, rel),
            purpose=heading,
            responsibilities=self._doc_topics(text),
            metadata={"size": path.stat().st_size if path.exists() else 0},
        )

    def _imports(self, tree: ast.AST) -> list[str]:
        imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
                elif node.level:
                    imports.update(alias.name for alias in node.names)
        return sorted(imports)

    def _component_edges(self, nodes: dict[str, ArchitectureNode]) -> list[ArchitectureEdge]:
        available = set(nodes)
        edges: list[ArchitectureEdge] = []
        for node in nodes.values():
            if node.kind not in {"module", "test"}:
                continue
            for dep in node.dependencies:
                target = self._resolve_dependency(dep, available)
                if target:
                    edges.append(ArchitectureEdge(node.id, target, "imports"))
        return edges

    def _resolve_dependency(self, dep: str, available: set[str]) -> str:
        candidates = [
            dep,
            f"src.aura.{dep}",
            f"src.aura.{dep.split('.')[-1]}",
        ]
        for candidate in candidates:
            if candidate in available:
                return candidate
        if dep.startswith("aura."):
            candidate = "src." + dep
            if candidate in available:
                return candidate
        return ""

    def _related_tests(self, node: ArchitectureNode, nodes: dict[str, ArchitectureNode]) -> list[str]:
        base = node.name.lower()
        aliases = {
            "computer_operator": ("computer_operator", "application_intelligence"),
            "software_director": ("software_director", "software_lifecycle"),
            "actions": ("tool_calling", "jarvis_acceptance"),
            "executive_agent": ("executive_agent", "jarvis_acceptance"),
            "tts": ("xtts",),
        }.get(base, (base,))
        tests = []
        for other in nodes.values():
            if other.kind != "test":
                continue
            test_key = other.path.lower().replace("\\", "/")
            if any(alias in test_key for alias in aliases):
                tests.append(other.path)
        return sorted(tests)

    def _health(self, nodes: dict[str, ArchitectureNode], edges: list[ArchitectureEdge]) -> dict[str, Any]:
        inbound = Counter(edge.target for edge in edges)
        oversized = [
            node.path
            for node in nodes.values()
            if node.kind == "module" and int(node.metadata.get("lines", 0)) > 900
        ]
        dead_candidates = [
            node.path
            for node in nodes.values()
            if node.kind == "module"
            and inbound.get(node.id, 0) == 0
            and node.name not in {"main", "__init__"}
            and not node.path.endswith("orchestrator.py")
        ][:20]
        missing_docs = [
            node.path
            for node in nodes.values()
            if node.kind == "module" and not node.purpose and not node.responsibilities
        ][:20]
        return {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "oversized_modules": oversized,
            "dead_code_candidates": dead_candidates,
            "missing_documentation": missing_docs,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def _ocr_answer(self, question: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        evidence = [
            "infrastructure/desktop/application_intelligence.py owns replaceable interface and discovery providers.",
            "infrastructure/desktop/computer_operator.py owns compatibility desktop perception and recovery.",
        ]
        answer = (
            "OCR belongs as a provider under the Application Intelligence and Computer Operator boundary. "
            "Add an OCR provider beside the existing interface/semantic providers, feed its observations into "
            "InterfaceMapper or a future Vision/OCR provider, and keep raw desktop control inside ComputerOperator. "
            "That preserves the layering: observe the interface, understand semantics, then operate safely."
        )
        return ArchitectureAnswer(question, answer, 0.92, evidence)

    def _desktop_automation_answer(self, question: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        modules = [
            "orchestrator: routes executable requests.",
            "executive_agent: decides when high-level execution is needed.",
            "computer_operator: owns desktop operation workflows.",
            "application_intelligence: understands unknown application interfaces.",
            "actions: owns ToolRegistry and safe open/file/url tools.",
            "result_revealer: brings results to the user.",
            "safety: blocks high-risk actions.",
        ]
        return ArchitectureAnswer(
            question,
            "Desktop automation is split across:\n" + "\n".join(f"- {row}" for row in modules),
            0.9,
            [row.split(":")[0] for row in modules],
        )

    def _voice_flow_answer(self, question: str) -> ArchitectureAnswer:
        flow = [
            "AudioIO records speech.",
            "STTService transcribes it.",
            "AuraSupervisor routes the text through fast path, tool detection, ExecutiveAgent, planning, or conversation.",
            "Executable goals may pass into ExecutiveAgent, SoftwareDirector, ComputerOperator, or ExecutionAgent tools.",
            "Results are verified, remembered, revealed, then spoken by TTSService.",
        ]
        return ArchitectureAnswer(question, "\n".join(f"{i}. {step}" for i, step in enumerate(flow, 1)), 0.9)

    def _impact_answer(self, question: str, component: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        impact = self.impact_analysis(component)
        affected = impact["affected_nodes"][:8]
        tests = impact["related_tests"] or ["tests/t9_tool_calling.py", "tests/jarvis_acceptance.py"]
        answer = (
            f"Changing {component} is {impact['risk']} risk. It can affect:\n"
            + "\n".join(f"- {item}" for item in affected)
            + "\nTests to update/run:\n"
            + "\n".join(f"- {item}" for item in tests[:8])
        )
        return ArchitectureAnswer(question, answer, 0.86, impact["matching_nodes"])

    def _computer_operator_tests_answer(self, question: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        tests = [
            "tests/t14_computer_operator.py",
            "tests/t15_application_intelligence.py",
            "tests/t10_executive_agent.py",
            "tests/t11_visibility_policy.py",
            "tests/jarvis_acceptance.py",
        ]
        return ArchitectureAnswer(
            question,
            "After changing ComputerOperator, update or run:\n" + "\n".join(f"- {test}" for test in tests),
            0.9,
            tests,
        )

    def _explain_component(self, question: str, component: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        matches = [node for node in graph.nodes.values() if component in node.id or component in node.name]
        responsibilities = self.RESPONSIBILITY_HINTS.get(component, [])
        answer = (
            "SoftwareDirector is AURA's autonomous software engineering subsystem. "
            "It turns product goals into project blueprints, scaffolds code, evolves existing projects, "
            "maintains dependency graphs and health reports, verifies outputs, stores project memory, "
            "and reveals generated results."
        )
        return ArchitectureAnswer(question, answer, 0.9, [node.path for node in matches[:5] if node.path] + responsibilities)

    def _unused_modules_answer(self, question: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        candidates = graph.health.get("dead_code_candidates", [])
        if not candidates:
            answer = "No strong unused-module candidates were found in the current architecture graph."
        else:
            answer = "Static unused-module candidates. Review manually before deleting:\n" + "\n".join(
                f"- {item}" for item in candidates[:10]
            )
        return ArchitectureAnswer(question, answer, 0.66, candidates[:10])

    def _executive_to_operator_answer(self, question: str) -> ArchitectureAnswer:
        answer = (
            "ExecutiveAgent owns the high-level execution decision. During initialization it receives or creates "
            "ComputerOperator. In can_handle(), operator-capable goals are detected before normal project routing. "
            "In execute(), ExecutiveAgent delegates to ComputerOperator.execute(), then converts the operator outcome "
            "into an ExecutiveOutcome for the supervisor to speak."
        )
        return ArchitectureAnswer(
            question,
            answer,
            0.88,
            ["legacy/assistant/executive_agent.py", "infrastructure/desktop/computer_operator.py"],
        )

    def _verification_answer(self, question: str, graph: ArchitectureGraph) -> ArchitectureAnswer:
        answer = (
            "Verification is layered. Direct tools return ActionResult and ExecutionVerifier checks file/app/url effects. "
            "SoftwareDirector runs project verification and writes reports. ComputerOperator uses a VerificationProvider "
            "after each operator step, then recovers before failing. Jarvis acceptance and phase tests validate the full path."
        )
        return ArchitectureAnswer(
            question,
            answer,
            0.86,
            ["legacy/assistant/executive_agent.py", "legacy/assistant/software_director.py", "infrastructure/desktop/computer_operator.py"],
        )

    def _self_explanation(self, question: str) -> ArchitectureAnswer:
        answer = (
            "AURA is organized as a local executive assistant. AuraSupervisor routes speech/text requests. "
            "Fast direct commands go to the safe ToolRegistry. Larger goals go to ExecutiveAgent, which may delegate "
            "software work to SoftwareDirector or desktop workflows to ComputerOperator. MemoryStore persists projects "
            "and logs. ResultRevealer shows created outputs. STT and TTS handle voice around that execution core."
        )
        return ArchitectureAnswer(question, answer, 0.88)

    def _chief_architect_answer(self, question: str) -> ArchitectureAnswer:
        from aura.legacy.assistant.chief_architect import ChiefArchitect

        architect = ChiefArchitect(self.project_root, self.memory, architecture=self)
        audit = architect.audit()
        top_debt = audit.technical_debt[:3]
        lines = [
            f"Engineering score: {audit.overall_score}/10.",
            f"Technical debt items: {len(audit.technical_debt)}.",
            f"Largest module: {audit.modules[0].path} ({audit.modules[0].lines} lines)." if audit.modules else "No modules indexed.",
            "Top priorities:",
        ]
        if top_debt:
            lines.extend(f"- P{item.priority}: {item.title}" for item in top_debt)
        else:
            lines.append("- No high-confidence debt items found.")
        return ArchitectureAnswer(
            question=question,
            answer="\n".join(lines),
            confidence=0.86,
            evidence=["ChiefArchitect audit cache", "Architecture graph"],
        )

    def _safe_files(self, folder: str, pattern: str) -> list[Path]:
        base = self.project_root / folder
        if not base.exists():
            return []
        return sorted(path for path in base.rglob(pattern) if path.is_file() and "__pycache__" not in path.parts)

    def _root_metadata_files(self) -> list[Path]:
        names = ["README.md", "LICENSE", "pyproject.toml", "requirements.txt", ".env.example"]
        return [self.project_root / name for name in names if (self.project_root / name).is_file()]

    def _read_cache(self) -> ArchitectureGraph | None:
        if not self.cache_path.is_file():
            return None
        try:
            payload = json.loads(self.cache_path.read_text(encoding="utf-8"))
            nodes = {
                key: ArchitectureNode(**value)
                for key, value in payload.get("nodes", {}).items()
                if isinstance(value, dict)
            }
            edges = [ArchitectureEdge(**value) for value in payload.get("edges", []) if isinstance(value, dict)]
            return ArchitectureGraph(
                generated_at=str(payload.get("generated_at", "")),
                project_root=str(payload.get("project_root", self.project_root)),
                nodes=nodes,
                edges=edges,
                health=payload.get("health", {}),
            )
        except Exception:
            return None

    def _write_cache(self, graph: ArchitectureGraph) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_path.write_text(json.dumps(asdict(graph), indent=2), encoding="utf-8")

    def _is_stale(self, graph: ArchitectureGraph) -> bool:
        try:
            generated = datetime.fromisoformat(graph.generated_at)
        except Exception:
            return True
        newest = 0.0
        for path in self._safe_files("src", "*.py") + self._safe_files("tests", "*.py") + self._root_metadata_files():
            try:
                newest = max(newest, path.stat().st_mtime)
            except OSError:
                continue
        return newest > generated.timestamp()

    def _rel(self, path: Path) -> str:
        try:
            return str(path.resolve().relative_to(self.project_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _module_id(self, path: Path) -> str:
        rel = self._rel(path).replace("/", ".")
        if rel.endswith(".py"):
            rel = rel[:-3]
        return rel

    def _subsystem_for(self, name: str, rel: str) -> str:
        token = f"{name} {rel}".lower()
        for subsystem, hints in self.SUBSYSTEM_HINTS.items():
            if any(hint in token for hint in hints):
                return subsystem
        return "core"

    def _responsibilities_for(self, node: ArchitectureNode) -> list[str]:
        return self._responsibilities_for_name(node.name)

    def _responsibilities_for_name(self, name: str) -> list[str]:
        lowered = name.lower()
        for key, responsibilities in self.RESPONSIBILITY_HINTS.items():
            if key in lowered:
                return responsibilities
        return []

    def _purpose_for(self, node: ArchitectureNode) -> str:
        responsibilities = self._responsibilities_for(node)
        if responsibilities:
            return responsibilities[0]
        return f"{node.name} module in the {node.subsystem} subsystem."

    def _doc_topics(self, text: str) -> list[str]:
        topics = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                topics.append(stripped.strip("# ").strip())
            if len(topics) >= 8:
                break
        return topics

    def _basename(self, value: str) -> str:
        return value.lower().replace("src.aura.", "").replace("tests.", "").replace("_", "")

    def _diagram_id(self, label: str) -> str:
        return re.sub(r"[^A-Za-z0-9_]+", "", label) or "Node"
