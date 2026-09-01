from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable

from aura.engineering_graph.electrical import electrical_nets
from aura.engineering_graph.model import EngineeringEntity, EngineeringGraph, EntityKind

from .results import VerificationState


AddFinding = Callable[..., None]
ELECTRICAL_RELATIONSHIPS={"power","ground","control","signal","regulated-power","switched-power"}


def _data(entity: EngineeringEntity) -> dict[str, Any]:
    metadata=dict(entity.metadata);parameters=metadata.get("parameters",{})
    return metadata|dict(parameters if isinstance(parameters,dict) else {})


def _family(entity: EngineeringEntity) -> str:
    data=_data(entity)
    return str(data.get("family",data.get("role",""))).lower()


def _port_records(entity: EngineeringEntity) -> dict[str, dict[str, Any]]:
    data=_data(entity);raw=data.get("interfaces",());roles=data.get("interface_roles",{});directions=data.get("port_direction",data.get("port_directions",{}))
    records={}
    for item in raw:
        if isinstance(item,str): name=item;record={}
        else:
            record=dict(item);name=str(record.get("id",record.get("name",record.get("interfaceId","")))).rsplit(":",1)[-1]
        if not name: continue
        role=record.get("role",record.get("kind",roles.get(name)))
        direction=record.get("direction",directions.get(name))
        records[name]=record|{"name":name,"role":str(role).lower() if role else None,"direction":str(direction).lower() if direction else None}
    # Older committed graphs store interface names separately from additive metadata.
    for name in data.get("required_interfaces",()):
        records.setdefault(str(name),{"name":str(name),"role":roles.get(name),"direction":directions.get(name)})["required"]=True
    return records


def _role(port: dict[str, Any]) -> str:
    role=str(port.get("role") or "").lower();name=str(port.get("name") or "").lower()
    if "ground" in role or name in {"gnd","ground","logic-gnd"}: return "ground"
    if any(value in role for value in ("power_out","power output","supply_output")): return "power_output"
    if any(value in role for value in ("power_in","power input","supply_input")): return "power_input"
    if any(value in name for value in ("vcc","vin","power","supply","vm","v+","load-in")): return "power"
    if any(value in role for value in ("signal","control","digital","analog","pwm","uart","i2c","spi")): return "signal"
    if any(value in name for value in ("gpio","signal","pwm","sda","scl","tx","rx","mosi","miso","clock","select")): return "signal"
    return role or "unknown"


def _voltage(port: dict[str, Any], component: EngineeringEntity) -> tuple[float,float] | None:
    data=_data(component)
    value=port.get("output_voltage_v",port.get("voltage_v"))
    bounds=port.get("voltage_range_v",port.get("input_voltage_range_v"))
    if bounds is None:
        if _role(port)=="power_output": bounds=data.get("output_voltage_range_v")
        elif _role(port) in {"power","power_input"}: bounds=data.get("input_voltage_range_v")
    if value is None:
        if _role(port)=="power_output": value=data.get("output_voltage_v")
        elif _role(port) in {"power","power_input"}: value=data.get("input_voltage_v")
    if bounds is not None: return float(bounds[0]),float(bounds[1])
    if value is not None: return float(value),float(value)
    return None


@dataclass(frozen=True)
class Terminal:
    component: EngineeringEntity
    interface_id: str
    port: dict[str, Any]


