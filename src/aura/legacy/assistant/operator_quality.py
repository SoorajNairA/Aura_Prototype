from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class RecoveryEntry:
    application: str
    failure: str
    recovery_steps: list[str]
    confidence: float
    successes: int = 0
    failures: int = 0
    last_used_at: str = ""


@dataclass
class OperatorRunMetrics:
    goal: str
    application: str
    success: bool
    duration_ms: float
    retries: int
    recoveries: int
    user_interventions: int
    confidence: float
    verification_count: int
    failure_history: list[str] = field(default_factory=list)
    recovery_history: list[str] = field(default_factory=list)
    optimization_opportunities: list[str] = field(default_factory=list)
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class BenchmarkTask:
    name: str
    goal: str
    category: str
    expected_application: str = ""
    timeout_ms: int = 120_000
    requires_live_desktop: bool = False


@dataclass
class BenchmarkResult:
    task: BenchmarkTask
    success: bool
    completion_time_ms: float
    retries: int
    recoveries: int
    user_intervention: bool
    confidence: float
    notes: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class RecoveryLibrary:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, application: str, failure: str, recovery_steps: list[str], success: bool, confidence: float) -> None:
        entries = self._read()
        key = f"{application.lower()}::{failure.lower()}"
        entry = entries.get(
            key,
            RecoveryEntry(
                application=application,
                failure=failure,
                recovery_steps=recovery_steps,
                confidence=confidence,
            ),
        )
        entry.recovery_steps = recovery_steps or entry.recovery_steps
        entry.confidence = round((entry.confidence + confidence) / 2, 2)
        if success:
            entry.successes += 1
        else:
            entry.failures += 1
        entry.last_used_at = datetime.now(timezone.utc).isoformat()
        entries[key] = entry
        self._write(entries)

    def suggestions(self, application: str, failure: str) -> list[str]:
        entries = self._read()
        app = application.lower()
        failure_terms = set(failure.lower().split())
        ranked: list[tuple[float, RecoveryEntry]] = []
        for entry in entries.values():
            if entry.application.lower() != app:
                continue
            overlap = len(failure_terms & set(entry.failure.lower().split()))
            reliability = entry.successes / max(entry.successes + entry.failures, 1)
            ranked.append((overlap + reliability + entry.confidence, entry))
        ranked.sort(key=lambda row: row[0], reverse=True)
        return [step for _, entry in ranked[:3] for step in entry.recovery_steps]

    def _read(self) -> dict[str, RecoveryEntry]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        rows = payload if isinstance(payload, dict) else {}
        entries: dict[str, RecoveryEntry] = {}
        for key, value in rows.items():
            if isinstance(value, dict):
                entries[key] = RecoveryEntry(**value)
        return entries

    def _write(self, entries: dict[str, RecoveryEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({key: asdict(value) for key, value in entries.items()}, indent=2),
            encoding="utf-8",
        )


class WorkflowAnalytics:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(self, metrics: OperatorRunMetrics) -> None:
        rows = self.read()
        rows.append(asdict(metrics))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(rows[-500:], indent=2), encoding="utf-8")

    def read(self) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def summary(self) -> dict[str, Any]:
        rows = self.read()
        if not rows:
            return {
                "success_rate": 0.0,
                "average_retries": 0.0,
                "recovery_success_rate": 0.0,
                "workflow_reuse_rate": 0.0,
                "average_execution_ms": 0.0,
                "least_reliable_applications": [],
                "slowest_tasks": [],
                "optimization_opportunities": [],
            }
        successes = sum(1 for row in rows if row.get("success"))
        recovered_successes = sum(1 for row in rows if row.get("success") and row.get("recoveries", 0) > 0)
        recovered_total = sum(1 for row in rows if row.get("recoveries", 0) > 0)
        by_app: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_app.setdefault(str(row.get("application", "unknown")), []).append(row)
        least_reliable = sorted(
            (
                {
                    "application": app,
                    "success_rate": round(sum(1 for row in app_rows if row.get("success")) / max(len(app_rows), 1), 2),
                    "runs": len(app_rows),
                }
                for app, app_rows in by_app.items()
            ),
            key=lambda item: item["success_rate"],
        )[:5]
        opportunities = []
        if sum(float(row.get("retries", 0)) for row in rows) / max(len(rows), 1) > 1:
            opportunities.append("Reduce retries by improving pre-action confidence checks.")
        if recovered_total and recovered_successes / recovered_total < 0.95:
            opportunities.append("Add stronger recovery routes for repeated failures.")
        slowest = sorted(rows, key=lambda row: float(row.get("duration_ms", 0)), reverse=True)[:5]
        return {
            "success_rate": round(successes / len(rows), 2),
            "average_retries": round(sum(float(row.get("retries", 0)) for row in rows) / len(rows), 2),
            "recovery_success_rate": round(recovered_successes / max(recovered_total, 1), 2),
            "workflow_reuse_rate": round(
                sum(1 for row in rows if float(row.get("confidence", 0)) >= 0.75) / len(rows),
                2,
            ),
            "average_execution_ms": round(sum(float(row.get("duration_ms", 0)) for row in rows) / len(rows), 1),
            "least_reliable_applications": least_reliable,
            "slowest_tasks": [
                {
                    "goal": row.get("goal", ""),
                    "application": row.get("application", ""),
                    "duration_ms": row.get("duration_ms", 0),
                }
                for row in slowest
            ],
            "optimization_opportunities": opportunities,
        }


