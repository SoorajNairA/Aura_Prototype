from __future__ import annotations
import argparse,time
from aura.app.config import Settings
from aura.infrastructure.llm.vertex import VertexPlannerProvider
from aura.planner.live import LivePlanner
from aura.planner.schemas import ProjectRequest

OBJECTIVE="Design a small ESP32 desk fan that turns on when it gets too warm."

def _provider():
    settings=Settings()
    if settings.planner_provider!="vertex":raise RuntimeError(f"Configured provider is {settings.planner_provider}, expected vertex")
    project=settings.gcp_project
    try:
        import google.auth
        credentials,adc_project=google.auth.default(scopes=[VertexPlannerProvider.SCOPE])
        credentials.refresh(__import__("google.auth.transport.requests",fromlist=["Request"]).Request())
    except Exception as exc:raise RuntimeError(f"ADC authentication failed: {exc}") from exc
    return settings,VertexPlannerProvider(project or adc_project,settings.gcp_location,settings.vertex_model,settings.vertex_timeout)

def model_check()->int:
    started=time.perf_counter()
    print("Provider                 Vertex")
    try: settings,provider=_provider();print(f"Model                    {settings.vertex_model}\nAuth                     PASS")
    except Exception as exc:print(f"Model                    unknown\nAuth                     FAIL\nRequest                  FAIL\nStructured output        FAIL\nReason                   {exc}");return 1
    request=ProjectRequest("Temperature Controlled Desk Fan",OBJECTIVE,("Turn on above the configured temperature",))
    outcome=LivePlanner(provider,settings.planner_timeout).plan(request)
    from aura.engineering_graph.model import EntityKind
    passed=outcome.mode=="live_model" and any(item.kind is EntityKind.COMPONENT for item in outcome.plan.entities)
    print(f"Request                  {'PASS' if outcome.mode=='live_model' else 'FAIL'}")
    print(f"Structured output        {'PASS' if passed else 'FAIL'}")
    print(f"Latency                  {(time.perf_counter()-started)*1000:.0f} ms")
    if outcome.fallback_reason:print(f"Reason                   {outcome.fallback_reason}")
    return 0 if passed else 1

def pipeline_check()->int:
    from fastapi.testclient import TestClient
    try: settings,provider=_provider()
    except Exception as exc:print(f"Vertex Planner            FAIL ({exc})");return 1
    from aura.workspace.server import create_app
    with TestClient(create_app(provider=provider,storage_mode="memory")) as client:
        response=client.post("/api/projects",json={"objective":OBJECTIVE,"planningMode":"live_model","operationId":f"pipeline-{time.time_ns()}"})
        if response.status_code!=201:print(f"API                       FAIL ({response.text})");return 1
        project=response.json();pid=project["projectId"]
        graph=client.get(f"/api/projects/{pid}/graph").json();verification=client.get(f"/api/projects/{pid}/verification").json()
        events=client.app.state.workspace.repository.get_events_after(pid,0)
        checks=[("API",True),("Capability classification",project["capability"]["status"].startswith("SUPPORTED")),("Vertex Planner",project["planningMode"]=="live_model"),("Schema",bool(graph["entities"])),("Graph",any(x["kind"]=="component" for x in graph["entities"])),("Verification",bool(verification.get("summary"))),("Transaction",project["revision"]>=1),("Representation requests",bool(project["representations"])),("Events",any(x.type=="project.ready" for x in events))]
        for name,passed in checks:print(f"{name:<26}{'PASS' if passed else 'FAIL'}")
        return 0 if all(p for _,p in checks) else 1

def main()->None:
    parser=argparse.ArgumentParser(description="AURA live diagnostics");parser.add_argument("check",choices=("model-check","pipeline-check"));args=parser.parse_args();raise SystemExit(model_check() if args.check=="model-check" else pipeline_check())

if __name__=="__main__":main()
