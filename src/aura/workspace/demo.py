"""Fast, bounded pre-demo diagnostics and safe benchmark reset tooling."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path
from uuid import uuid4


IRRIGATION = "Design a small ESP32 automatic irrigation system with sensor, pump, driver, tubing, reservoir, enclosure, and low voltage power."


def _request(url: str, path: str, *, data: dict | None = None, timeout: float = 5) -> tuple[int, object]:
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(url.rstrip("/") + path, data=body,
        headers={"content-type": "application/json"} if body else {}, method="POST" if body else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def check(url: str, project_id: str | None = None) -> int:
    results: list[tuple[str, str, str]] = []
    try:
        code, live = _request(url, "/health/live")
        results.append(("PASS" if code == 200 else "FAIL", "backend", f"{code} {live}"))
        code, ready = _request(url, "/health/ready")
        results.append(("PASS" if code == 200 else "FAIL", "database/artifacts", f"{code} {ready}"))
        code, projects = _request(url, "/api/projects")
        results.append(("PASS" if code == 200 else "FAIL", "project index", f"{len(projects) if isinstance(projects,list) else 0} saved"))
        # Lists may contain historical projects from an older schema.  A health
        # rehearsal should inspect the newest demo candidate unless one was named.
        selected = project_id or (max(projects, key=lambda item: item.get("updatedAt", ""))["projectId"] if code == 200 and projects else None)
        if selected:
            pcode, project = _request(url, f"/api/projects/{selected}")
            bad = [x for x in project.get("representations", []) if x.get("status") == "generating"] if isinstance(project,dict) else []
            results.append(("PASS" if pcode == 200 and not bad else "WARN", "demo project", f"{selected}; {len(bad)} generating"))
            vcode, verification = _request(url, f"/api/projects/{selected}/verification")
            critical = verification.get("summary", {}).get("failed", 0) if isinstance(verification,dict) else 0
            results.append(("PASS" if vcode == 200 and not critical else "FAIL", "verification", f"{critical} failed"))
        else:
            results.append(("WARN", "demo project", "no saved benchmark selected"))
    except Exception as exc:
        results.append(("FAIL", "backend", f"unreachable: {exc.__class__.__name__}"))
    from aura.app.config import Settings
    from aura.workspace.representation_service import CircuitGeneratorAdapter
    settings=Settings()
    results.append(("PASS" if shutil.which("node") else "FAIL", "Circuit generator", "node executable" if shutil.which("node") else "node not on PATH"))
    worker=Path(__file__).with_name("web") / "representation" / "cascade-worker.js"
    results.append(("PASS" if worker.is_file() else "FAIL", "CAD worker", str(worker) if worker.is_file() else "cascade worker missing"))
    try:
        adapter=CircuitGeneratorAdapter(timeout=3)
        results.append(("PASS" if adapter.script_path.is_file() else "FAIL", "tCircuit script", str(adapter.script_path)))
    except Exception as exc:
        results.append(("FAIL", "tCircuit script", str(exc)))
    if settings.planner_provider=="vertex":
        try:
            from aura.workspace.diagnostics import _provider
            _,provider=_provider();results.append(("PASS", "Vertex", f"{provider.model} / {provider.location}"))
        except Exception as exc:
            results.append(("FAIL", "Vertex", str(exc)))
    else:
        results.append(("WARN", "Vertex", f"configured provider is {settings.planner_provider}"))
    results.append(("PASS", "Build", f"version {__import__('os').getenv('AURA_VERSION','0.1.0')} commit {__import__('os').getenv('AURA_BUILD_COMMIT','development')}"))
    print("AURA DEMO HEALTH")
    for state, name, detail in results:
        print(f"{state:4}  {name}: {detail}")
    passed=not any(state == "FAIL" for state, _, _ in results)
    print("READY FOR DEMO" if passed else "NOT READY FOR DEMO")
    return 0 if passed else 1


def reset(url: str, benchmark: str) -> int:
    if benchmark != "irrigation":
        print("FAIL  reset is scoped to the known irrigation benchmark", file=sys.stderr)
        return 2
    operation = f"demo-reset-irrigation-{uuid4().hex}"
    code, project = _request(url, "/api/projects", data={"objective": IRRIGATION,"planningMode":"deterministic_test","operationId":operation}, timeout=20)
    if code not in {200, 201}:
        print(f"FAIL  demo reset: HTTP {code}")
        return 1
    print(f"PASS  created/reopened isolated benchmark {project['projectId']} revision {project['revision']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AURA hackathon demo diagnostics")
    sub = parser.add_subparsers(dest="command", required=True)
    check_parser = sub.add_parser("check"); check_parser.add_argument("--url", default="http://127.0.0.1:8765"); check_parser.add_argument("--project-id")
    reset_parser = sub.add_parser("reset"); reset_parser.add_argument("benchmark", choices=["irrigation"]); reset_parser.add_argument("--url", default="http://127.0.0.1:8765")
    args = parser.parse_args()
    return check(args.url, args.project_id) if args.command == "check" else reset(args.url, args.benchmark)


if __name__ == "__main__":
    raise SystemExit(main())