def evaluate_graph(graph: EngineeringGraph, add: AddFinding) -> None:
    """Inspect a complete graph without changing it; graph-owned nets are authoritative."""
    components={item.id:item for item in graph.find(kind=EntityKind.COMPONENT)}
    ports={key:_port_records(value) for key,value in components.items()}
    nets=electrical_nets(graph)
    terminal_net: dict[tuple[str,str],str]={}
    net_terminals: dict[str,list[Terminal]]={}

    for net in sorted(nets,key=lambda item:item["netId"]):
        net_id=net["netId"];terminals=[]
        for raw in net.get("terminals",()):
            component_id=str(raw.get("componentId",""));interface_id=str(raw.get("interfaceId",""))
            component=components.get(component_id);port=ports.get(component_id,{}).get(interface_id)
            if component is None or port is None:
                add("ELEC_NET_TERMINAL_INVALID",VerificationState.FAILED,"critical",f"Net {net_id} references missing terminal {component_id}:{interface_id}.",(component_id,),category="electrical",net_ids=(net_id,),interface_ids=(interface_id,),actual={"terminal":raw},blocking=True)
                continue
            key=(component_id,interface_id)
            if key in terminal_net and terminal_net[key]!=net_id:
                add("ELEC_PIN_RESOURCE_CONFLICT",VerificationState.FAILED,"critical",f"{component_id}:{interface_id} is assigned to incompatible nets.",(component_id,),category="electrical",net_ids=(terminal_net[key],net_id),interface_ids=(interface_id,),actual={"netIds":[terminal_net[key],net_id]},blocking=True)
            terminal_net[key]=net_id;terminals.append(Terminal(component,interface_id,port))
        if not terminals: continue
        net_terminals[net_id]=terminals
        roles=[_role(item.port) for item in terminals]
        directions=[str(item.port.get("direction") or "") for item in terminals]
        net_role=str(net.get("role","")).lower()

        if ("ground" in roles and any(role in {"power","power_output"} for role in roles)) or (net_role=="ground" and "power_output" in roles) or ("signal" in roles and net_role in {"power","ground"}):
            add("ELEC_NET_ROLE_CONFLICT",VerificationState.FAILED,"critical",f"Net {net_id} joins contradictory electrical roles.",tuple(sorted({item.component.id for item in terminals})),category="electrical",net_ids=(net_id,),interface_ids=tuple(item.interface_id for item in terminals),expected={"coherentNetRole":True},actual={"netRole":net_role,"terminalRoles":roles},blocking=True)

        active=[item for item in terminals if item.port.get("direction") in {"output","source"} and str(item.port.get("drive_mode","push_pull")) not in {"open_drain","open_collector","tri_state"}]
        if net_role in {"signal","control"} and len(active)>1 and not net.get("shared_bus"):
            add("ELEC_OUTPUT_CONTENTION",VerificationState.FAILED,"critical",f"Net {net_id} joins multiple actively driven outputs.",tuple(item.component.id for item in active),category="electrical",net_ids=(net_id,),interface_ids=tuple(item.interface_id for item in active),actual={"activeOutputs":[f"{item.component.id}:{item.interface_id}" for item in active]},required_capability="explicit_shared_bus_or_single_driver",blocking=True)
        required_signal=bool(net.get("required") or any(item.port.get("required") for item in terminals))
        if net_role in {"signal","control"} and required_signal and directions and all(value in {"input","sink"} for value in directions):
            add("ELEC_SIGNAL_SOURCE_MISSING",VerificationState.FAILED,"critical",f"Required signal net {net_id} contains inputs but no source.",tuple(item.component.id for item in terminals),category="electrical",net_ids=(net_id,),interface_ids=tuple(item.interface_id for item in terminals),actual={"directions":directions},required_capability="signal_source",blocking=True)

        sources=[item for item in terminals if _role(item.port)=="power_output" and item.port.get("direction") in {None,"output","source"}]
        if len(sources)>1:
            ranges=[_voltage(item.port,item.component) for item in sources]
            known=[value for value in ranges if value is not None]
            incompatible=len(known)>1 and max(value[0] for value in known)>min(value[1] for value in known)
            parallel=all(item.port.get("parallel_capable") for item in sources)
            code="ELEC_POWER_SOURCE_CONFLICT" if incompatible else "ELEC_PARALLEL_SOURCE_NOT_PROVEN"
            state=VerificationState.FAILED if incompatible else VerificationState.ESTIMATED
            if incompatible or not parallel:
                add(code,state,"critical" if incompatible else "warning",f"Net {net_id} directly joins multiple regulated sources"+(" with incompatible voltage domains." if incompatible else " without proven current-sharing support."),tuple(item.component.id for item in sources),category="electrical",net_ids=(net_id,),interface_ids=tuple(item.interface_id for item in sources),actual={"sourceRangesV":ranges,"parallelCapable":parallel},required_capability="compatible_power_combining",blocking=incompatible)

        source_ranges=[(_voltage(item.port,item.component),item) for item in sources]
        inputs=[item for item in terminals if _role(item.port) in {"power","power_input"}]
        if net_role in {"power","regulated-power","switched-power"} and not sources and any(item.port.get("required") for item in inputs):
            add("ELEC_POWER_SOURCE_MISSING",VerificationState.FAILED,"critical",f"Required power net {net_id} contains loads but no represented source output.",tuple(item.component.id for item in inputs),category="electrical",net_ids=(net_id,),interface_ids=tuple(item.interface_id for item in inputs),actual={"sourceOutputs":[],"loadInputs":[f"{item.component.id}:{item.interface_id}" for item in inputs]},required_capability="power_source_output",blocking=True)
        for source_range,source in source_ranges:
            if source_range is None: continue
            for target in inputs:
                target_range=_voltage(target.port,target.component)
                if target_range is not None and max(source_range[0],target_range[0])>min(source_range[1],target_range[1]):
                    add("ELEC_POWER_DOMAIN_INCOMPATIBLE",VerificationState.FAILED,"critical",f"Net {net_id} directly joins incompatible source and input voltage domains.",(source.component.id,target.component.id),category="electrical",net_ids=(net_id,),interface_ids=(source.interface_id,target.interface_id),expected={"inputRangeV":target_range},actual={"sourceRangeV":source_range},required_capability="converter_separated_voltage_domain",blocking=True)

        signal_outputs=[item for item in terminals if item.port.get("direction") in {"output","source"}]
        signal_inputs=[item for item in terminals if item.port.get("direction") in {"input","sink"}]
        if net_role in {"signal","control"}:
            for source in signal_outputs:
                source_value=source.port.get("logic_output_voltage_v",_data(source.component).get("logic_output_voltage_v"))
                if source_value is None: continue
                for target in signal_inputs:
                    accepted=target.port.get("accepted_logic_voltage_range_v",_data(target.component).get("accepted_logic_voltage_range_v"))
                    if accepted is not None and not float(accepted[0])<=float(source_value)<=float(accepted[1]):
                        add("ELEC_LOGIC_LEVEL_INCOMPATIBLE",VerificationState.FAILED,"critical",f"Net {net_id} directly connects {source_value} V logic to an incompatible input.",(source.component.id,target.component.id),category="electrical",net_ids=(net_id,),interface_ids=(source.interface_id,target.interface_id),expected={"acceptedLogicRangeV":accepted},actual={"logicOutputVoltageV":source_value},required_capability="level_shifter_in_signal_path",blocking=True)

        # Domain-specific budget: only loads and source capacity on this rail.
        if net_role in {"power","regulated-power","switched-power"}:
            capacities=[_data(item.component).get("available_current_a") for item in sources]
            loads=[item for item in terminals if _role(item.port) in {"power","power_input"}]
            currents=[_data(item.component).get("peak_current_a",_data(item.component).get("stall_current_a",_data(item.component).get("current_a"))) for item in loads]
            if sources and loads:
                if all(value is not None for value in capacities+currents):
                    capacity=sum(map(float,capacities));demand=sum(map(float,currents))
                    if demand>capacity:
                        add("POWER_BUDGET_EXCEEDED",VerificationState.FAILED,"critical",f"Net {net_id} load demand {demand:g} A exceeds represented capacity {capacity:g} A.",tuple(item.component.id for item in sources+loads),category="electrical",net_ids=(net_id,),expected={"maximumA":capacity},actual={"peakDemandA":demand},blocking=True)
                elif any(value is not None for value in capacities+currents):
                    add("POWER_BUDGET_NOT_PROVEN",VerificationState.ESTIMATED,"warning",f"Net {net_id} has incomplete source/load current data.",tuple(item.component.id for item in sources+loads),category="electrical",net_ids=(net_id,),actual={"sourceCapacityA":capacities,"loadCurrentA":currents})

        protocols={str(item.port.get("protocol")).lower() for item in terminals if item.port.get("protocol")}
        if len(protocols)>1:
            add("ELEC_PROTOCOL_INCOMPATIBLE",VerificationState.FAILED,"critical",f"Net {net_id} mixes incompatible protocols {sorted(protocols)}.",tuple(item.component.id for item in terminals),category="electrical",net_ids=(net_id,),actual={"protocols":sorted(protocols)},blocking=True)
        if "uart" in protocols:
            tx=[item for item in terminals if str(item.port.get("protocol_role",item.interface_id)).lower()=="tx"]
            rx=[item for item in terminals if str(item.port.get("protocol_role",item.interface_id)).lower()=="rx"]
            if len(tx)!=1 or not rx:
                add("ELEC_PROTOCOL_DIRECTION_INVALID",VerificationState.FAILED,"critical",f"UART net {net_id} does not contain one TX source and at least one RX sink.",tuple(item.component.id for item in terminals),category="electrical",net_ids=(net_id,),actual={"txCount":len(tx),"rxCount":len(rx)},blocking=True)

    # Required ports and protocol completeness are component-specific.
    for component_id,component in sorted(components.items()):
        records=ports[component_id]
        missing=[name for name,port in records.items() if port.get("required") and (component_id,name) not in terminal_net]
        if missing:
            add("ELEC_REQUIRED_PORT_UNCONNECTED",VerificationState.FAILED,"critical",f"{component.name} has unconnected required interfaces: {', '.join(missing)}.",(component_id,),category="electrical",interface_ids=tuple(missing),actual={"connectedInterfaces":sorted(name for owner,name in terminal_net if owner==component_id)},blocking=True)
        required_protocol_ports=_data(component).get("required_protocol_ports",{})
        for protocol,names in sorted(required_protocol_ports.items()):
            absent=[name for name in names if (component_id,name) not in terminal_net]
            if absent:
                add("ELEC_BUS_INCOMPLETE",VerificationState.FAILED,"critical",f"{component.name} has an incomplete {protocol} bus.",(component_id,),category="electrical",interface_ids=tuple(absent),expected={"requiredPorts":list(names)},actual={"missingPorts":absent},required_capability=f"complete_{protocol.lower()}_bus",blocking=True)

    # Load-control topology is proven by the actual load net, never by global
    # presence of a driver or protection component.
    driver_roles={"motor_driver","mosfet_driver","relay_module","switching_stage","pump switching"}
    load_roles={"small_dc_motor","small_dc_pump","fan","solenoid","bare_relay","relay","water delivery"}
    protection_roles={"flyback_diode","transient_suppression","inductive_protection"}
    for load in sorted(components.values(),key=lambda item:item.id):
        data=_data(load);roles={_family(load),str(data.get("load_class","")).lower(),*(str(value).lower() for value in data.get("functional_roles",()))}
        if not (roles & load_roles or data.get("requires_driver")): continue
        power_ports=[name for name,record in ports[load.id].items() if _role(record) in {"power","power_input"}]
        load_nets={terminal_net[(load.id,name)] for name in power_ports if (load.id,name) in terminal_net}
        drivers=[]
        for net_id in load_nets:
            for terminal in net_terminals.get(net_id,()):
                terminal_data=_data(terminal.component)
                terminal_roles={_family(terminal.component),*(str(value).lower() for value in terminal_data.get("functional_roles",()))}
                if terminal.component.id!=load.id and terminal_roles & driver_roles and _role(terminal.port)=="power_output": drivers.append(terminal.component)
        if data.get("requires_driver") and not drivers:
            add("ELEC_DRIVER_REQUIRED",VerificationState.FAILED,"critical",f"{load.name} is not powered through a connected driver output.",(load.id,),category="electrical",net_ids=tuple(sorted(load_nets)),expected={"driverInLoadPath":True},actual={"driverIds":[]},required_capability=str(data.get("required_driver_capability","switching_stage")),blocking=True)
        for driver in {item.id:item for item in drivers}.values():
            driver_ports=ports[driver.id]
            connected={name for name in driver_ports if (driver.id,name) in terminal_net}
            required_roles=set(_data(driver).get("required_switching_roles",("signal","power_input","power_output")))
            observed_roles={_role(record) for name,record in driver_ports.items() if name in connected}
            if _data(driver).get("switching_stage") and not required_roles<=observed_roles:
                add("ELEC_SWITCHING_PATH_INCOMPLETE",VerificationState.FAILED,"critical",f"{driver.name} is present in the load path but its control/supply/switching topology is incomplete.",(driver.id,load.id),category="electrical",net_ids=tuple(sorted(load_nets)),expected={"requiredRoles":sorted(required_roles)},actual={"connectedRoles":sorted(observed_roles)},required_capability="complete_switching_stage_topology",blocking=True)
            inductive=bool(data.get("inductive_load") or roles & {"small_dc_motor","small_dc_pump","solenoid","bare_relay","relay","water delivery"})
            integrated=bool(_data(driver).get("integrated_protection") or _data(driver).get("flyback_protection"))
            placed=any(
                (_family(item) in protection_roles or bool(_data(item).get("protection_component")))
                and load.id in _data(item).get("protects_load_ids",())
                and any((item.id,name) in terminal_net and terminal_net[(item.id,name)] in load_nets for name in ports[item.id])
                for item in components.values()
            )
            if inductive and not integrated and not placed:
                add("ELEC_INDUCTIVE_PROTECTION_REQUIRED",VerificationState.ESTIMATED,"warning",f"Inductive protection for {load.name} is not proven in its actual switched-load path.",(driver.id,load.id),category="electrical",net_ids=tuple(sorted(load_nets)),expected={"integratedOrPathConnectedProtection":True},actual={"integratedProtection":integrated,"pathConnectedProtection":placed},required_capability="inductive_suppression")

    # Fixed I2C addresses conflict only on the same materialized bus.
    by_bus: dict[str,list[tuple[EngineeringEntity,Any,bool]]]=defaultdict(list)
    for component_id,component in components.items():
        data=_data(component);address=data.get("i2c_address")
        if address is None: continue
        bus_ids={terminal_net[(component_id,name)] for name,port in ports[component_id].items() if str(port.get("protocol","")).lower()=="i2c" and (component_id,name) in terminal_net}
        for bus_id in bus_ids: by_bus[bus_id].append((component,address,bool(data.get("i2c_address_configurable"))))
    for bus_id,items in sorted(by_bus.items()):
        addresses: dict[str,list[tuple[EngineeringEntity,bool]]]=defaultdict(list)
        for component,address,configurable in items: addresses[str(address)].append((component,configurable))
        for address,duplicates in sorted(addresses.items()):
            if len(duplicates)>1 and not any(configurable for _,configurable in duplicates):
                add("ELEC_I2C_ADDRESS_CONFLICT",VerificationState.FAILED,"critical",f"I2C bus {bus_id} contains multiple fixed devices at address {address}.",tuple(item.id for item,_ in duplicates),category="electrical",net_ids=(bus_id,),actual={"address":address},required_capability="configurable_address_or_bus_multiplexer",blocking=True)

    # Path-specific shared reference declarations.
    for component in components.values():
        for peer_id in _data(component).get("requires_common_ground_with",()):
            left={net for (owner,port),net in terminal_net.items() if owner==component.id and _role(ports[owner][port])=="ground"}
            right={net for (owner,port),net in terminal_net.items() if owner==peer_id and _role(ports[owner][port])=="ground"}
            if not left & right and not _data(component).get("galvanically_isolated"):
                add("ELEC_COMMON_GROUND_REQUIRED",VerificationState.FAILED,"critical",f"{component.name} and {peer_id} do not share their required reference net.",(component.id,peer_id),category="electrical",net_ids=tuple(sorted(left|right)),required_capability="shared_reference_or_declared_isolation",blocking=True)

    _evaluate_requirements(graph,components,add)
    _evaluate_mechanics(graph,components,add)
    _evaluate_evidence(graph,components,add)