class OperatorBenchmark:
    DEFAULT_TASKS = (
        BenchmarkTask("Open VS Code", "Open VS Code", "vscode", "vscode"),
        BenchmarkTask("Create Folder", "Create a folder named BenchmarkFolder", "filesystem", "explorer"),
        BenchmarkTask("Create Python Project", "Create a Python calculator app", "software", "vscode"),
        BenchmarkTask("Operate Browser", "Open GitHub", "browser", "chrome"),
        BenchmarkTask("Recover Compile Error", "Recover compile error in Unreal", "unreal", "unreal"),
    )

    def __init__(self, result_path: Path) -> None:
        self.result_path = result_path

    def run(
        self,
        executor: Callable[[BenchmarkTask], tuple[bool, float, int, int, bool, float, str]],
        tasks: Optional[list[BenchmarkTask]] = None,
    ) -> list[BenchmarkResult]:
        results: list[BenchmarkResult] = []
        for task in tasks or list(self.DEFAULT_TASKS):
            success, elapsed, retries, recoveries, intervention, confidence, notes = executor(task)
            results.append(
                BenchmarkResult(
                    task=task,
                    success=success,
                    completion_time_ms=round(elapsed, 1),
                    retries=retries,
                    recoveries=recoveries,
                    user_intervention=intervention,
                    confidence=round(confidence, 2),
                    notes=notes,
                )
            )
        self.record(results)
        return results

    def record(self, results: list[BenchmarkResult]) -> None:
        rows = self.read()
        rows.extend(asdict(result) for result in results)
        self.result_path.parent.mkdir(parents=True, exist_ok=True)
        self.result_path.write_text(json.dumps(rows[-1000:], indent=2), encoding="utf-8")

    def read(self) -> list[dict[str, Any]]:
        if not self.result_path.is_file():
            return []
        try:
            payload = json.loads(self.result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        return payload if isinstance(payload, list) else []

    def summary(self) -> dict[str, Any]:
        rows = self.read()
        if not rows:
            return {"success_rate": 0.0, "average_retries": 0.0, "average_time_ms": 0.0, "runs": 0}
        return {
            "success_rate": round(sum(1 for row in rows if row.get("success")) / len(rows), 2),
            "average_retries": round(sum(float(row.get("retries", 0)) for row in rows) / len(rows), 2),
            "average_time_ms": round(sum(float(row.get("completion_time_ms", 0)) for row in rows) / len(rows), 1),
            "runs": len(rows),
        }
