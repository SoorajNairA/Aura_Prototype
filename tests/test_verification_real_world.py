from __future__ import annotations

from dataclasses import replace

from fastapi.testclient import TestClient

from aura.engineering_graph.model import EntityKind
from aura.planner.schemas import ComponentSpec, ConnectionSpec, PlannedEntity, ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.results import VerificationState
from aura.verification.service import VerificationService
from aura.workspace.server import create_app


def base_plan():
    plan=PlannerService().irrigation_benchmark_plan(ProjectRequest(
        "Verification fixture","Design a low-voltage automatic pump",("Switch the pump automatically",)))
    project=next(item for item in plan.entities if item.kind is EntityKind.PROJECT)
    metadata=dict(project.metadata);metadata["strict_verification"]=True
    entities=tuple(replace(item,metadata=tuple(metadata.items())) if item.id==project.id else item for item in plan.entities)
    return replace(plan,entities=entities)


def component(plan, component_id, **changes):
    return replace(plan,components=tuple(replace(item,**changes) if item.id==component_id else item for item in plan.components))


def parameters(plan, component_id, **changes):
    item=next(value for value in plan.components if value.id==component_id)
    return component(plan,component_id,parameters=dict(item.parameters)|changes)


def connections(plan, *items):
    return replace(plan,connections=tuple(items))


def result(plan): return VerificationService().verify(plan)
def codes(plan): return [item.check for item in result(plan).findings]


def direct_load(plan, role="small_dc_motor", name="DC motor"):
    plan=component(plan,"component-pump",role=role,name=name)
    direct=ConnectionSpec("direct-gpio","component-esp32","component-pump","gpio-pump","power+","control","unsafe direct drive")
    return replace(plan,connections=tuple(item for item in plan.connections if item.target_id!="component-pump")+(direct,))


def test_dc_motor_direct_gpio_requires_driver():
    assert "ELEC_DRIVER_REQUIRED" in codes(direct_load(base_plan()))


def test_pump_direct_gpio_requires_driver():
    assert "ELEC_DRIVER_REQUIRED" in codes(direct_load(base_plan(),"small_dc_pump","Pump"))


def test_unrelated_driver_does_not_hide_direct_gpio():
    plan=direct_load(base_plan())
    assert any(item.id=="component-driver" for item in plan.components)
    assert "ELEC_DRIVER_REQUIRED" in codes(plan)


def test_connected_driver_satisfies_driver_architecture():
    assert "ELEC_DRIVER_REQUIRED" not in codes(base_plan())


def test_bare_relay_coil_direct_gpio_requires_driver():
    assert "ELEC_DRIVER_REQUIRED" in codes(direct_load(base_plan(),"bare_relay","Bare relay coil"))


def test_integrated_relay_module_does_not_require_redundant_driver():
    plan=component(base_plan(),"component-pump",role="relay_module",name="Protected relay module")
    assert not any(item.check=="ELEC_DRIVER_REQUIRED" and "component-pump" in item.entity_ids for item in result(plan).findings)


def test_servo_signal_without_power_fails_required_power():
    plan=component(base_plan(),"component-pump",role="servo",name="Servo",interfaces=("power","ground","signal"))
    signal=ConnectionSpec("servo-signal","component-esp32","component-pump","gpio-pump","signal","control","PWM signal")
    plan=replace(plan,connections=tuple(item for item in plan.connections if item.target_id!="component-pump")+(signal,))
    assert "ELEC_POWER_REQUIRED" in codes(plan)


def test_servo_signal_is_not_accepted_as_power():
    plan=component(base_plan(),"component-pump",role="servo",name="Servo",interfaces=("power","ground","signal"))
    bad=ConnectionSpec("servo-bad","component-esp32","component-pump","gpio-pump","power","control","signal into power")
    plan=replace(plan,connections=tuple(item for item in plan.connections if item.target_id!="component-pump")+(bad,))
    assert "ELEC_PORT_ROLE_INCOMPATIBLE" in codes(plan)


def test_missing_common_ground_is_component_specific():
    plan=replace(base_plan(),connections=tuple(item for item in base_plan().connections if item.connection_type!="ground"))
    findings=[item for item in result(plan).findings if item.check=="ELEC_COMMON_GROUND_REQUIRED"]
    assert findings and all(item.interface_ids for item in findings)


def test_known_voltage_mismatch_fails():
    plan=parameters(base_plan(),"component-power",voltage_v=12.0)
    assert "ELEC_VOLTAGE_INCOMPATIBLE" in codes(plan)