def _evaluate_requirements(graph: EngineeringGraph, components: dict[str,EngineeringEntity], add: AddFinding) -> None:
    def roles(component: EngineeringEntity) -> set[str]:
        data=_data(component)
        return {_family(component),str(data.get("role","")).lower(),*(str(value).lower() for value in data.get("functional_roles",()))}
    directed={(item.source_id,item.target_id) for item in graph.relationships.values() if item.type in {"signal","control","switched-power"}}
    for requirement in graph.find(kind=EntityKind.REQUIREMENT):
        data=_data(requirement);required_caps=set(map(str,data.get("required_capabilities",())))
        if required_caps:
            matches=[item.id for item in components.values() if required_caps<={*map(str,_data(item).get("capabilities",())),*map(str,_data(item).get("measures",())),*map(str,_data(item).get("measurements",()))}]
            if not matches:
                add("REQ_NOT_FUNCTIONALLY_SATISFIED",VerificationState.FAILED,"critical",f"{requirement.name} lacks represented capabilities {sorted(required_caps)}.",(requirement.id,),category="requirement",requirement_ids=(requirement.id,),expected={"capabilities":sorted(required_caps)},actual={"matchingComponentIds":matches},blocking=True)
        chain=[str(value).lower() for value in data.get("required_control_chain",())]
        if chain:
            candidates=[[item.id for item in components.values() if stage in roles(item)] for stage in chain]
            complete=all(candidates) and all(any((left,right) in directed for left in candidates[index] for right in candidates[index+1]) for index in range(len(candidates)-1))
            if not complete:
                add("REQ_CONTROL_CHAIN_INCOMPLETE",VerificationState.FAILED,"critical",f"{requirement.name} lacks the required role-ordered control path.",(requirement.id,),category="requirement",requirement_ids=(requirement.id,),expected={"controlChain":chain},actual={"candidateIds":candidates,"directedEdges":sorted(directed)},required_capability="connected_sense_control_drive_actuate_chain",blocking=True)


