from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any, Callable

from aura.engineering_graph.model import EntityKind
from aura.planner.schemas import ComponentSpec, ConnectionSpec, ProjectPlan

from .results import VerificationState


AddFinding = Callable[..., None]

CONTROLLERS = {"controller", "microcontroller_board"}
DRIVERS = {"motor_driver", "mosfet_driver", "relay_module", "pump switching"}
POWER_SOURCES = {"low_voltage_power_source", "system power", "battery"}
LOADS = {"small_dc_motor", "small_dc_pump", "fan", "servo", "solenoid", "bare_relay", "relay"}
INDUCTIVE = {"small_dc_motor", "small_dc_pump", "fan", "solenoid", "bare_relay", "relay"}
POWER_PORTS = {"power", "power+", "v+", "vcc", "vin", "motor-power", "load-in", "5v", "3v3"}
GROUND_PORTS = {"ground", "gnd", "logic-gnd", "power-ground"}
SIGNAL_PORTS = {"signal", "logic-in", "control", "pwm", "sda", "scl", "tx", "rx", "analog"}


@dataclass(frozen=True)
class PlanIndex:
    components: dict[str, ComponentSpec]
    incoming: dict[str, tuple[ConnectionSpec, ...]]
    outgoing: dict[str, tuple[ConnectionSpec, ...]]

    @classmethod
    def build(cls, plan: ProjectPlan) -> "PlanIndex":
        incoming: dict[str, list[ConnectionSpec]] = defaultdict(list)
        outgoing: dict[str, list[ConnectionSpec]] = defaultdict(list)
        for connection in sorted(plan.connections, key=lambda item: item.id):
            outgoing[connection.source_id].append(connection)
            incoming[connection.target_id].append(connection)
        return cls(
            {component.id: component for component in plan.components},
            {key: tuple(value) for key, value in incoming.items()},
            {key: tuple(value) for key, value in outgoing.items()},
        )

    def path(self, source: str, target: str, allowed: set[str]) -> bool:
        pending=deque([source]);seen={source}
        while pending:
            current=pending.popleft()
            for edge in self.outgoing.get(current, ()):
                if edge.connection_type not in allowed: continue
                if edge.target_id == target: return True
                if edge.target_id not in seen:
                    seen.add(edge.target_id);pending.append(edge.target_id)
        return False


def _family(component: ComponentSpec) -> str:
    return str(component.parameters.get("family", component.role)).strip().lower()


def _roles(component: ComponentSpec) -> set[str]:
    legacy={"component-esp32":"microcontroller_board","component-pump":"small_dc_pump",
            "component-driver":"mosfet_driver","component-power":"low_voltage_power_source"}.get(component.id)
    values={_family(component), component.role.lower(), *(str(value).lower() for value in component.parameters.get("functional_roles", ()))}
    if legacy: values.add(legacy)
    return values


def _is(component: ComponentSpec, families: set[str]) -> bool:
    return bool(_roles(component) & families)


def _port_kind(component: ComponentSpec, port: str) -> str:
    explicit=component.parameters.get("interface_roles", {})
    if port in explicit: return str(explicit[port]).lower()
    value=port.lower()
    if value in GROUND_PORTS or "gnd" in value or "ground" in value: return "ground"
    if value in SIGNAL_PORTS or any(token in value for token in ("gpio", "signal", "pwm", "logic", "sda", "scl", "uart", "analog")): return "signal"
    if value in POWER_PORTS or any(token in value for token in ("power", "vcc", "vin", "supply", "load")): return "power"
    return "unknown"


