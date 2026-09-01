from __future__ import annotations

from copy import deepcopy

from aura.engineering_graph.model import EngineeringEntity, EngineeringGraph, EntityKind, Relationship
from aura.engineering_graph.patches import GraphOperation, GraphPatch, PatchOperation
from aura.engineering_graph.serialization import graph_to_dict
from aura.verification.results import VerificationState
from aura.verification.service import VerificationService


def port(name,role,direction=None,**metadata):
    return {"name":name,"role":role,"direction":direction,**metadata}


def component(identifier,interfaces,role="module",**parameters):
    return EngineeringEntity(identifier,EntityKind.COMPONENT,identifier,"project",{
        "role":role,"interfaces":interfaces,"parameters":parameters,
    })


def net(identifier,role,*terminals,**metadata):
    return EngineeringEntity(identifier,EntityKind.CONNECTION,identifier,"project",{
        "semantic_type":"electrical_net","role":role,
        "terminals":[{"componentId":owner,"interfaceId":interface} for owner,interface in terminals],
        **metadata,
    })


def graph(*entities,relationships=()):
    project=EngineeringEntity("project",EntityKind.PROJECT,"Candidate")
    values={item.id:item for item in (project,*entities)}
    return EngineeringGraph("project",entities=values,relationships={item.id:item for item in relationships})


def verify(candidate): return VerificationService().verify_graph(candidate)
def codes(candidate): return [item.check for item in verify(candidate).findings]


def test_full_graph_verification_is_pure_and_repeatable():
    candidate=graph(component("source",[port("out","signal","output")]),component("sink",[port("in","signal","input")]),net("signal","signal",("source","out"),("sink","in")))
    before=deepcopy(graph_to_dict(candidate));first=verify(candidate);second=verify(candidate)
    assert graph_to_dict(candidate)==before
    assert [(x.id,x.check,x.severity,x.expected,x.actual) for x in first.findings]==[(x.id,x.check,x.severity,x.expected,x.actual) for x in second.findings]
    assert first.state is second.state


def test_legacy_relationships_materialize_fallback_nets_without_mutation():
    source=component("source",[port("out","signal","output")]);sink=component("sink",[port("in","signal","input")])
    relationship=Relationship("edge","source","sink","signal",{"connection_id":"missing-legacy-connection"})
    candidate=graph(source,sink,relationships=(relationship,));before=deepcopy(graph_to_dict(candidate))
    verify(candidate)
    assert graph_to_dict(candidate)==before


def test_push_pull_outputs_on_same_net_fail_contention():
    candidate=graph(component("a",[port("d5","signal","output")]),component("b",[port("d6","signal","output")]),net("bus","signal",("a","d5"),("b","d6")))
    assert "ELEC_OUTPUT_CONTENTION" in codes(candidate)


def test_open_drain_shared_bus_avoids_false_contention():
    shared={"drive_mode":"open_drain","protocol":"i2c"}
    candidate=graph(component("a",[port("sda","signal","output",**shared)]),component("b",[port("sda","signal","output",**shared)]),net("i2c","signal",("a","sda"),("b","sda"),shared_bus=True))
    assert "ELEC_OUTPUT_CONTENTION" not in codes(candidate)


def test_required_input_only_signal_has_no_source():
    candidate=graph(component("a",[port("in","signal","input",required=True)]),component("b",[port("in","signal","input")]),net("signal","signal",("a","in"),("b","in"),required=True))
    assert "ELEC_SIGNAL_SOURCE_MISSING" in codes(candidate)


def test_incompatible_regulated_sources_fail():
    candidate=graph(
        component("five",[port("out","power_output","output",output_voltage_v=5)]),
        component("three",[port("out","power_output","output",output_voltage_v=3.3)]),
        net("rail","power",("five","out"),("three","out")))
    assert "ELEC_POWER_SOURCE_CONFLICT" in codes(candidate)


def test_equal_sources_without_parallel_semantics_warn():
    candidate=graph(
        component("one",[port("out","power_output","output",output_voltage_v=5)]),
        component("two",[port("out","power_output","output",output_voltage_v=5)]),
        net("rail","power",("one","out"),("two","out")))
    finding=next(item for item in verify(candidate).findings if item.check=="ELEC_PARALLEL_SOURCE_NOT_PROVEN")
    assert finding.state is VerificationState.ESTIMATED and not finding.blocking