def _evaluate_mechanics(graph: EngineeringGraph, components: dict[str,EngineeringEntity], add: AddFinding) -> None:
    adjacency: dict[str,set[str]]=defaultdict(set)
    for relationship in graph.relationships.values():
        if relationship.type in {"mechanical","mate","drives"}:
            adjacency[relationship.source_id].add(relationship.target_id);adjacency[relationship.target_id].add(relationship.source_id)
    axis_actuators: dict[str,list[str]]=defaultdict(list);axis_targets: dict[str,list[str]]=defaultdict(list)
    for component in components.values():
        data=_data(component)
        for axis in data.get("controlled_axis_ids",()): axis_actuators[str(axis)].append(component.id)
        for axis in data.get("driven_axis_ids",()): axis_targets[str(axis)].append(component.id)
    for axis in sorted(set(axis_actuators)|set(axis_targets)):
        actuators=axis_actuators[axis];targets=axis_targets[axis];complete=False
        for actuator in actuators:
            seen={actuator};pending=deque([actuator])
            while pending:
                current=pending.popleft()
                for peer in adjacency[current]-seen: seen.add(peer);pending.append(peer)
            if any(target in seen for target in targets): complete=True
        if len(actuators)!=1 or len(targets)!=1 or not complete:
            add("MECH_AXIS_PATH_INCOMPLETE",VerificationState.FAILED,"critical",f"Controlled axis {axis} does not have one actuator and one mechanically reachable driven target.",tuple(sorted(set(actuators+targets))),category="mechanical",expected={"actuatorCount":1,"targetCount":1,"mechanicalPath":True},actual={"actuatorIds":actuators,"targetIds":targets,"mechanicalPath":complete},required_capability="complete_independent_axis_path",blocking=True)