def test_unknown_voltage_warns_without_failure():
    power=next(item for item in base_plan().components if item.id=="component-power")
    values=dict(power.parameters);values.pop("voltage_v")
    plan=component(base_plan(),"component-power",parameters=values)
    findings=[item for item in result(plan).findings if item.check=="ELEC_VOLTAGE_NOT_PROVEN"]
    assert findings and all(item.state is VerificationState.ESTIMATED and not item.blocking for item in findings)


def test_inductive_load_without_proven_protection_warns():
    plan=parameters(base_plan(),"component-driver",flyback_protection=False,protection_required=False)
    finding=next(item for item in result(plan).findings if item.check=="ELEC_INDUCTIVE_PROTECTION_REQUIRED")
    assert finding.state is VerificationState.ESTIMATED and not finding.blocking


def test_known_required_inductive_protection_failure_blocks():
    plan=parameters(base_plan(),"component-driver",flyback_protection=False,protection_required=True)
    finding=next(item for item in result(plan).findings if item.check=="ELEC_INDUCTIVE_PROTECTION_REQUIRED")
    assert finding.state is VerificationState.FAILED and finding.blocking


def test_integrated_motor_driver_satisfies_protection():
    plan=component(base_plan(),"component-driver",role="motor_driver",name="Integrated motor driver")
    assert "ELEC_INDUCTIVE_PROTECTION_REQUIRED" not in codes(plan)


def test_protocol_mismatch_fails_only_with_known_protocols():
    plan=parameters(base_plan(),"component-sensor",output_protocol="i2c")
    plan=parameters(plan,"component-esp32",accepted_protocols=["pwm"])
    assert "ELEC_PROTOCOL_INCOMPATIBLE" in codes(plan)


def test_unknown_protocol_does_not_invent_mismatch():
    assert "ELEC_PROTOCOL_INCOMPATIBLE" not in codes(base_plan())


def axis_plan():
    return PlannerService().plan(ProjectRequest("Axes","Build a two-axis controlled panel",("Provide two independent axes",)))


def test_two_valid_axis_ids_pass_distinct_axis_rule():
    assert "MECH_CONTROLLED_AXIS_MISSING" not in codes(axis_plan())


def test_two_actuators_on_same_axis_fail_distinct_axis_rule():
    plan=axis_plan();actuators=[item for item in plan.components if "controlled_motion" in item.parameters.get("functional_roles",())]
    changed=[]
    for item in plan.components:
        if item in actuators: changed.append(replace(item,parameters=dict(item.parameters)|{"controlled_axis_ids":["axis-1"]}))
        else: changed.append(item)
    assert "MECH_CONTROLLED_AXIS_MISSING" in codes(replace(plan,components=tuple(changed)))


def test_required_prismatic_joint_rejects_revolute_mechanism():
    plan=axis_plan();requirement=next(item for item in plan.entities if item.kind is EntityKind.REQUIREMENT and dict(item.metadata).get("required_axes"))
    metadata=dict(requirement.metadata)|{"required_joint_types":["prismatic","prismatic"]}
    plan=replace(plan,entities=tuple(replace(item,metadata=tuple(metadata.items())) if item.id==requirement.id else item for item in plan.entities))
    assert "MECH_JOINT_TYPE_INCOMPATIBLE" in codes(plan)


def test_known_insufficient_actuator_torque_fails():
    plan=parameters(base_plan(),"component-pump",functional_roles=["controlled_motion"],available_torque_nm=.2,required_torque_nm=1.0)
    assert "MECH_ACTUATOR_CAPABILITY_INSUFFICIENT" in codes(plan)


def test_unknown_actuator_torque_is_not_proven_warning():
    plan=parameters(base_plan(),"component-pump",functional_roles=["controlled_motion"])
    finding=next(item for item in result(plan).findings if item.check=="MECH_ACTUATOR_CAPABILITY_NOT_PROVEN")
    assert finding.state is VerificationState.ESTIMATED and not finding.blocking


def add_requirement(plan, requirement_id, **metadata):
    project=next(item for item in plan.entities if item.kind is EntityKind.PROJECT)
    entity=PlannedEntity(requirement_id,EntityKind.REQUIREMENT,metadata.pop("label","Functional requirement"),project.id,tuple(metadata.items()))
    return replace(plan,entities=plan.entities+(entity,))