def test_converter_separates_12v_and_5v_domains():
    candidate=graph(
        component("battery",[port("out","power_output","output",output_voltage_v=12)]),
        component("buck",[port("vin","power_input","input",input_voltage_range_v=[10,14]),port("vout","power_output","output",output_voltage_v=5)],role="buck_converter"),
        component("load",[port("vcc","power_input","input",input_voltage_range_v=[4.5,5.5])]),
        net("rail12","power",("battery","out"),("buck","vin")),net("rail5","power",("buck","vout"),("load","vcc")))
    found=codes(candidate)
    assert "ELEC_POWER_SOURCE_CONFLICT" not in found and "ELEC_POWER_DOMAIN_INCOMPATIBLE" not in found


def test_direct_incompatible_power_domain_fails():
    candidate=graph(component("source",[port("out","power_output","output",output_voltage_v=12)]),component("load",[port("vcc","power_input","input",input_voltage_range_v=[4.5,5.5])]),net("rail","power",("source","out"),("load","vcc")))
    assert "ELEC_POWER_DOMAIN_INCOMPATIBLE" in codes(candidate)


def test_power_to_ground_net_role_conflict_fails():
    candidate=graph(component("source",[port("out","power_output","output")]),component("return",[port("gnd","ground","input")]),net("short","ground",("source","out"),("return","gnd")))
    assert "ELEC_NET_ROLE_CONFLICT" in codes(candidate)


def test_missing_required_driver_supply_port_fails():
    driver=component("driver",[port("vcc","power_input","input",required=True),port("vm","power_input","input",required=True),port("in","signal","input")],role="motor_driver")
    source=component("logic-supply",[port("out","power_output","output")])
    candidate=graph(driver,source,net("logic","power",("logic-supply","out"),("driver","vcc")))
    finding=next(item for item in verify(candidate).findings if item.check=="ELEC_REQUIRED_PORT_UNCONNECTED")
    assert "vm" in finding.interface_ids


def test_input_only_required_power_net_has_no_source():
    driver=component("driver",[port("vm","power_input","input",required=True)],role="motor_driver")
    motor=component("motor",[port("power","power_input","input",required=True)],role="small_dc_motor")
    candidate=graph(driver,motor,net("unpowered","power",("driver","vm"),("motor","power")))
    assert "ELEC_POWER_SOURCE_MISSING" in codes(candidate)


def test_i2c_required_scl_missing_fails_bus_completeness():
    sensor=component("sensor",[port("sda","signal","input",protocol="i2c"),port("scl","signal","input",protocol="i2c")],required_protocol_ports={"i2c":["sda","scl"]})
    controller=component("controller",[port("sda","signal","output",protocol="i2c",drive_mode="open_drain")])
    candidate=graph(sensor,controller,net("i2c","signal",("sensor","sda"),("controller","sda"),shared_bus=True))
    assert "ELEC_BUS_INCOMPLETE" in codes(candidate)


def test_uart_tx_to_tx_fails_direction():
    candidate=graph(component("a",[port("tx","signal","output",protocol="uart",protocol_role="tx")]),component("b",[port("tx","signal","output",protocol="uart",protocol_role="tx")]),net("uart","signal",("a","tx"),("b","tx")))
    found=codes(candidate)
    assert "ELEC_PROTOCOL_DIRECTION_INVALID" in found


def test_same_pin_on_two_graph_owned_nets_fails():
    controller=component("controller",[port("d6","signal","output")])
    left=component("left",[port("in","signal","input")]);right=component("right",[port("in","signal","input")])
    candidate=graph(controller,left,right,net("one","signal",("controller","d6"),("left","in")),net("two","signal",("controller","d6"),("right","in")))
    assert "ELEC_PIN_RESOURCE_CONFLICT" in codes(candidate)


def test_fixed_i2c_address_conflict_on_same_bus_fails():
    shared=lambda name: component(name,[port("sda","signal","input",protocol="i2c")],i2c_address="0x40",i2c_address_configurable=False)
    candidate=graph(shared("a"),shared("b"),net("i2c","signal",("a","sda"),("b","sda"),shared_bus=True))
    assert "ELEC_I2C_ADDRESS_CONFLICT" in codes(candidate)


def test_unique_i2c_addresses_pass_address_check():
    a=component("a",[port("sda","signal","input",protocol="i2c")],i2c_address="0x40")
    b=component("b",[port("sda","signal","input",protocol="i2c")],i2c_address="0x41")
    candidate=graph(a,b,net("i2c","signal",("a","sda"),("b","sda"),shared_bus=True))
    assert "ELEC_I2C_ADDRESS_CONFLICT" not in codes(candidate)


