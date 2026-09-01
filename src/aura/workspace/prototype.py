from __future__ import annotations

import html
import json
import argparse
import webbrowser
from pathlib import Path

from aura.engineering_graph.model import EngineeringGraph, EntityKind
from .view_models import WorkspaceProjection


def render_workspace(graph: EngineeringGraph) -> str:
    projection = WorkspaceProjection.from_graph(graph)
    components = graph.find(kind=EntityKind.COMPONENT)
    data = [{"id": c.id, "name": c.name, "status": c.verification_status,
             "description": c.metadata.get("description", ""), "role": c.metadata.get("role", "")}
            for c in components]
    cards = "".join(f'<button class="component" data-id="{html.escape(c["id"])}">{html.escape(c["name"])}</button>' for c in data)
    warnings = "".join(f'<li>{html.escape(item["message"])}</li>' for item in projection.verification_summary(graph) if item["severity"] != "info")
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>AURA Engineering Workspace</title>
<style>body{{margin:0;background:#07111d;color:#dff;font:14px Segoe UI;display:grid;grid-template-columns:260px 1fr 300px;grid-template-rows:1fr 170px;height:100vh}}panel,main{{padding:18px;border:1px solid #17435a}}.component{{margin:12px;padding:18px;background:#102c3b;color:#9ff;border:1px solid #2786a8;cursor:pointer}}.component:hover{{background:#174c61}}.selected{{outline:3px solid #ffd54a}}.related{{box-shadow:0 0 18px #47e6ff}}#input{{width:90%;padding:10px;background:#07111d;color:white}}</style></head>
<body><panel><h2>Project hierarchy</h2><div id="tree"></div></panel><main><h1>Automatic Irrigation System</h1><input id="input" value="Design a small ESP32-based automatic plant irrigation system"/><div id="components">{cards}</div></main><panel><h2>Component information</h2><div id="info">Select a semantic component.</div><h2>Verification</h2><ul>{warnings}</ul></panel><panel style="grid-column:1/4"><h2>Generation progress</h2><div>Project started → requirements → subsystems → components → connections → verification → revision committed → ready</div><div id="focus"></div></panel>
<script>const components={json.dumps(data)};const hierarchy={json.dumps(projection.hierarchy(graph))};document.getElementById('tree').textContent=JSON.stringify(hierarchy,null,2);document.querySelectorAll('.component').forEach(el=>{{el.addEventListener('click',()=>{{document.querySelectorAll('.component').forEach(x=>x.classList.remove('selected'));el.classList.add('selected');const c=components.find(x=>x.id===el.dataset.id);document.getElementById('info').textContent=c.name+' — '+c.role+' — '+c.status+' — '+c.description;}});}});window.auraFocus=(ids,explanation)=>{{document.querySelectorAll('.component').forEach(x=>x.classList.toggle('related',ids.includes(x.dataset.id)));document.getElementById('focus').textContent=explanation;}};</script></body></html>'''


def save_workspace(graph: EngineeringGraph, path: Path) -> Path:
    path.write_text(render_workspace(graph), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the AURA irrigation workspace prototype")
    parser.add_argument("--output", type=Path, default=Path("workspace/irrigation-workspace.html"))
    parser.add_argument("--open", action="store_true", dest="open_browser")
    args = parser.parse_args()
    from aura.planner.schemas import ProjectRequest
    from aura.planner.service import PlannerService
    from aura.verification.service import VerificationService
    from .bridge import WorkspaceBridge

    request = ProjectRequest("Automatic Irrigation System",
        "Design a small ESP32-based automatic plant irrigation system with a soil-moisture sensor, water pump, driver or relay, power source, tubing, and a basic enclosure.",
        ("Water automatically when soil is dry", "Use low-voltage DC power", "Keep water separated from electronics"),
        assumptions=("Use a capacitive moisture sensor", "Use a splash-resistant electronics enclosure"))
    plan = PlannerService().plan(request)
    result = VerificationService().verify(plan)
    graph = WorkspaceBridge().commit(EngineeringGraph(plan.entities[0].id), result)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output = save_workspace(graph, args.output.resolve())
    print(output)
    if args.open_browser:
        webbrowser.open(output.as_uri())


if __name__ == "__main__":
    main()