def evaluate_plausibility(plan: ProjectPlan, add: AddFinding) -> None:
    """Add deterministic architecture-level findings without mutating the plan."""
    index=PlanIndex.build(plan);components=index.components
    project=next(entity for entity in plan.entities if entity.kind is EntityKind.PROJECT)
    metadata=dict(project.metadata)
    strict=bool(metadata.get("semanticRequirements") or metadata.get("strict_verification"))

    controllers=[item for item in components.values() if _is(item, CONTROLLERS)]
    loads=[item for item in components.values() if _is(item, LOADS)]
    drivers=[item for item in components.values() if _is(item, DRIVERS)]
    sources=[item for item in components.values() if _is(item, POWER_SOURCES)]

    # A driver elsewhere in the graph must never excuse a direct GPIO-to-load edge.
    for edge in sorted(plan.connections, key=lambda item: item.id):
        source=components[edge.source_id];target=components[edge.target_id]
        if _is(source, CONTROLLERS) and _is(target, LOADS) and target.role != "servo":
            direct_power=edge.connection_type in {"power", "switched-power"} or _port_kind(target, edge.target_interface)=="power"
            if direct_power or edge.connection_type=="control":
                capability=("motor_driver" if target.role=="small_dc_motor" else
                            "relay_driver" if _family(target) in {"relay", "bare_relay"} else
                            "logic_compatible_switching_stage")
                add("ELEC_DRIVER_REQUIRED",VerificationState.FAILED,"critical",
                    f"{target.name} is connected directly to a controller output; the controller can signal it but cannot supply load power.",
                    (target.id,source.id),category="electrical",interface_ids=(edge.source_interface,edge.target_interface),
                    expected={"requiredCapability":capability,"path":"controller -> driver -> load"},
                    actual={"connectionId":edge.id,"path":[source.id,target.id],"connectionType":edge.connection_type},
                    required_capability=capability,repair_hint="Insert a compatible driver or switching stage between control and load power.",blocking=True)

    # Loads need a connected driver, not merely a driver-shaped component somewhere.
    for load in sorted(loads, key=lambda item: item.id):
        if load.role=="servo": continue
        driven_by=[edge for edge in index.incoming.get(load.id,())
                   if edge.connection_type in {"switched-power","power"} and _is(components[edge.source_id],DRIVERS)]
        if not driven_by and not any(edge.source_id in {c.id for c in controllers} for edge in index.incoming.get(load.id,())):
            add("ELEC_DRIVER_REQUIRED",VerificationState.FAILED,"critical",
                f"{load.name} has no connected load-capable driver stage.",(load.id,),category="electrical",
                expected={"path":"controller -> driver -> load"},actual={"incomingConnectionIds":[x.id for x in index.incoming.get(load.id,())]},
                required_capability="motor_driver" if load.role=="small_dc_motor" else "logic_compatible_switching_stage",
                repair_hint="Connect the load through a driver sized for its function.",blocking=True)

    # Per-component power and return paths. Legacy plans without semantic metadata warn instead of newly failing.
    for component in sorted(components.values(), key=lambda item: item.id):
        if _is(component, POWER_SOURCES): continue
        required_power=tuple(sorted(port for port in component.interfaces if _port_kind(component,port)=="power"))
        required_ground=tuple(sorted(port for port in component.interfaces if _port_kind(component,port)=="ground"))
        connected={edge.target_interface for edge in index.incoming.get(component.id,())}|{edge.source_interface for edge in index.outgoing.get(component.id,())}
        missing_power=tuple(port for port in required_power if port not in connected)
        missing_ground=tuple(port for port in required_ground if port not in connected)
        for ports,code,capability,label in (
            (missing_power,"ELEC_POWER_REQUIRED","valid_power_supply","power"),
            (missing_ground,"ELEC_COMMON_GROUND_REQUIRED","shared_reference_or_declared_isolation","ground/return"),
        ):
            if not ports: continue
            state=VerificationState.FAILED if strict else VerificationState.ESTIMATED
            add(code,state,"critical" if strict else "warning",f"{component.name} has an unconnected required {label} port: {', '.join(ports)}.",(component.id,),
                category="electrical",interface_ids=ports,expected={"connectedPorts":list(ports)},actual={"connectedPorts":sorted(connected)},
                required_capability=capability,repair_hint=f"Connect each required {label} port using the graph's electrical nets.",blocking=strict)

    # Signal must not be used as load power and power must not be used as a signal.
    for edge in sorted(plan.connections, key=lambda item: item.id):
        source=components[edge.source_id];target=components[edge.target_id]
        source_kind=_port_kind(source,edge.source_interface);target_kind=_port_kind(target,edge.target_interface)
        incompatible=(edge.connection_type in {"power","regulated-power","switched-power"} and target_kind=="signal") or (edge.connection_type in {"control","signal"} and target_kind=="power")
        if incompatible:
            add("ELEC_PORT_ROLE_INCOMPATIBLE",VerificationState.FAILED,"critical",f"Connection {edge.id} assigns {edge.connection_type} to a {target_kind}-only endpoint.",(source.id,target.id),
                category="electrical",interface_ids=(edge.source_interface,edge.target_interface),expected={"compatibleEndpointRole":edge.connection_type},actual={"sourceRole":source_kind,"targetRole":target_kind,"connectionId":edge.id},blocking=True)

    # Compare only explicit known voltages on actual power paths. Never default a missing value.
    for edge in sorted(plan.connections, key=lambda item: item.id):
        if edge.connection_type not in {"power","regulated-power","switched-power"}: continue
        source=components[edge.source_id];target=components[edge.target_id]
        source_v=source.parameters.get("output_voltage_v",source.parameters.get("voltage_v",source.parameters.get("load_voltage_v")))
        # A nominal ``supply_voltage_v`` is not necessarily a proven absolute
        # input limit (breakout modules commonly include regulation).  Only an
        # explicit input constraint or load operating voltage proves a mismatch.
        target_v=target.parameters.get("input_voltage_v",target.parameters.get("voltage_v"))
        if target_v is None and edge.target_interface.lower() in {"load-in","motor-power","power","power+","vin","vcc"}:
            target_v=target.parameters.get("load_voltage_v")
        allowed=target.parameters.get("input_voltage_range_v",target.parameters.get("supply_voltage_range_v"))
        if source_v is None or (target_v is None and allowed is None):
            add("ELEC_VOLTAGE_NOT_PROVEN",VerificationState.ESTIMATED,"warning",f"Voltage compatibility for {source.name} to {target.name} is not proven by available properties.",(source.id,target.id),
                category="electrical",expected={"knownSourceAndInputVoltage":True},actual={"sourceVoltageV":source_v,"targetVoltageV":target_v,"targetRangeV":allowed},repair_hint="Resolve voltage ratings from evidence before claiming compatibility.")
            continue
        compatible=(float(allowed[0])<=float(source_v)<=float(allowed[1])) if allowed is not None else float(source_v)==float(target_v)
        if not compatible:
            add("ELEC_VOLTAGE_INCOMPATIBLE",VerificationState.FAILED,"critical",f"{source.name} supplies {source_v} V but {target.name} requires {allowed if allowed is not None else target_v} V.",(source.id,target.id),
                category="electrical",expected={"inputVoltageV":target_v,"inputRangeV":allowed},actual={"supplyVoltageV":source_v,"connectionId":edge.id},required_capability="compatible_voltage_domain_or_converter",repair_hint="Use a compatible supply or a proven regulator/level conversion stage.",blocking=True)

    # Protection is contextual: integrated modules can satisfy it themselves.
    for load in sorted((item for item in loads if _is(item,INDUCTIVE)), key=lambda item:item.id):
        incoming=[edge for edge in index.incoming.get(load.id,()) if _is(components[edge.source_id],DRIVERS)]
        for edge in incoming:
            driver=components[edge.source_id]
            integrated=bool(driver.parameters.get("flyback_protection") or driver.parameters.get("integrated_protection") or driver.role in {"motor_driver","relay_module"})
            protected=any(
                protection.id != load.id
                and "inductive_protection" in _roles(protection)
                and any(
                    connection.source_id == driver.id
                    and connection.target_id == protection.id
                    and connection.source_interface == edge.source_interface
                    for connection in plan.connections
                )
                for protection in components.values()
            )
            if not integrated and not protected:
                state=VerificationState.FAILED if driver.parameters.get("protection_required") else VerificationState.ESTIMATED
                add("ELEC_INDUCTIVE_PROTECTION_REQUIRED",state,"critical" if state is VerificationState.FAILED else "warning",f"Protection for inductive load {load.name} is not proven at {driver.name}.",(driver.id,load.id),
                    category="electrical",expected={"inductiveSuppression":True},actual={"flybackProtection":driver.parameters.get("flyback_protection")},required_capability="inductive_suppression",repair_hint="Confirm integrated suppression or add a suitable protection stage.",blocking=state is VerificationState.FAILED)

    # Protocol checks only fire when endpoint protocol facts exist.
    for edge in sorted(plan.connections, key=lambda item:item.id):
        source=components[edge.source_id];target=components[edge.target_id]
        source_protocol=source.parameters.get("output_protocol",source.parameters.get("protocol"))
        accepted=target.parameters.get("accepted_protocols",target.parameters.get("protocol"))
        if not source_protocol or not accepted: continue
        accepted_set={accepted} if isinstance(accepted,str) else set(accepted)
        if source_protocol not in accepted_set:
            add("ELEC_PROTOCOL_INCOMPATIBLE",VerificationState.FAILED,"critical",f"{source.name} uses {source_protocol}, which {target.name} does not accept.",(source.id,target.id),category="electrical",
                interface_ids=(edge.source_interface,edge.target_interface),expected={"acceptedProtocols":sorted(accepted_set)},actual={"protocol":source_protocol},required_capability="compatible_communication_interface",blocking=True)

    # Distinct controlled axes, expected joint types, and actuator capability.
    requirements=[(entity.id,entity.name,dict(entity.metadata)) for entity in plan.entities if entity.kind is EntityKind.REQUIREMENT]
    axis_owners: dict[str,list[str]]=defaultdict(list)
    for component in components.values():
        for axis in component.parameters.get("controlled_axis_ids",()): axis_owners[str(axis)].append(component.id)
    for requirement_id,label,requirement in requirements:
        required_axes=int(requirement.get("required_axes",0) or 0)
        if required_axes:
            observed=sorted(axis for axis,owners in axis_owners.items() if len(owners)==1)
            if len(observed)<required_axes:
                add("MECH_CONTROLLED_AXIS_MISSING",VerificationState.FAILED,"critical",f"{label} requires {required_axes} independent controlled axes; only {len(observed)} are uniquely resolved.",(requirement_id,*sorted({owner for owners in axis_owners.values() for owner in owners})),category="mechanical",requirement_ids=(requirement_id,),
                    expected={"requiredAxes":required_axes},actual={"uniqueAxisIds":observed,"axisOwners":dict(sorted(axis_owners.items()))},required_capability="independent_controlled_axis",repair_hint="Provide distinct actuator, driven-axis, and control relationships for every required axis.",blocking=True)
        joint_types=requirement.get("required_joint_types",())
        if joint_types:
            observed=[str(item.parameters.get("joint_type","unresolved")) for item in components.values() if item.parameters.get("driven_axis_ids")]
            missing=[kind for kind in joint_types if kind not in observed]
            if missing:
                add("MECH_JOINT_TYPE_INCOMPATIBLE",VerificationState.FAILED,"critical",f"{label} requires joint types {list(joint_types)} but the driven mechanism provides {observed}.",(requirement_id,),category="mechanical",requirement_ids=(requirement_id,),expected={"jointTypes":list(joint_types)},actual={"jointTypes":observed},required_capability="compatible_mechanical_joint",blocking=True)

    for actuator in sorted((item for item in components.values() if "controlled_motion" in _roles(item)),key=lambda item:item.id):
        available=actuator.parameters.get("available_torque_nm")
        required=actuator.parameters.get("required_torque_nm")
        if available is not None and required is not None and float(available)<float(required):
            add("MECH_ACTUATOR_CAPABILITY_INSUFFICIENT",VerificationState.FAILED,"critical",f"{actuator.name} provides {available} N·m but the represented requirement is {required} N·m.",(actuator.id,),category="mechanical",expected={"minimumTorqueNm":required},actual={"availableTorqueNm":available},required_capability="actuator_with_sufficient_torque",blocking=True)
        elif available is None or required is None:
            add("MECH_ACTUATOR_CAPABILITY_NOT_PROVEN",VerificationState.ESTIMATED,"warning",f"Actuator capability for {actuator.name} is not proven because required or available torque is unknown.",(actuator.id,),category="mechanical",expected={"knownRequiredAndAvailableTorque":True},actual={"requiredTorqueNm":required,"availableTorqueNm":available})

    # Capability-based functional coverage and control chain hooks.
    capabilities={item.id:set(map(str,item.parameters.get("capabilities",())))|set(map(str,item.parameters.get("measures",())))|set(map(str,item.parameters.get("measurements",()))) for item in components.values()}
    for requirement_id,label,requirement in requirements:
        required_caps=set(map(str,requirement.get("required_capabilities",())))
        if required_caps:
            matching=[cid for cid,values in capabilities.items() if required_caps<=values]
            if not matching:
                add("REQ_NOT_FUNCTIONALLY_SATISFIED",VerificationState.FAILED,"critical",f"{label} requires capabilities {sorted(required_caps)} that no represented component provides.",(requirement_id,),category="requirement",requirement_ids=(requirement_id,),expected={"capabilities":sorted(required_caps)},actual={"componentCapabilities":{key:sorted(value) for key,value in sorted(capabilities.items())}},required_capability=sorted(required_caps)[0],blocking=True)
        chain=requirement.get("required_control_chain",())
        if chain:
            candidates=[[item.id for item in components.values() if role in _roles(item)] for role in chain]
            valid=all(candidates) and any(index.path(left,right,{"signal","control","switched-power"}) for left in candidates[0] for right in candidates[-1])
            if not valid:
                add("REQ_CONTROL_CHAIN_INCOMPLETE",VerificationState.FAILED,"critical",f"{label} does not have the required {' -> '.join(chain)} architecture path.",(requirement_id,),category="requirement",requirement_ids=(requirement_id,),expected={"controlChain":list(chain)},actual={"candidateIds":candidates},required_capability="connected_sense_control_actuate_chain",blocking=True)

    # Explicit identity is separate from family compatibility.
    identities=tuple(metadata.get("required_component_identities",()))
    represented=" ".join(f"{item.name} {item.parameters.get('planner_intent','')} {item.parameters.get('component_definition_id','')}" for item in components.values()).lower()
    for identity in sorted(map(str,identities)):
        if identity.lower() not in represented:
            add("COMPONENT_EXPLICIT_IDENTITY_LOST",VerificationState.FAILED if metadata.get("identity_mandatory",True) else VerificationState.ESTIMATED,"critical" if metadata.get("identity_mandatory",True) else "warning",f"Explicitly required hardware identity {identity} is not preserved by the represented components.",(project.id,),category="component",expected={"componentIdentity":identity},actual={"representedIdentities":represented},required_capability=f"exact_identity:{identity}",blocking=bool(metadata.get("identity_mandatory",True)))

    for requirement_id,label,requirement in requirements:
        if not requirement.get("critical"): continue
        required=set(requirement.get("required_roles",()))
        matches=[item for item in components.values() if required & _roles(item)]
        if matches and all(str(item.parameters.get("resolution_quality","UNRESOLVED"))=="UNRESOLVED" for item in matches):
            add("COMPONENT_CRITICAL_UNRESOLVED",VerificationState.ESTIMATED,"warning",f"{label} is represented only by unresolved component identities.",(requirement_id,*[item.id for item in matches]),category="component",requirement_ids=(requirement_id,),expected={"resolutionQuality":["EXACT","COMPATIBLE_GENERIC","CONCEPTUAL"]},actual={"resolutionQuality":"UNRESOLVED"},repair_hint="Resolve a compatible component family or exact part before claiming clean readiness.")