def test_common_ground_is_path_specific():
    a=component("controller",[port("gnd","ground","input")],requires_common_ground_with=["servo"])
    b=component("servo",[port("gnd","ground","input")]);x=component("x",[port("gnd","ground","input")]);y=component("y",[port("gnd","ground","input")])
    candidate=graph(a,b,x,y,net("ground-a","ground",("controller","gnd"),("x","gnd")),net("ground-b","ground",("servo","gnd"),("y","gnd")))
    assert "ELEC_COMMON_GROUND_REQUIRED" in codes(candidate)


def test_declared_isolation_avoids_common_ground_false_failure():
    a=component("controller",[port("gnd","ground","input")],requires_common_ground_with=["device"],galvanically_isolated=True)
    b=component("device",[port("gnd","ground","input")])
    candidate=graph(a,b,net("a","ground",("controller","gnd")),net("b","ground",("device","gnd")))
    assert "ELEC_COMMON_GROUND_REQUIRED" not in codes(candidate)


def test_power_budget_is_checked_on_actual_supply_net():
    source=component("source",[port("out","power_output","output")],available_current_a=1)
    load=component("load",[port("in","power_input","input")],peak_current_a=2)
    candidate=graph(source,load,net("rail","power",("source","out"),("load","in")))
    assert "POWER_BUDGET_EXCEEDED" in codes(candidate)


def test_incomplete_domain_current_data_warns_not_fails():
    source=component("source",[port("out","power_output","output")],available_current_a=2)
    load=component("load",[port("in","power_input","input")])
    finding=next(item for item in verify(graph(source,load,net("rail","power",("source","out"),("load","in")))).findings if item.check=="POWER_BUDGET_NOT_PROVEN")
    assert finding.state is VerificationState.ESTIMATED and not finding.blocking


def test_direct_logic_level_mismatch_fails_even_with_unrelated_shifter():
    source=component("source",[port("out","signal","output",logic_output_voltage_v=5)])
    target=component("target",[port("in","signal","input",accepted_logic_voltage_range_v=[0,3.6])])
    shifter=component("unrelated-shifter",[port("a","signal","input"),port("b","signal","output")],role="level_shifter")
    candidate=graph(source,target,shifter,net("direct","signal",("source","out"),("target","in")))
    assert "ELEC_LOGIC_LEVEL_INCOMPATIBLE" in codes(candidate)


def test_level_shifter_in_path_separates_logic_domains():
    source=component("source",[port("out","signal","output",logic_output_voltage_v=5)])
    shifter=component("shifter",[port("high","signal","input",accepted_logic_voltage_range_v=[4.5,5.5]),port("low","signal","output",logic_output_voltage_v=3.3)],role="level_shifter")
    target=component("target",[port("in","signal","input",accepted_logic_voltage_range_v=[0,3.6])])
    candidate=graph(source,shifter,target,net("high","signal",("source","out"),("shifter","high")),net("low","signal",("shifter","low"),("target","in")))
    assert "ELEC_LOGIC_LEVEL_INCOMPATIBLE" not in codes(candidate)


def test_axis_requires_unique_mechanical_target_path():
    actuator=component("servo",[],controlled_axis_ids=["yaw"]);target=component("panel",[],driven_axis_ids=["yaw"])
    assert "MECH_AXIS_PATH_INCOMPLETE" in codes(graph(actuator,target))


def test_complete_axis_mechanical_path_passes():
    actuator=component("servo",[],controlled_axis_ids=["yaw"]);target=component("panel",[],driven_axis_ids=["yaw"])
    relation=Relationship("drive","servo","panel","mechanical")
    assert "MECH_AXIS_PATH_INCOMPLETE" not in codes(graph(actuator,target,relationships=(relation,)))


def control_graph(complete=True):
    sensor=component("sensor",[],role="sensor",functional_roles=["sensing"])
    controller=component("controller",[],role="controller")
    driver=component("driver",[],role="motor_driver")
    motor=component("motor",[],role="small_dc_motor")
    requirement=EngineeringEntity("requirement",EntityKind.REQUIREMENT,"Automatic motion","project",{"required_control_chain":["sensing","controller","motor_driver","small_dc_motor"]})
    relations=[Relationship("sense","sensor","controller","signal"),Relationship("command","controller","driver","control")]
    if complete: relations.append(Relationship("drive","driver","motor","switched-power"))
    return graph(sensor,controller,driver,motor,requirement,relationships=relations)


def test_full_graph_control_chain_requires_every_ordered_stage():
    assert "REQ_CONTROL_CHAIN_INCOMPLETE" in codes(control_graph(False))


def test_full_graph_control_chain_passes_complete_role_path():
    assert "REQ_CONTROL_CHAIN_INCOMPLETE" not in codes(control_graph(True))


