import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from aura.engineering_graph.model import EngineeringEntity, EntityKind
from aura.workspace.server import create_app


class PlacementProvider:
    def generate_structured(self, messages, **kwargs):
        context = json.loads(messages[0]["content"])
        target = context["selectedSemanticId"]
        axis_two = next(item for item in context["components"] if "axis-2" in item["drivenAxisIds"])
        return SimpleNamespace(
            text=json.dumps({
                "action": "ATTACH_TO_INTERFACE",
                "targetSemanticId": target,
                "summary": "Mount the light sensor at the tip of the second axis",
                "rationale": "The axis-2 driven link exposes an unused compatible distal interface.",
                "referenceSemanticId": axis_two["id"],
                "referenceInterface": "end-face",
                "targetInterface": "body-mount",
                "scalePercent": None,
                "preserveDimensions": [],
                "parameterKey": None,
                "parameterValueJson": None,
                "componentDefinitionId": None,
            }),
            input_tokens=120, output_tokens=80, total_tokens=200,
        )


def test_natural_language_placement_creates_verified_interface_mate():
    app = create_app(provider=PlacementProvider(), storage_mode="memory")
    with TestClient(app) as client:
        project = client.post("/api/projects", json={
            "objective": "Design a dual-axis solar tracker system",
            "planningMode": "deterministic_test",
        }).json()
        project_id = project["projectId"]
        stored = app.state.workspace.repository.get_project(project_id)
        assert stored is not None
        stored.planning_mode = "live_model"
        target = "component-light-sensor"
        subsystem = stored.graph.find(kind=EntityKind.SUBSYSTEM)[0].id
        stored.graph.entities[target] = EngineeringEntity(target, EntityKind.COMPONENT, "Ambient light sensor", subsystem, {
            "family": "light_sensor", "role": "light_sensor",
            "parameters": {"functional_roles": ["feedback_light_direction"], "resolution_quality": "CONCEPTUAL"},
            "dimensions": {"width": {"value": 22, "unit": "mm"}, "length": {"value": 16, "unit": "mm"}, "height": {"value": 6, "unit": "mm"}},
        })
        original_get = app.state.workspace.repository.get_project
        app.state.workspace.repository.get_project = lambda value: stored if value == project_id else original_get(value)
        graph = client.get(f"/api/projects/{project_id}/graph").json()
        assert any(item["id"] == target for item in graph["entities"])

        response = client.post(f"/api/projects/{project_id}/modification-proposals", json={
            "projectId": project_id, "baseRevision": project["revision"],
            "selectedSemanticIds": [target], "request": "place this at the tip of the second axis", "mode": "automatic",
        })

        assert response.status_code == 201
        proposal = response.json()
        assert proposal["operations"][0]["operation"] in {"add_mechanical_attachment", "update_mechanical_attachment"}
        assert proposal["preview"]["semanticId"] == target
        committed = client.post(f"/api/projects/{project_id}/modification-proposals/{proposal['proposalId']}/commit")
        assert committed.status_code == 200
        app.state.workspace.repository.get_project = original_get
        assembly = client.get(f"/api/projects/{project_id}/assembly").json()
        part = next(item for item in assembly["parts"] if item["semanticId"] == target)
        assert "component-mechanism-2" in part["mechanicalParents"]
        assert any(item["from"] == "component-mechanism-2:end-face" for item in part["mateInterfaces"])
