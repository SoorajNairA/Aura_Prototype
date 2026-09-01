from fastapi.testclient import TestClient

from aura.workspace.server import create_app


def _project(client: TestClient, objective: str):
    response=client.post("/api/projects",json={"objective":objective,"planningMode":"deterministic_test"})
    assert response.status_code==201,response.text
    return response.json()


def _assert_interface_assembly(client: TestClient, project: dict):
    assembly=client.get(f'/api/projects/{project["projectId"]}/assembly').json()
    interfaces={item["interfaceId"]:item for item in assembly["interfaces"]}
    assert assembly["placementMethod"]=="interface-frame-mating"
    assert interfaces and assembly["relationships"]
    for mate in assembly["relationships"]:
        assert mate["from"] in interfaces and mate["to"] in interfaces
        assert interfaces[mate["to"]]["type"] in interfaces[mate["from"]]["compatibleTypes"]
    for servo in [part for part in assembly["parts"] if "servo" in part["semanticId"]]:
        owned=[item for item in interfaces.values() if item["semanticId"]==servo["semanticId"]]
        assert {item["type"] for item in owned}>={"fixed_mount","rotating_output"}
        assert next(item for item in owned if item["type"]=="fixed_mount")["interfaceId"] != next(item for item in owned if item["type"]=="rotating_output")["interfaceId"]
    return assembly


def _assert_complete_schematic(client: TestClient, project: dict):
    record=next(item for item in project["representations"] if item["type"]=="circuit_schematic")
    assert record["status"]=="ready",record
    circuit=client.get(f'/api/artifacts/{record["artifactId"]}/content').json()
    components=[item for item in circuit if item["type"]=="schematic_component"]
    traces=[item for item in circuit if item["type"]=="schematic_trace"]
    compiled=[item for item in circuit if item["type"]=="aura_electrical_connection"]
    reported=[item for item in circuit if item["type"]=="aura_unconnected_interface"]
    assert components and traces
    assert all(item.get("aura_semantic_id") for item in components)
    assert compiled and all(item.get("graphConnectionId") and item["status"]=="connected" for item in compiled)
    assert not reported
    return circuit


def test_robotic_arm_uses_generic_attachment_and_electrical_interfaces():
    with TestClient(create_app(storage_mode="memory")) as client:
        project=_project(client,"make a robotic arm")
        assembly=_assert_interface_assembly(client,project)
        assert any(item["type"]=="revolute" for item in assembly["relationships"])
        circuit=_assert_complete_schematic(client,project)
        assert len([item for item in circuit if item["type"]=="aura_electrical_connection"])>=3


def test_servo_lid_reuses_the_same_interface_and_circuit_compilers():
    with TestClient(create_app(storage_mode="memory")) as client:
        project=_project(client,"make a servo lid mechanism")
        assembly=_assert_interface_assembly(client,project)
        assert any(item["type"]=="revolute" for item in assembly["relationships"])
        circuit=_assert_complete_schematic(client,project)
        assert any(item.get("aura_semantic_id")=="component-servo" for item in circuit if item["type"]=="schematic_component")