def test_exact_identity_does_not_verify_estimated_property():
    item=component("servo",[],resolution_quality="EXACT",property_facts={"available_torque_nm":{"value":.18,"unit":"N*m","status":"estimated","evidence_id":"estimate"}})
    assert "EVIDENCE_PROPERTY_NOT_VERIFIED" in codes(graph(item))


def test_stale_critical_property_is_visible():
    item=component("servo",[],property_facts={"available_torque_nm":{"value":.18,"unit":"N*m","status":"stale","evidence_id":"old"}})
    assert "EVIDENCE_PROPERTY_STALE" in codes(graph(item))


def test_conflicting_property_values_are_not_silently_selected():
    facts=[{"value":5,"unit":"V","status":"source_verified","evidence_id":"a"},{"value":12,"unit":"V","status":"source_verified","evidence_id":"b"}]
    item=component("controller",[],property_facts={"input_voltage_v":facts})
    assert "EVIDENCE_PROPERTY_CONFLICT" in codes(graph(item))


def test_modification_delegates_to_complete_graph_verification():
    source=component("source",[port("out","power_output","output")]);return_path=component("return",[port("gnd","ground","input")])
    candidate=graph(source,return_path,net("rail","power",("source","out"),("return","gnd")))
    # Initially the net is already contradictory; changing unrelated metadata
    # must still run the complete graph and reject it.
    patch=GraphPatch("candidate-change",(GraphOperation(PatchOperation.UPDATE_ENTITY,target_id="source",changes={"name":"changed source"}),),"candidate")
    result=VerificationService().verify_modification(candidate,patch)
    assert not result.accepted and "ELEC_NET_ROLE_CONFLICT" in [item.check for item in result.findings]


def load_path(integrated=False):
    driver=component("driver",[
        port("logic","signal","input"),port("supply","power_input","input"),port("out","power_output","output")],
        role="motor_driver",switching_stage=True,integrated_protection=integrated)
    motor=component("motor",[port("power","power_input","input")],role="small_dc_motor",requires_driver=True,inductive_load=True)
    return driver,motor,net("motor-rail","switched-power",("driver","out"),("motor","power"))


def test_driver_in_load_net_still_requires_control_and_supply_topology():
    driver,motor,rail=load_path()
    assert "ELEC_SWITCHING_PATH_INCOMPLETE" in codes(graph(driver,motor,rail))


def test_unrelated_diode_does_not_prove_inductive_protection():
    driver,motor,rail=load_path()
    diode=component("diode",[port("k","power","passive")],role="flyback_diode",protects_load_ids=[])
    assert "ELEC_INDUCTIVE_PROTECTION_REQUIRED" in codes(graph(driver,motor,diode,rail))


def test_protection_must_target_and_share_actual_load_path():
    driver,motor,rail=load_path()
    diode=component("diode",[port("k","power","passive")],role="flyback_diode",protects_load_ids=["motor"])
    protected=net("motor-rail","switched-power",("driver","out"),("motor","power"),("diode","k"))
    assert "ELEC_INDUCTIVE_PROTECTION_REQUIRED" not in codes(graph(driver,motor,diode,protected))


def test_integrated_driver_protection_avoids_external_diode_requirement():
    driver,motor,rail=load_path(integrated=True)
    assert "ELEC_INDUCTIVE_PROTECTION_REQUIRED" not in codes(graph(driver,motor,rail))


def test_complete_integrated_switching_stage_avoids_topology_false_failure():
    driver,motor,rail=load_path(integrated=True)
    controller=component("controller",[port("gpio","signal","output")])
    supply=component("supply",[port("out","power_output","output")])
    candidate=graph(driver,motor,controller,supply,rail,
        net("control","control",("controller","gpio"),("driver","logic")),
        net("driver-supply","power",("supply","out"),("driver","supply")))
    assert "ELEC_SWITCHING_PATH_INCOMPLETE" not in codes(candidate)


def test_modified_component_invalidates_old_targeted_evidence():
    target=component("target",[])
    evidence=EngineeringEntity("evidence-old",EntityKind.EVIDENCE,"Old property evidence","project",{"appliesTo":["target"]},verification_status="source_verified")
    candidate=graph(target,evidence)
    patch=GraphPatch("rename",(GraphOperation(PatchOperation.UPDATE_ENTITY,target_id="target",changes={"name":"replacement"}),),"replace")
    verified=VerificationService().verify_modification(candidate,patch)
    evidence_update=next(item for item in verified.patch.operations if item.target_id=="evidence-old")
    assert evidence_update.changes["verification_status"]=="stale"