def test_directional_sensing_is_not_satisfied_by_ambient_measurement():
    plan=parameters(base_plan(),"component-sensor",capabilities=["ambient_light"])
    plan=add_requirement(plan,"requirement-direction",required_capabilities=["directional_light"],critical=True,label="Detect strongest-light direction")
    assert "REQ_NOT_FUNCTIONALLY_SATISFIED" in codes(plan)


def test_directional_capability_satisfies_functional_requirement():
    plan=parameters(base_plan(),"component-sensor",capabilities=["directional_light"])
    plan=add_requirement(plan,"requirement-direction",required_capabilities=["directional_light"],critical=True,label="Detect strongest-light direction")
    assert "REQ_NOT_FUNCTIONALLY_SATISFIED" not in codes(plan)


def test_disconnected_components_fail_required_control_chain():
    plan=add_requirement(base_plan(),"requirement-chain",required_control_chain=["soil sensing","controller","small_dc_pump"],critical=True,label="Automatic pumping")
    plan=replace(plan,connections=tuple(item for item in plan.connections if item.connection_type not in {"signal","control","switched-power"}))
    assert "REQ_CONTROL_CHAIN_INCOMPLETE" in codes(plan)


def test_connected_sensor_controller_driver_load_chain_passes():
    plan=add_requirement(base_plan(),"requirement-chain",required_control_chain=["soil sensing","controller","small_dc_pump"],critical=True,label="Automatic pumping")
    assert "REQ_CONTROL_CHAIN_INCOMPLETE" not in codes(plan)


def test_named_hardware_identity_loss_is_structured():
    plan=base_plan();project=next(item for item in plan.entities if item.kind is EntityKind.PROJECT)
    metadata=dict(project.metadata)|{"required_component_identities":["Arduino Nano"],"identity_mandatory":True}
    plan=replace(plan,entities=tuple(replace(item,metadata=tuple(metadata.items())) if item.id==project.id else item for item in plan.entities))
    assert "COMPONENT_EXPLICIT_IDENTITY_LOST" in codes(plan)


def test_named_hardware_identity_preserved():
    plan=component(base_plan(),"component-esp32",name="Arduino Nano")
    project=next(item for item in plan.entities if item.kind is EntityKind.PROJECT)
    metadata=dict(project.metadata)|{"required_component_identities":["Arduino Nano"]}
    plan=replace(plan,entities=tuple(replace(item,metadata=tuple(metadata.items())) if item.id==project.id else item for item in plan.entities))
    assert "COMPONENT_EXPLICIT_IDENTITY_LOST" not in codes(plan)


def test_critical_unresolved_component_prevents_clean_state():
    plan=parameters(base_plan(),"component-sensor",functional_roles=["feedback_custom"],resolution_quality="UNRESOLVED")
    project=next(item for item in plan.entities if item.kind is EntityKind.PROJECT)
    project_metadata=dict(project.metadata);project_metadata["strict_verification"]=False
    plan=replace(plan,entities=tuple(replace(item,metadata=tuple(project_metadata.items())) if item.id==project.id else item for item in plan.entities))
    plan=add_requirement(plan,"requirement-custom",required_roles=["feedback_custom"],critical=True,label="Critical sensing")
    verified=result(plan)
    assert "COMPONENT_CRITICAL_UNRESOLVED" in [item.check for item in verified.findings]
    assert verified.state is VerificationState.ESTIMATED


def test_findings_expose_bounded_repair_context():
    finding=next(item for item in result(direct_load(base_plan())).findings if item.check=="ELEC_DRIVER_REQUIRED")
    payload=finding.to_dict()
    assert payload["blocking"] and payload["category"]=="electrical"
    assert payload["requiredCapability"] and payload["repairHint"] and payload["semanticIds"]


def test_finding_ids_and_order_are_deterministic():
    first=result(direct_load(base_plan())).findings
    second=result(direct_load(base_plan())).findings
    assert [(item.id,item.check,item.entity_ids) for item in first]==[(item.id,item.check,item.entity_ids) for item in second]


def test_verification_does_not_mutate_plan():
    plan=direct_load(base_plan());before=repr(plan)
    result(plan)
    assert repr(plan)==before


def test_project_readiness_exposes_verification_limitations():
    with TestClient(create_app(storage_mode="memory")) as client:
        response=client.post("/api/projects",json={"objective":"Design a small ESP32 automatic irrigation system","planningMode":"deterministic_test"})
        assert response.status_code==201
        assert response.json()["status"]!="ready"