def _evaluate_evidence(graph: EngineeringGraph, components: dict[str,EngineeringEntity], add: AddFinding) -> None:
    critical={"input_voltage_v","input_voltage_range_v","output_voltage_v","available_current_a","available_torque_nm","required_torque_nm"}
    for component in sorted(components.values(),key=lambda item:item.id):
        data=_data(component);facts=data.get("property_facts",{})
        for property_name,raw in sorted(facts.items()):
            records=raw if isinstance(raw,list) else [raw]
            active=[record for record in records if record.get("active",True)]
            values={(repr(record.get("value")),record.get("unit")) for record in active}
            evidence_ids=tuple(sorted({str(record.get("evidence_id",record.get("evidenceId",""))) for record in active if record.get("evidence_id",record.get("evidenceId"))}))
            if len(values)>1:
                blocking=property_name in critical and bool(data.get("property_required_for_decision",{}).get(property_name))
                add("EVIDENCE_PROPERTY_CONFLICT",VerificationState.FAILED if blocking else VerificationState.ESTIMATED,"critical" if blocking else "warning",f"{component.name} has conflicting active values for {property_name}.",(component.id,),category="evidence",evidence_ids=evidence_ids,expected={"singleActiveValue":True},actual={"property":property_name,"values":[{"value":value,"unit":unit} for value,unit in sorted(values)]},blocking=blocking)
            if active and all(str(record.get("status","")).lower()=="stale" for record in active) and property_name in critical:
                add("EVIDENCE_PROPERTY_STALE",VerificationState.STALE,"warning",f"Critical property {property_name} for {component.name} relies only on stale evidence.",(component.id,),category="evidence",evidence_ids=evidence_ids,actual={"property":property_name,"statuses":[record.get("status") for record in active]})
            if str(data.get("resolution_quality",""))=="EXACT" and active and all(str(record.get("status","")).lower() in {"conceptual","estimated",""} for record in active) and property_name in critical:
                add("EVIDENCE_PROPERTY_NOT_VERIFIED",VerificationState.ESTIMATED,"warning",f"Exact identity for {component.name} does not verify its {property_name} property.",(component.id,),category="evidence",evidence_ids=evidence_ids,actual={"property":property_name,"statuses":[record.get("status") for record in active]})
