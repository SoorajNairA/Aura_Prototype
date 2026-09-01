from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from aura.engineering_graph.model import EngineeringEntity, EntityKind, Relationship
from aura.engineering_graph.patches import GraphOperation, GraphPatch, PatchOperation
from aura.capabilities import CapabilityStatus, classify_objective
from aura.engineering_graph.interfaces import component_interfaces

from .schemas import (
    ComponentSpec, ConnectionSpec, PlannedEntity, PlannedRelationship, ProjectPlan, ProjectRequest, SubsystemSpec,
    RepresentationRequest, VerificationRequest, WorkspaceEventProposal,
)


@dataclass(frozen=True)
class PlannerRepairAttempt:
    """A single, graph-aware replan.  The candidate itself is never committed."""
    plan: ProjectPlan
    context: dict[str, Any]
    metadata: dict[str, Any]


class PlannerService:
    """Produce a deterministic, structured proposal without executing it."""

    def plan(self, request: ProjectRequest) -> ProjectPlan:
        request.validate()
        capability=classify_objective(request.objective)
        if capability["status"] in {CapabilityStatus.UNSUPPORTED.value,CapabilityStatus.NEEDS_CLARIFICATION.value}:
            raise ValueError(capability)
        # Normal production always compiles semantic intent.  It never selects a
        # complete project graph by matching a demo or benchmark phrase.
        return self._semantic_plan(request, capability["status"])

    def _semantic_plan(self,request:ProjectRequest,capability_status:str)->ProjectPlan:
        """Compile intent into families without replacing an unknown role with a look-alike.

        This is deliberately a small vocabulary of *roles*, not a menu of project
        templates.  A useful unknown is kept as a conceptual component, with the
        original Planner intent and resolution class carried into the graph.
        """
        # The structured planner may carry essential mechanism requirements in
        # its project name or requirements list.  Normalization must preserve
        # them all; looking only at the free-form objective silently dropped
        # "Tri-Axis" in live planner output.
        semantic_text=request.objective
        intent_text=" ".join((request.project_name,semantic_text,*request.requirements))
        text=semantic_text.lower();objective_text=request.objective.lower();planner_labels=" ".join(request.components).lower();project_id=self._id(request.objective,"project")
        semantic_requirements=[]
        def require(key,label,roles,*,axes=0,quantity=1):
            if not any(item["key"]==key for item in semantic_requirements):
                semantic_requirements.append({"key":key,"label":label,"roles":list(roles),"axes":axes,"quantity":quantity,"critical":True})
        require("controller","Control logic",("controller",))
        require("power","Low-voltage power",("power",))
        def has_term(value:str,term:str)->bool: return bool(re.search(rf"\b{re.escape(term)}\w*\b",value))
        # "Drawer opened" is a sensed state, not necessarily an instruction to
        # actuate the drawer.  Open/close only imply motion for a moving closure.
        non_indicator_motion=(has_term(text,"turn") and "turn on" not in text and "turns on" not in text)
        explicit_motion=bool(re.search(r"\b(?:move|moves|moving|rotate|rotates|rotating|lift|lifts|lifting|tilt|tilts|tilting|pan|pans|panning|balance|balances|balancing|conveyor|dispens\w*|arm|arms|drive|drives|driving|slid\w*)\b",text))
        needs_motion=explicit_motion or non_indicator_motion or any(has_term(planner_labels,word) for word in ("motor","servo","actuator")) or (any(has_term(text,word) for word in ("lid","flap","shade")) and any(has_term(text,word) for word in ("open","close")))
        mobile_drive=(any(has_term(text,word) or has_term(planner_labels,word) for word in ("wheel","vehicle","car","chassis"))
                      or bool(re.search(r"\bdrive(?:s|n|ing)?\b",text))
                      or bool(re.search(r"\bdrive(?:s|n|ing)?\b",planner_labels)))
        if any(word in text for word in ("plate","panel","platform","surface","conveyor")): require("moving-surface","Moving surface or platform",("moving_surface",))
        if any(word in text for word in ("ball","object","drawer","lid","camera")): require("moving-body","Required moving body",("moving_body",))
        if needs_motion and any(word in text for word in ("support","plate","panel","platform","conveyor","lid","drawer","camera")): require("support","Stationary support",("support",))
        if needs_motion: require("controlled-motion","Controlled actuation",("controlled_motion",))
        if mobile_drive:
            require("drive-output","Driven moving component",("drive_output",))
            require("support","Stationary support",("support",))
        if any(re.search(rf"\b{re.escape(word)}\b", text) or re.search(rf"\b{re.escape(word)}\b", planner_labels) for word in ("remote","wireless","receiver","bluetooth")):
            require("remote-control-input","Remote control input",("remote_control_input",))
        axis_count=self._requested_axis_count(intent_text)
        if not axis_count and (("pan" in text and "tilt" in text) or "balanc" in text): axis_count=2
        servo_count=self._named_component_count(f"{intent_text} {planner_labels}","servo")
        requested_counts={
            "fan":self._named_component_count(intent_text,"fan"),
            "pump":self._named_component_count(intent_text,"pump"),
            "temperature-sensor":self._named_component_count(intent_text,"temperature sensor"),
            "environmental-sensor":self._named_component_count(intent_text,"environmental sensor"),
            "distance-sensor":self._named_component_count(intent_text,"distance sensor"),
            "drive-wheel":self._named_component_count(intent_text,"wheel"),
        }
        requested_counts={family:count for family,count in requested_counts.items() if count}
        if axis_count>8 or servo_count>8 or any(count>8 for count in requested_counts.values()):
            raise ValueError({"status":"UNSUPPORTED","reasons":["This bounded planner supports at most eight repeated actuators, sensors, wheels, or controlled axes per project."]})
        if axis_count: require("controlled-axes",f"{axis_count}-axis controlled motion",("controlled_motion",),axes=axis_count)
        count_roles={"fan":"airflow_output","pump":"fluid_drive","temperature-sensor":"feedback_temperature","environmental-sensor":"feedback_environment","distance-sensor":"feedback_distance","drive-wheel":"drive_output"}
        for family,count in requested_counts.items():
            require(f"{family}-count",f"{count} independently represented {family.replace('-',' ')} instances",(count_roles[family],),quantity=count)
        if any(word in text for word in ("position","balanc")): require("position-feedback","Position/state feedback",("feedback_position",))
        if "temperature" in text or "thermal" in text or "warm" in text: require("temperature-feedback","Temperature feedback",("feedback_temperature",))
        if "drawer" in text and any(word in text for word in ("detect","opened","open state")): require("open-state-feedback","Open-state feedback",("feedback_open_state",))
        if "light" in text and any(word in text for word in ("turn on","turns on","output","illuminate")): require("light-output","Light output",("light_output",))
        directional_light=("light" in text and any(word in text for word in ("brightest","direction","track","point toward")))
        if directional_light: require("directional-light-feedback","Directional light feedback",("feedback_light",),quantity=4)
        elif any(word in text for word in ("bright","illumination","light sensor")): require("light-feedback","Light feedback",("feedback_light",))
        if "soil" in text or "moisture" in text: require("soil-feedback","Soil moisture feedback",("feedback_soil",))

        families={"controller":1,"power":1}
        def include(family:str,count:int=1)->None: families[family]=max(families.get(family,0),count)
        # Reusable objective-to-role rules.  None selects a complete named project.
        if any(word in text for word in ("warm","temperature","thermal")): include("temperature-sensor")
        if any(word in text for word in ("bright","illumination","light sensor","ldr","bh1750")):
            include("light-sensor",4 if directional_light else 1)
        if any(word in text for word in ("humidity","pressure","weather","environment")): include("environmental-sensor")
        if any(word in text for word in ("distance","range")): include("distance-sensor")
        if any(word in text for word in ("airflow","fan","ventilation")): include("fan");include("driver")
        if any(word in text for word in ("water","liquid","soil","pump","fluid","irrigation")): include("container");include("tube");include("pump");include("driver");include("enclosure")
        if "soil" in text or "moisture" in text: include("soil-sensor")
        if any(word in text for word in ("dispense","dispensing","food","portion")): include("container");include("servo");include("dispensing-mechanism");include("mounting-plate")
        if any(re.search(rf"\b{re.escape(word)}\b",text) for word in ("lid","flap","shade")): include("lid");include("hinge");include("servo");include("mounting-plate")
        if "drawer" in text: include("drawer");include("open-state-sensor")
        if "light" in text and any(word in text for word in ("turn on","turns on","output","illuminate")): include("indicator")
        if "lamp" in text: include("indicator")
        if "bare relay" in text:
            include("bare-relay");include("driver");include("flyback-diode")
        elif "relay" in text: include("relay-module")
        if "conveyor" in text or "belt" in text: include("conveyor");include("motor");include("driver");include("support")
        if mobile_drive:
            wheel_count=requested_counts.get("drive-wheel",2);include("chassis");include("drive-wheel",wheel_count);include("motor",wheel_count);include("motor-driver",wheel_count if "independent" in text else 1)
        if any(re.search(rf"\b{re.escape(word)}\b", text) or re.search(rf"\b{re.escape(word)}\b", planner_labels) for word in ("remote","wireless","receiver","bluetooth")): include("wireless-control")
        if any(word in text or word in planner_labels for word in ("enclosure","housing")): include("enclosure")
        if "camera" in text: include("camera-platform")
        if any(word in text for word in ("plate","platform")): include("controlled-platform");include("support")
        if "ball" in text or "object" in text: include("tracked-object")
        if any(word in text for word in ("position","balanc")): include("position-sensor")
        sliding_system="slid" in text and any(word in text for word in ("door","panel","drawer"))
        if "panel" in text and not sliding_system: include("panel");include("support")
        if axis_count: include("servo",axis_count);include("mechanism",axis_count)
        if servo_count:
            include("servo",servo_count)
            if needs_motion: include("mechanism",servo_count)
        motor_count=self._named_component_count(f"{intent_text} {planner_labels}","motor")
        if motor_count>8:
            raise ValueError({"status":"UNSUPPORTED","reasons":["This bounded planner supports at most eight repeated actuators per project."]})
        if motor_count: include("motor",motor_count)
        for family,count in requested_counts.items(): include(family,count)
        if sliding_system:
            include("sliding-panel");include("linear-mechanism");include("frame")
        if directional_light: include("resistor",4)

        specs={
          "controller":("ESP32 DevKit","microcontroller_board","electronics",{"logic_voltage_v":3.3,"gpio_max_current_ma":12,"functional_roles":["controller"],"resolution_quality":"EXACT","visual_template":"esp32_devkit"},(52,28,8)),
          "power":("Low-voltage power source","low_voltage_power_source","power",{"voltage_v":5.0,"available_current_a":max(3.0,families.get("servo",0)*0.8+families.get("motor",0)*0.6+0.5),"mains_exposed":False,"functional_roles":["power"],"resolution_quality":"COMPATIBLE_GENERIC"},(48,30,18)),
          "enclosure":("Protective enclosure","enclosure","structure",{"contains":["component-controller"],"waterproofing":"splash-resistant" if "tank" in text else "basic","functional_roles":["support"],"resolution_quality":"COMPATIBLE_GENERIC"},(120,90,55)),
          "temperature-sensor":("Temperature sensor","temperature_sensor","sensor",{"supply_voltage_v":3.3,"signal_voltage_v":3.3,"threshold_c":26,"functional_roles":["feedback_temperature"],"measures":["temperature"],"resolution_quality":"EXACT"},(22,16,6)),
          "light-sensor":("Ambient light sensor","light_sensor","sensor",{"supply_voltage_v":3.3,"signal_voltage_v":3.3,"functional_roles":["feedback_light"],"measures":["light"],"resolution_quality":"COMPATIBLE_GENERIC"},(22,16,6)),
          "soil-sensor":("Capacitive soil moisture sensor","soil_moisture_sensor","sensor",{"supply_voltage_v":3.3,"signal_voltage_v":3.3,"functional_roles":["feedback_soil"],"measures":["soil_moisture"],"resolution_quality":"EXACT","visual_template":"soil_probe"},(23,98,4)),
          "environmental-sensor":("Environmental sensor","environmental_sensor","sensor",{"supply_voltage_v":3.3,"measurements":["temperature","humidity","pressure"],"functional_roles":["feedback_environment"],"resolution_quality":"EXACT"},(24,18,6)),
          "distance-sensor":("Generic distance sensor","distance_sensor","sensor",{"supply_voltage_v":5.0,"functional_roles":["feedback_distance"],"measures":["distance"],"resolution_quality":"COMPATIBLE_GENERIC"},(45,22,18)),
          "position-sensor":("Conceptual position sensor","conceptual_sensor","sensor",{"supply_voltage_v":5.0,"signal_voltage_v":3.3,"functional_roles":["feedback_position"],"measures":["position"],"resolution_quality":"CONCEPTUAL","research_required":True},(35,24,12)),
          "open-state-sensor":("Conceptual open-state sensor","conceptual_sensor","sensor",{"supply_voltage_v":5.0,"signal_voltage_v":3.3,"functional_roles":["feedback_open_state"],"measures":["open_state"],"resolution_quality":"CONCEPTUAL"},(24,18,8)),
          "driver":("Logic-level N-channel MOSFET switch","mosfet_driver","electronics",{"logic_voltage_v":3.3,"logic_voltage_min_v":2.5,"logic_voltage_max_v":5.0,"load_voltage_v":5.0,"max_current_a":3.0,"flyback_protection":False,"protection_required":True,"functional_roles":["actuator_driver"],"resolution_quality":"EXACT","visual_template":"mosfet_switch"},(32,24,8)),
          "motor-driver":("Generic motor driver","motor_driver","electronics",{"logic_voltage_v":3.3,"logic_voltage_min_v":2.7,"logic_voltage_max_v":5.5,"load_voltage_v":5.0,"max_current_a":1.2,"flyback_protection":True,"functional_roles":["actuator_driver"],"resolution_quality":"COMPATIBLE_GENERIC"},(32,24,8)),
          "relay-module":("5 V relay module","relay_module","electronics",{"logic_voltage_v":3.3,"logic_voltage_min_v":3.3,"logic_voltage_max_v":5.0,"load_voltage_v":5.0,"max_current_a":5.0,"flyback_protection":True,"integrated_driver":True,"functional_roles":["actuator_driver","switching"],"resolution_quality":"EXACT","visual_template":"relay_module"},(50,26,18)),
          "bare-relay":("5 V bare relay","bare_relay","electronics",{"voltage_v":5.0,"current_a":0.08,"inductive_load":True,"flyback_protection":False,"protection_required":True,"integrated_driver":False,"functional_roles":["switching"],"resolution_quality":"EXACT","visual_template":"bare_relay"},(20,15,15)),
          "flyback-diode":("D1 Flyback Diode","flyback_diode","electronics",{"functional_roles":["inductive_protection"],"resolution_quality":"EXACT","visual_template":"axial_diode"},(10,3,3)),
          "resistor":("LDR divider resistor","resistor","electronics",{"functional_roles":["signal_conditioning"],"resistance_ohm":10000,"resolution_quality":"COMPATIBLE_GENERIC","visual_template":"axial_resistor"},(7,3,3)),
          "fan":("Desk fan","fan","actuator",{"voltage_v":5.0,"current_a":0.5,"inductive_load":True,"functional_roles":["airflow_output"],"resolution_quality":"EXACT"},(90,30,90)),
          "servo":("SG90 Servo","servo","actuator",{"voltage_v":5.0,"current_a":0.65,"inductive_load":False,"functional_roles":["controlled_motion"],"controlled_dof":1,"resolution_quality":"EXACT","visual_template":"sg90"},(23,12,29)),
          "motor":("Small DC motor","small_dc_motor","actuator",{"voltage_v":5.0,"current_a":0.6,"inductive_load":True,"functional_roles":["controlled_motion","conveyor_drive"],"controlled_dof":1,"resolution_quality":"COMPATIBLE_GENERIC"},(30,45,30)),
          "chassis":("Structural chassis","mounting_plate","structure",{"functional_roles":["support"],"resolution_quality":"CONCEPTUAL"},(180,110,18)),
          "drive-wheel":("Drive wheel","drive_wheel","mechanical",{"functional_roles":["moving_body","drive_output"],"resolution_quality":"CONCEPTUAL"},(52,52,18)),
          "wireless-control":("Conceptual wireless control module","wireless_module","electronics",{"functional_roles":["remote_control_input"],"resolution_quality":"CONCEPTUAL"},(32,20,8)),
          "container":("Container","container","mechanical",{"capacity_l":1.5,"wet_environment":any(word in text for word in ("water","liquid","soil","pump")),"functional_roles":["moving_body"],"resolution_quality":"COMPATIBLE_GENERIC"},(110,100,150)),
          "dispensing-mechanism":("Conceptual dispensing wheel","generic_mechanical_part","mechanical",{"functional_roles":["moving_surface"],"resolution_quality":"CONCEPTUAL"},(55,55,25)),
          "indicator":("Low-voltage light output","indicator","electronics",{"voltage_v":5.0,"functional_roles":["light_output"],"resolution_quality":"COMPATIBLE_GENERIC"},(18,12,8)),
          "lid":("Lightweight lid","lid","mechanical",{"mass_g":120,"functional_roles":["moving_body","moving_surface"],"resolution_quality":"COMPATIBLE_GENERIC"},(120,90,6)),
          "drawer":("Drawer body","generic_mechanical_part","mechanical",{"functional_roles":["moving_body"],"resolution_quality":"CONCEPTUAL"},(160,100,45)),
          "hinge":("Hinge","hinge","mechanical",{"functional_roles":["support"],"resolution_quality":"COMPATIBLE_GENERIC"},(80,10,10)),
          "mounting-plate":("Mounting plate","mounting_plate","structure",{"functional_roles":["support"],"resolution_quality":"COMPATIBLE_GENERIC"},(150,100,6)),
          "support":("Structural base","base","structure",{"functional_roles":["support"],"resolution_quality":"CONCEPTUAL"},(150,100,12)),
          "frame":("Structural frame","structural_frame","structure",{"functional_roles":["support"],"resolution_quality":"CONCEPTUAL"},(200,24,120)),
          "mechanism":("Driven link","articulated_link","mechanical",{"functional_roles":["moving_surface","moving_body"],"joint_type":"revolute","resolution_quality":"CONCEPTUAL"},(18,18,90)),
          "linear-mechanism":("Rotary-to-linear drive","linear_drive","mechanical",{"functional_roles":["motion_transmission"],"joint_type":"prismatic","resolution_quality":"CONCEPTUAL"},(100,36,18)),
          "sliding-panel":("Sliding panel","sliding_panel","mechanical",{"functional_roles":["moving_surface","moving_body"],"joint_type":"prismatic","resolution_quality":"CONCEPTUAL"},(160,12,90)),
          "controlled-platform":("Controlled platform","rotating_platform","mechanical",{"functional_roles":["moving_surface","moving_body"],"joint_type":"revolute","resolution_quality":"CONCEPTUAL"},(140,100,8)),
          "camera-platform":("Camera platform","camera_platform","mechanical",{"functional_roles":["moving_surface","moving_body"],"joint_type":"revolute","resolution_quality":"CONCEPTUAL"},(80,60,18)),
          "panel":("Tracked panel","panel","mechanical",{"functional_roles":["moving_surface","moving_body"],"joint_type":"revolute","surface_kind":"energy_collection" if "solar" in text else "generic_panel","resolution_quality":"CONCEPTUAL"},(180,120,8)),
          "tool-platform":("End platform","tool_platform","mechanical",{"functional_roles":["moving_surface","moving_body","tool_mount"],"joint_type":"revolute","resolution_quality":"CONCEPTUAL"},(58,44,10)),
          "conveyor":("Conveyor surface","generic_mechanical_part","mechanical",{"functional_roles":["moving_surface","moving_body"],"resolution_quality":"CONCEPTUAL"},(180,70,20)),
          "tracked-object":("Tracked object","tracked_object","mechanical",{"functional_roles":["moving_body"],"resolution_quality":"CONCEPTUAL"},(24,24,24)),
          "tube":("Fluid tube","tube","mechanical",{"resolution_quality":"CONCEPTUAL"},(10,150,10)),
          "pump":("Low-voltage pump","small_dc_pump","actuator",{"voltage_v":5.0,"current_a":0.8,"inductive_load":True,"functional_roles":["fluid_drive"],"resolution_quality":"COMPATIBLE_GENERIC"},(40,60,40)),
        }
        curated={"controller":"esp32-devkit-v1","temperature-sensor":"bme280-i2c-module","environmental-sensor":"bme280-breakout","distance-sensor":"vl53l0x-module","soil-sensor":"capacitive-soil-v1","fan":"dc-fan-5v","servo":"sg90-servo","driver":"logic-mosfet-module","motor-driver":"drv8833-module","relay-module":"relay-module-5v","bare-relay":"bare-relay-5v","flyback-diode":"1n4007-diode","resistor":"resistor-10k"}
        identity_overrides:dict[str,list[dict[str,Any]]]={}
        def identity(family:str,name:str,definition:str,visual:str,dimensions:tuple[float,float,float],quality:str="EXACT",parameters:dict[str,Any]|None=None):
            identity_overrides.setdefault(family,[]).append({"name":name,"definition":definition,"visual":visual,"dimensions":dimensions,"quality":quality,"parameters":parameters or {}})
        named_text=f"{intent_text} {planner_labels}".lower()
        if "arduino nano" in named_text: identity("controller","Arduino Nano","arduino-nano-v3","arduino_nano",(45,18,8),parameters={"logic_voltage_v":5.0,"gpio_max_current_ma":20})
        elif "arduino uno" in named_text or re.search(r"\barduino\b",named_text): identity("controller","Arduino Uno","arduino-uno-r4","arduino_uno",(69,53,15),"EXACT" if "uno" in named_text else "COMPATIBLE_GENERIC",{"logic_voltage_v":5.0,"gpio_max_current_ma":20})
        elif "esp8266" in named_text or "nodemcu" in named_text: identity("controller","ESP8266 NodeMCU","esp8266-nodemcu-v3","nodemcu",(31,58,13),parameters={"logic_voltage_v":3.3})
        elif "raspberry pi pico" in named_text or re.search(r"\bpico\b",named_text): identity("controller","Raspberry Pi Pico","raspberry-pi-pico","pico",(51,21,4),parameters={"logic_voltage_v":3.3})
        elif "esp32" in named_text: identity("controller","ESP32 DevKit","esp32-devkit-v1","esp32_devkit",(28,52,12),parameters={"logic_voltage_v":3.3})
        if "mg996" in named_text:
            for _ in range(families.get("servo",1)): identity("servo","MG996R Servo","mg996r-servo","mg996r",(41,20,43))
        elif "sg90" in named_text:
            for _ in range(families.get("servo",1)): identity("servo","SG90 Servo","sg90-servo","sg90",(23,12,29))
        if "hc-sr04" in named_text or "hc sr04" in named_text: identity("distance-sensor","HC-SR04 Ultrasonic Sensor","hc-sr04-class","hc_sr04",(45,20,15))
        if "bh1750" in named_text: identity("light-sensor","BH1750 Light Sensor","bh1750-module","bh1750",(18,13,4))
        if directional_light:
            identity_overrides["light-sensor"]=[]
            for index in range(4): identity("light-sensor",f"LDR Direction Sensor {index+1}","photoresistor-module","ldr",(32,14,7))
        raw_trace=[];raw_counts={}
        for raw in request.components:
            resolved=self._resolve_component_intent(raw,objective_text)
            raw_trace.append({"plannerIntent":raw,**resolved})
            family=resolved.get("normalizedFamily")
            if family: raw_counts[family]=raw_counts.get(family,0)+1
        for family,count in raw_counts.items(): include(family,count)
        # Choose a fallback actuator only after structured Planner intent has
        # been normalized. Otherwise a valid requested motor architecture also
        # inherits a phantom default servo (or vice versa).
        if needs_motion and not any(family in families for family in ("servo","motor")): include("servo")
        if raw_counts.get("mounting-plate") and "support" in families:
            families.pop("support")
        if (families.get("motor-driver") and not families.get("motor")
                and not any(families.get(family) for family in ("fan","pump"))):
            # A hobby servo already contains its motor-control electronics.  An
            # unconnected external motor driver is not retained as a phantom
            # component merely because the Planner used generic motor wording.
            families.pop("motor-driver")
            for trace in raw_trace:
                if trace.get("normalizedFamily")=="motor-driver":
                    trace.update({"normalizedFamily":None,"resolutionQuality":"UNRESOLVED","reason":"external motor driver is incompatible with the selected self-driven servo architecture"})
        if families.get("fan") or families.get("pump"):
            load_count=families.get("fan",0)+families.get("pump",0);include("driver",load_count);include("flyback-diode",load_count)
        if families.get("motor"):
            explicit_driver_count=self._named_component_count(intent_text,"motor driver")
            families["motor-driver"]=max(raw_counts.get("motor-driver",0),explicit_driver_count,families["motor"] if "independent" in text else 1)
        if families.get("motor") and not (families.get("fan") or families.get("pump")):
            families.pop("driver",None)
        moving_families={"mechanism","linear-mechanism","sliding-panel","controlled-platform","camera-platform","panel","tool-platform","conveyor","lid","dispensing-mechanism","drive-wheel"}
        actuator_families={"servo","motor","fan","pump"}
        support_families={"support","mounting-plate","chassis","frame","hinge","enclosure"}
        if needs_motion and not moving_families.intersection(families): include("mechanism")
        if not support_families.intersection(families): include("support")
        if axis_count >= 3 and not {"controlled-platform","camera-platform","panel","tool-platform"}.intersection(families): include("tool-platform")
        order=list(families);roles=tuple(dict.fromkeys(specs[family][2] for family in order));subsystems=tuple(SubsystemSpec(f"subsystem-{role}",role.title(),role,"Deterministic semantic subsystem.") for role in roles)
        components=[];component_by_family={}
        for family in order:
            name,kind,role,base_params,dims=specs[family];count=families[family]
            matching=[item for item in raw_trace if item.get("normalizedFamily")==family]
            for index in range(count):
                override=(identity_overrides.get(family) or [None]*count)[min(index,len(identity_overrides.get(family) or [None])-1)]
                component_name=override["name"] if override else name
                component_dims=override["dimensions"] if override else dims
                suffix="" if count==1 or (family in {"light-sensor","motor"} and index==0) else f"-{index+1}";cid=f"component-{family}{suffix}";params=dict(base_params)
                if family in curated:
                    params["component_definition_id"]=curated[family]
                    params["component_definition_version"]="catalogue-v1"
                if override:
                    params.update(override["parameters"]);params.update({"component_definition_id":override["definition"],"component_definition_version":"catalogue-v1","resolution_quality":override["quality"],"visual_template":override["visual"],"requested_identity":override["name"]})
                if index<len(matching):
                    params["planner_intent"]=matching[index]["plannerIntent"];params["resolution_quality"]=matching[index]["resolutionQuality"];params["resolution_reason"]=matching[index]["reason"]
                    if matching[index]["resolutionQuality"] != "EXACT":
                        params.pop("component_definition_id",None)
                        params.pop("component_definition_version",None)
                else: params["planner_intent"]=name
                physical=component_interfaces(kind,tuple(float(value) for value in component_dims),params);interface_names=tuple(dict.fromkeys(item.name for item in physical))
                components.append(ComponentSpec(cid,component_name,kind,f"subsystem-{role}",f"{component_name} for the requested low-voltage system.",params,interface_names,{key:{"value":value,"unit":"mm"} for key,value in zip(("width","length","height"),component_dims)},assumption_refs=(f"assumption-{family}",)))
                component_by_family.setdefault(family,[]).append(cid)
        # Explicit axes remain graph semantics.  An actuator can advertise one
        # or more controlled axes, and a distinct driven body records which
        # axis it realizes.  This supports servo, motor, and future actuator
        # families without a project-name or robotic-arm branch.
        if axis_count:
            next_axis=1
            for index,component in enumerate(components):
                if "controlled_motion" not in component.parameters.get("functional_roles",()): continue
                capacity=max(int(component.parameters.get("controlled_dof",0) or 0),1)
                assigned=[]
                while len(assigned)<capacity and next_axis<=axis_count:
                    assigned.append(f"axis-{next_axis}");next_axis+=1
                if assigned:
                    parameters=dict(component.parameters);parameters["controlled_axis_ids"]=assigned;parameters["joint_type"]="revolute"
                    direction_cycle=((0,0,1),(1,0,0),(0,1,0),(1,0,0))
                    parameters["output_axis"]=list(direction_cycle[(next_axis-len(assigned)-1)%len(direction_cycle)])
                    components[index]=replace(component,parameters=parameters)
            index_by_id={component.id:index for index,component in enumerate(components)}
            transmissions=component_by_family.get("mechanism",[])+component_by_family.get("linear-mechanism",[])
            for axis_index,component_id in enumerate(transmissions[:axis_count],1):
                index=index_by_id[component_id];component=components[index];parameters=dict(component.parameters)
                parameters["driven_axis_ids"]=[f"axis-{axis_index}"]
                components[index]=replace(component,parameters=parameters)
        ids={c.id for c in components};connections=[];by_component={c.id:c for c in components};controller_signal=0;mechanical_interfaces_used:set[str]=set()
        def connect(a,b,kind):
            nonlocal controller_signal
            endpoint={"power":("power","power"),"ground":("ground","ground"),"control":("signal","signal"),"signal":("signal","signal"),"switched-power":("signal","power"),"regulated-power":("power","power")}.get(kind)
            if kind in {"control","signal"}:
                if a in by_component and by_component[a].role in {"microcontroller_board","controller"}:
                    controller_signal+=1;endpoint=(f"signal-{min(controller_signal,8)}","signal")
                elif b in by_component and by_component[b].role in {"microcontroller_board","controller"}:
                    controller_signal+=1;endpoint=("signal",f"signal-{min(controller_signal,8)}")
                if b in by_component and by_component[b].role=="resistor": endpoint=("signal","terminal-a")
            if kind=="mechanical" and a in by_component and b in by_component:
                left=component_interfaces(by_component[a].role,tuple(float(x.get("value",1)) for x in by_component[a].dimensions.values()),by_component[a].parameters);right=component_interfaces(by_component[b].role,tuple(float(x.get("value",1)) for x in by_component[b].dimensions.values()),by_component[b].parameters)
                # A downstream actuator body is fixed to the prior link.  Its
                # rotating output remains available for the next driven link.
                preferred=((x,y) for x in left for y in right if
                    (by_component[a].role in {"articulated_link","generic_mechanical_part","linear_drive"} and by_component[b].role=="servo" and x.name=="end-face" and y.name=="body-mount")
                    or (by_component[a].role in {"mounting_plate","base","structural_frame"} and by_component[b].role=="small_dc_motor" and x.name.startswith("drive-mount-") and y.name=="body-mount")
                    or (by_component[a].role in {"panel","rotating_platform","camera_platform","tool_platform"} and "sensor" in by_component[b].role and x.name=="sensor-mount" and y.name=="body-mount"))
                compatible=((x,y) for x in left for y in right if y.kind in x.compatible)
                pair=next((pair for pair in (*preferred,*compatible) if f"{a}:{pair[0].name}" not in mechanical_interfaces_used and f"{b}:{pair[1].name}" not in mechanical_interfaces_used),None)
                if pair:
                    endpoint=(pair[0].name,pair[1].name);mechanical_interfaces_used.update((f"{a}:{endpoint[0]}",f"{b}:{endpoint[1]}"))
            if kind=="switched-power" and a in by_component and by_component[a].role in {"mosfet_driver","motor_driver","relay_module","bare_relay"}:
                endpoint=("load-output","cathode" if by_component[b].role=="flyback_diode" else "power")
            if kind=="ground" and a in by_component and by_component[a].role=="flyback_diode": endpoint=("anode","ground")
            if kind=="ground" and a in by_component and by_component[a].role=="resistor": endpoint=("terminal-b","ground")
            if endpoint is None and kind!="mechanical" and a in by_component and b in by_component:
                left=component_interfaces(by_component[a].role,tuple(float(x.get("value",1)) for x in by_component[a].dimensions.values()),by_component[a].parameters);right=component_interfaces(by_component[b].role,tuple(float(x.get("value",1)) for x in by_component[b].dimensions.values()),by_component[b].parameters)
                endpoint=next(((x.name,y.name) for x in left for y in right if y.kind in x.compatible),("mechanical","mechanical"))
            if a in ids and b in ids and endpoint: connections.append(ConnectionSpec(f"connection-{a[10:]}-{b[10:]}-{kind}",a,b,endpoint[0],endpoint[1],kind,f"{kind.title()} connection."))
        controller=component_by_family["controller"][0];power=component_by_family["power"][0]
        sensors=[c.id for c in components if any(str(role).startswith("feedback_") for role in c.parameters.get("functional_roles",[]))]
        for sensor in sensors: connect(sensor,controller,"signal")
        for index,resistor in enumerate(component_by_family.get("resistor",[])):
            if sensors:
                connect(sensors[min(index,len(sensors)-1)],resistor,"signal");connect(resistor,power,"ground")
        for remote in component_by_family.get("wireless-control",[]): connect(remote,controller,"signal")
        drivers=component_by_family.get("driver",[])+component_by_family.get("motor-driver",[])+component_by_family.get("relay-module",[]);actuators=[c.id for c in components if "controlled_motion" in c.parameters.get("functional_roles",[]) or c.role in {"fan","small_dc_pump","bare_relay"}]
        driven_index=0
        for actuator in actuators:
            externally_driven=drivers and by_component[actuator].role!="servo"
            driver=drivers[min(driven_index,len(drivers)-1)] if externally_driven else controller
            connect(driver,actuator,"switched-power" if externally_driven else "control")
            if externally_driven: driven_index+=1
        relay_targets=set()
        relay_switches=component_by_family.get("relay-module",[])+component_by_family.get("bare-relay",[])
        if relay_switches and component_by_family.get("indicator"):
            for index,indicator in enumerate(component_by_family["indicator"]):
                relay=relay_switches[min(index,len(relay_switches)-1)]
                connect(relay,indicator,"switched-power");relay_targets.add(indicator)
        for indicator in component_by_family.get("indicator",[]):
            if indicator not in relay_targets: connect(controller,indicator,"control")
        for driver in drivers: connect(controller,driver,"control")
        driver_controlled={actuator for actuator in actuators if drivers and by_component[actuator].role!="servo"}|relay_targets
        for target in sorted(item.id for item in components if item.id!=power and {"power","ground"}.issubset(item.interfaces)):
            if target not in driver_controlled: connect(power,target,"power")
            connect(power,target,"ground")
        for index,diode in enumerate(component_by_family.get("flyback-diode",[])):
            if drivers:
                connect(drivers[min(index,len(drivers)-1)],diode,"switched-power");connect(diode,power,"ground")
        servos=component_by_family.get("servo",[]);mechanisms=component_by_family.get("mechanism",[]);platforms=component_by_family.get("controlled-platform",[])+component_by_family.get("camera-platform",[])+component_by_family.get("panel",[])+component_by_family.get("tool-platform",[])+component_by_family.get("conveyor",[])+component_by_family.get("lid",[])+component_by_family.get("dispensing-mechanism",[])
        mounts=component_by_family.get("mounting-plate",[])+component_by_family.get("support",[])+component_by_family.get("frame",[])
        if servos and mounts: connect(mounts[0],servos[0],"mechanical")
        linear_drives=component_by_family.get("linear-mechanism",[]);sliding_panels=component_by_family.get("sliding-panel",[])
        if servos and linear_drives and sliding_panels:
            connect(servos[0],linear_drives[0],"mechanical")
            connect(linear_drives[0],sliding_panels[0],"mechanical")
        elif len(servos)>1 and mechanisms:
            for index,servo in enumerate(servos):
                stage=mechanisms[min(index,len(mechanisms)-1)];connect(servo,stage,"mechanical")
                if index+1<len(servos): connect(stage,servos[index+1],"mechanical")
            if platforms: connect(mechanisms[min(len(servos)-1,len(mechanisms)-1)],platforms[0],"mechanical")
        elif servos and mechanisms:
            connect(servos[0],mechanisms[0],"mechanical")
            if platforms: connect(mechanisms[0],platforms[0],"mechanical")
        elif servos and platforms: connect(servos[0],platforms[0],"mechanical")
        if platforms and sensors: connect(platforms[0],sensors[0],"mechanical")
        if mounts:
            connect(mounts[0],controller,"mechanical")
            connect(mounts[0],power,"mechanical")
        if component_by_family.get("hinge",[]) and component_by_family.get("lid",[]): connect(component_by_family["hinge"][0],component_by_family["lid"][0],"mechanical")
        if component_by_family.get("motor",[]) and component_by_family.get("conveyor",[]):
            connect(component_by_family["motor"][0],component_by_family["conveyor"][0],"mechanical")
            if component_by_family.get("support",[]): connect(component_by_family["support"][0],component_by_family["motor"][0],"mechanical")
        motors=component_by_family.get("motor",[]);wheels=component_by_family.get("drive-wheel",[]);chassis=component_by_family.get("chassis",[])
        if motors and platforms:
            connect(motors[0],platforms[0],"mechanical")
            if mounts: connect(mounts[0],motors[0],"mechanical")
        if motors and chassis:
            for index,motor in enumerate(motors): connect(chassis[min(index,len(chassis)-1)],motor,"mechanical")
        if motors and wheels:
            for index,motor in enumerate(motors): connect(motor,wheels[min(index,len(wheels)-1)],"mechanical")
        entities=[PlannedEntity(project_id,EntityKind.PROJECT,request.project_name,metadata=(("objective",request.objective),("capability_status",capability_status),("plannerIntentTrace",raw_trace),("semanticRequirements",semantic_requirements)))]
        entities += [PlannedEntity(s.id,EntityKind.SUBSYSTEM,s.name,project_id,(("role",s.role),)) for s in subsystems]
        entities += [PlannedEntity(f"requirement-{item['key']}",EntityKind.REQUIREMENT,item["label"],project_id,tuple({"semantic_requirement":item["key"],"required_roles":item["roles"],"required_axes":item["axes"],"required_quantity":item["quantity"],"critical":item["critical"]}.items())) for item in semantic_requirements]
        entities += [PlannedEntity(f"requirement-declared-{i}",EntityKind.REQUIREMENT,value,project_id,(("declared_requirement",True),)) for i,value in enumerate(request.requirements,1)]
        entities += [PlannedEntity(c.id,EntityKind.COMPONENT,c.name,c.subsystem_id,tuple({"role":c.role,"family":c.role,"parameters":c.parameters,"interfaces":list(c.interfaces),"dimensions":c.dimensions,"representation_status":"placeholder","assumption_refs":list(c.assumption_refs)}.items())) for c in components]
        entities += [PlannedEntity(f"assumption-{i}",EntityKind.ASSUMPTION,value,project_id) for i,value in enumerate(("Use 5 V isolated low-voltage power","Exact mechanical fit remains conceptual"),1)]
        entities += [PlannedEntity(c.id,EntityKind.CONNECTION,c.description,project_id,tuple({"source_id":c.source_id,"target_id":c.target_id,"source_interface":c.source_interface,"target_interface":c.target_interface,"connection_type":c.connection_type}.items())) for c in connections]
        operations=[GraphOperation(PatchOperation.ADD_ENTITY,entity=EngineeringEntity(e.id,e.kind,e.name,e.parent_id,dict(e.metadata))) for e in entities];relationships=tuple(PlannedRelationship(c.id+"-edge",c.source_id,c.target_id,c.connection_type) for c in connections)
        operations += [GraphOperation(PatchOperation.ADD_RELATIONSHIP,relationship=Relationship(r.id,r.source_id,r.target_id,r.type,{"connection_id":r.id.removesuffix("-edge")})) for r in relationships]
        patch=GraphPatch(self._id(request.objective,"initial-patch"),tuple(operations),f"Create {request.project_name}")
        plan=ProjectPlan(request,tuple(entities),relationships,patch,(RepresentationRequest(project_id,"system_diagram"),),VerificationRequest(patch.id,("structure","electrical","physical","safety","objective_coverage")),(WorkspaceEventProposal("project.started",project_id),),subsystems,tuple(components),tuple(connections),("Use low-voltage DC only","Unsupported certification remains explicit"))
        plan.validate();return plan

    @staticmethod
    def _requested_axis_count(text: str) -> int:
        """Extract an explicitly requested number of independently controlled axes."""
        words={"one":1,"single":1,"two":2,"dual":2,"three":3,"tri":3,"four":4,"quad":4,"five":5,"six":6,"seven":7,"eight":8}
        number=r"(?:\d+|one|single|two|dual|three|tri|four|quad|five|six|seven|eight)"
        def value(token: str) -> int: return int(token) if token.isdigit() else words[token]
        counts=[]
        for match in re.finditer(rf"\b(?P<count>{number})\s*[- ]?axis(?:es)?\b",text.lower()): counts.append(value(match.group("count")))
        for match in re.finditer(rf"\b(?P<count>{number})\s+(?:independent\s+)?degrees?\s+of\s+freedom\b",text.lower()): counts.append(value(match.group("count")))
        for match in re.finditer(rf"\b(?P<count>{number})\s*[- ]?dof\b",text.lower()): counts.append(value(match.group("count")))
        for match in re.finditer(rf"\b(?P<count>{number})\s+(?:independent\s+)?(?:(?:servo|motor|actuator)\s+)?(?:control\s+)?(?:channels|joints)\b",text.lower()): counts.append(value(match.group("count")))
        return max(counts,default=0)

    @staticmethod
    def _named_component_count(text: str, family: str) -> int:
        words={"one":1,"single":1,"two":2,"dual":2,"three":3,"tri":3,"four":4,"quad":4,"five":5,"six":6,"seven":7,"eight":8}
        match=re.search(rf"\b(?P<count>\d+|{'|'.join(words)})(?:\s+|-)\s*(?:(?:independently\s+)?(?:controlled|driven)\s+)?(?:(?:hobby|small|dc|raw)\s+)?{re.escape(family)}s?\b",text.lower())
        if not match: return 0
        token=match.group("count");return int(token) if token.isdigit() else words[token]

    def repair_context(self, plan: ProjectPlan, verification: Any) -> tuple[dict[str, Any], list[str]]:
        """Extract the bounded, provider-neutral context for one graph repair."""
        critical=[finding for finding in verification.findings if finding.severity=="critical" and finding.state.value=="failed"]
        component_by_id={component.id:component for component in plan.components}
        implicated={entity_id for finding in critical for entity_id in finding.entity_ids if entity_id in component_by_id}
        relevant=[]
        for component_id in sorted(implicated):
            component=component_by_id[component_id]
            dimensions=tuple(float(value.get("value",1)) for value in component.dimensions.values())
            relevant.append({"id":component.id,"family":component.role,"interfaces":[{"name":item.name,"type":item.kind,"compatible":list(item.compatible)} for item in component_interfaces(component.role,dimensions)]})
        checks={finding.check for finding in critical}
        additions=[]
        roles={role for component in plan.components for role in component.parameters.get("functional_roles",())}
        has_motor=any(component.role=="small_dc_motor" for component in plan.components)
        has_servo=any(component.role=="servo" for component in plan.components)
        has_inductive=any(component.role in {"small_dc_motor","small_dc_pump","fan"} for component in plan.components)
        has_driver=any(component.role in {"mosfet_driver","motor_driver","relay_module"} for component in plan.components)
        if has_inductive and not has_driver and ({"direct-pump-gpio","missing-driver","ELEC_DRIVER_REQUIRED","ELEC_411","connection-endpoint"}&checks): additions.append("compatible motor driver")
        if has_inductive and "ELEC_INDUCTIVE_PROTECTION_REQUIRED" in checks: additions.append("flyback diode")
        if has_motor and ({"MECH_301","connection-endpoint"}&checks): additions.extend(("structural chassis","drive wheel"))
        if has_servo and ({"MECH_301","MECH_302","MECH_310","MECH_311","MECH_312","connection-endpoint"}&checks): additions.extend(("structural support","driven mechanism"))
        if {"power-connection","common-ground","ELEC_411"}&checks: additions.append("low-voltage power supply")
        if "remote_control_input" in roles: additions.append("wireless control module")
        additions=list(dict.fromkeys(additions))
        context={
            "originalObjective":plan.request.objective,
            "normalizedGraph":{"components":[{"id":component.id,"family":component.role,"interfaces":list(component.interfaces),"roles":component.parameters.get("functional_roles",[])} for component in plan.components],"connections":[{"id":connection.id,"type":connection.connection_type,"source":connection.source_id,"sourceInterface":connection.source_interface,"target":connection.target_id,"targetInterface":connection.target_interface} for connection in plan.connections]},
            "criticalFindings":[{"code":finding.check,"message":finding.message,"entityIds":list(finding.entity_ids),"expected":finding.expected,"actual":finding.actual} for finding in critical],
            "relevantComponentInterfaces":relevant,
            "repairRules":["Use only declared compatible interfaces.","Preserve every structured required axis with a distinct actuator, driven component, joint, upstream support, and control relationship.","Place a driver between controller GPIO and a high-current inductive actuator.","Attach actuator bodies to support and rotating outputs to driven components.","Recompile and reverify exactly once."],
        }
        return context, additions

    def repair(self, plan: ProjectPlan, verification: Any) -> PlannerRepairAttempt:
        """Perform one deterministic, interface-aware replan after graph rejection.

        This deliberately recompiles a new candidate through ``plan`` rather
        than mutating an invalid graph.  It uses only families implicated by
        the rejected connections/findings, so it is bounded and auditable.
        """
        context, additions=self.repair_context(plan,verification)
        repaired_request=ProjectRequest(plan.request.project_name,plan.request.objective,plan.request.requirements,
            components=tuple(dict.fromkeys((*plan.request.components,*additions))),assumptions=tuple(dict.fromkeys((*plan.request.assumptions,"One bounded semantic repair was applied"))),representation=plan.request.representation)
        repaired=self.plan(repaired_request)
        return PlannerRepairAttempt(repaired,context,{"repairAttempted":True,"repairProvider":"deterministic_semantic_repair","repairAdditions":additions,"criticalFindingCountBefore":len(context["criticalFindings"])})

    @staticmethod
    def _resolve_component_intent(intent:str,objective:str)->dict[str,str|None]:
        """Resolve a Planner label only when its functional language is retained."""
        label=re.sub(r"[_-]+"," ",intent.lower()).strip()
        exact_named=(
            (("arduino nano","arduino uno","esp32 devkit","esp8266","nodemcu","raspberry pi pico"),"controller"),
            (("sg90","mg996r"),"servo"),(("hc sr04","hc-sr04"),"distance-sensor"),
            (("bh1750","ldr","photoresistor"),"light-sensor"),(("soil moisture sensor",),"soil-sensor"),
            (("l298n","tb6612","uln2003"),"motor-driver"),(("relay module",),"relay-module"),
            (("flyback diode",),"flyback-diode"),
        )
        for names,family in exact_named:
            if any(name in label for name in names):
                return {"normalizedFamily":family,"resolutionQuality":"EXACT","reason":"explicit named hardware identity is preserved"}
        if ("tank" in label or "level" in label) and any(word in objective for word in ("position","balanc","track")) and not any(word in objective for word in ("tank","level")):
            return {"normalizedFamily":None,"resolutionQuality":"UNRESOLVED","reason":"level sensing does not preserve the objective's position-feedback intent"}
        rules=(
            (("arduino",),"controller","COMPATIBLE_GENERIC"),(("controller","esp32","microcontroller"),"controller","EXACT"),(("power","battery","supply"),"power","EXACT"),
            (("servo",),"servo","EXACT"),(("temperature",),"temperature-sensor","EXACT"),(("ambient light","light sensor"),"light-sensor","COMPATIBLE_GENERIC"),
            (("humidity","pressure","environmental"),"environmental-sensor","EXACT"),(("distance","range","level sensor"),"distance-sensor","COMPATIBLE_GENERIC"),
            (("position","tracking","camera-based"),"position-sensor","CONCEPTUAL"),(("drawer","open-state","reed"),"open-state-sensor","CONCEPTUAL"),
            (("conveyor","belt"),"conveyor","CONCEPTUAL"),(("motor driver","h-bridge"),"motor-driver","COMPATIBLE_GENERIC"),(("motor",),"motor","COMPATIBLE_GENERIC"),(("fan",),"fan","EXACT"),(("pump",),"pump","COMPATIBLE_GENERIC"),
            (("driver","mosfet","relay"),"driver","EXACT"),(("wheel",),"drive-wheel","CONCEPTUAL"),(("chassis",),"chassis","CONCEPTUAL"),(("remote","wireless","receiver","bluetooth"),"wireless-control","CONCEPTUAL"),(("container","reservoir"),"container","COMPATIBLE_GENERIC"),(("tube","tubing"),"tube","COMPATIBLE_GENERIC"),
            (("enclosure","housing"),"enclosure","COMPATIBLE_GENERIC"),(("lid",),"lid","COMPATIBLE_GENERIC"),(("hinge",),"hinge","COMPATIBLE_GENERIC"),
            (("mounting plate","mount plate","bracket","structural support"),"mounting-plate","COMPATIBLE_GENERIC"),(("camera platform","camera mount"),"camera-platform","CONCEPTUAL"),(("plate","platform"),"controlled-platform","CONCEPTUAL"),
            (("ball","object"),"tracked-object","CONCEPTUAL"),(("camera",),"camera-platform","CONCEPTUAL"),(("arm","link","mechanism","shaft"),"mechanism","CONCEPTUAL"),
        )
        for terms,family,quality in rules:
            if any(term in label for term in terms): return {"normalizedFamily":family,"resolutionQuality":quality,"reason":"functional terms match the retained family semantics"}
        return {"normalizedFamily":None,"resolutionQuality":"UNRESOLVED","reason":"no safe family preserves this Planner intent"}

    def irrigation_benchmark_plan(self, request: ProjectRequest) -> ProjectPlan:
        """Legacy fixture retained only for test/demo reset tooling, never `plan`."""
        project_id = "project-auto-irrigation-v1"
        subsystems = (
            SubsystemSpec("subsystem-controller", "Controller subsystem", "sense and control", "Reads moisture and controls water delivery."),
            SubsystemSpec("subsystem-water", "Water subsystem", "store and move water", "Routes water from reservoir to plant."),
            SubsystemSpec("subsystem-power", "Power subsystem", "low-voltage supply", "Supplies regulated low-voltage power."),
            SubsystemSpec("subsystem-structure", "Physical structure", "protect electronics", "Separates electronics from water."),
        )
        components = (
            ComponentSpec("component-esp32", "ESP32", "controller", "subsystem-controller", "Microcontroller that reads the sensor and commands the driver.", {"logic_voltage_v": 3.3, "gpio_max_current_ma": 12}, ("3v3", "gnd", "gpio-sensor", "gpio-pump"), {"width": {"value": 28, "unit": "mm"}, "length": {"value": 52, "unit": "mm"}}, evidence_refs=("evidence-esp32-datasheet",)),
            ComponentSpec("component-sensor", "Soil-moisture sensor", "soil sensing", "subsystem-controller", "Low-voltage sensor used to estimate soil moisture.", {"supply_voltage_v": 3.3, "signal_voltage_v": 3.3}, ("vcc", "gnd", "signal"), {"width": {"value": 20, "unit": "mm"}, "length": {"value": 60, "unit": "mm"}}, assumption_refs=("assumption-capacitive-sensor",)),
            ComponentSpec("component-driver", "Relay driver", "pump switching", "subsystem-controller", "Separates the ESP32 GPIO from the pump load.", {"logic_voltage_v": 3.3, "load_voltage_v": 5.0, "max_current_a": 2.0, "driver_type": "relay", "flyback_protection": False}, ("logic-in", "logic-gnd", "load-in", "load-out"), {"width": {"value": 26, "unit": "mm"}, "length": {"value": 34, "unit": "mm"}}, assumption_refs=("assumption-relay-logic-level",)),
            ComponentSpec("component-pump", "Water pump", "water delivery", "subsystem-water", "Low-voltage DC pump delivering water through tubing.", {"voltage_v": 5.0, "current_a": 0.8, "inductive_load": True}, ("power+", "ground", "inlet", "outlet"), {"width": {"value": 40, "unit": "mm"}, "length": {"value": 60, "unit": "mm"}}, assumption_refs=("assumption-pump-rating",)),
            ComponentSpec("component-reservoir", "Reservoir", "water storage", "subsystem-water", "Stores irrigation water away from exposed electronics.", {"capacity_l": 2.0}, ("outlet",), {"width": {"value": 120, "unit": "mm"}, "length": {"value": 180, "unit": "mm"}, "height": {"value": 150, "unit": "mm"}}, assumption_refs=("assumption-reservoir-size",)),
            ComponentSpec("component-tubing", "Tubing", "water routing", "subsystem-water", "Flexible tube between reservoir, pump, and plant.", {"inner_diameter_mm": 6}, ("end-a", "end-b"), {"length": {"value": 1, "unit": "m"}}, assumption_refs=("assumption-tube-fit",)),
            ComponentSpec("component-power", "5 V DC power source", "system power", "subsystem-power", "Isolated low-voltage supply for controller and pump.", {"voltage_v": 5.0, "available_current_a": 2.0, "mains_exposed": False}, ("5v", "ground"), {"width": {"value": 45, "unit": "mm"}, "length": {"value": 70, "unit": "mm"}}, assumption_refs=("assumption-certified-adapter",)),
            ComponentSpec("component-enclosure", "Electronics enclosure", "water separation", "subsystem-structure", "Splash-resistant enclosure for controller, driver, and power connections.", {"waterproofing": "splash-resistant", "contains": ["component-esp32", "component-driver"]}, ("cable-gland",), {"width": {"value": 100, "unit": "mm"}, "length": {"value": 120, "unit": "mm"}, "height": {"value": 60, "unit": "mm"}}, assumption_refs=("assumption-waterproof-enclosure",)),
        )
        connections = (
            ConnectionSpec("connection-sensor-signal", "component-sensor", "component-esp32", "signal", "gpio-sensor", "signal", "Sensor measurement to controller."),
            ConnectionSpec("connection-esp32-driver", "component-esp32", "component-driver", "gpio-pump", "logic-in", "control", "GPIO controls the isolated driver."),
            ConnectionSpec("connection-driver-pump", "component-driver", "component-pump", "load-out", "power+", "switched-power", "Driver switches pump power."),
            ConnectionSpec("connection-power-driver", "component-power", "component-driver", "5v", "load-in", "power", "Supply feeds pump driver."),
            ConnectionSpec("connection-power-esp32", "component-power", "component-esp32", "5v", "3v3", "regulated-power", "Board regulator supplies ESP32."),
            ConnectionSpec("connection-common-ground", "component-power", "component-esp32", "ground", "gnd", "ground", "Common logic reference."),
            ConnectionSpec("connection-reservoir-tube", "component-reservoir", "component-tubing", "outlet", "end-a", "fluid", "Tubing draws from reservoir."),
            ConnectionSpec("connection-tube-pump", "component-tubing", "component-pump", "end-b", "inlet", "fluid", "Tubing connects to pump inlet."),
        )
        entities = [PlannedEntity(project_id, EntityKind.PROJECT, "Automatic Irrigation System", metadata=(("objective", request.objective),))]
        entities += [PlannedEntity(s.id, EntityKind.SUBSYSTEM, s.name, project_id, (("role", s.role), ("description", s.description))) for s in subsystems]
        entities += [PlannedEntity(c.id, EntityKind.COMPONENT, c.name, c.subsystem_id, tuple({
            "role": c.role, "description": c.description, "parameters": c.parameters,
            "interfaces": list(c.interfaces), "dimensions": c.dimensions,
            "representation_status": c.representation_status,
            "evidence_refs": list(c.evidence_refs), "assumption_refs": list(c.assumption_refs),
        }.items())) for c in components]
        for i, text in enumerate(request.requirements): entities.append(PlannedEntity(f"requirement-{i+1}", EntityKind.REQUIREMENT, text, project_id))
        for i, text in enumerate(request.assumptions): entities.append(PlannedEntity(f"assumption-{i+1}", EntityKind.ASSUMPTION, text, project_id))
        referenced_assumptions = sorted({ref for component in components for ref in component.assumption_refs})
        referenced_evidence = sorted({ref for component in components for ref in component.evidence_refs})
        entities += [PlannedEntity(ref, EntityKind.ASSUMPTION, ref.removeprefix("assumption-").replace("-", " ").title(), project_id) for ref in referenced_assumptions]
        entities += [PlannedEntity(ref, EntityKind.EVIDENCE, "ESP32 manufacturer datasheet reference", project_id, (("source_status", "source_required"),)) for ref in referenced_evidence]
        entities += [PlannedEntity(f"constraint-{i+1}", EntityKind.CONSTRAINT, text, project_id) for i, text in enumerate(("Use low-voltage DC only", "Separate water from electronics"))]
        entities += [PlannedEntity(c.id, EntityKind.CONNECTION, c.description, project_id, tuple({
            "source_id": c.source_id, "target_id": c.target_id,
            "source_interface": c.source_interface, "target_interface": c.target_interface,
            "connection_type": c.connection_type,
        }.items())) for c in connections]
        operations = [GraphOperation(PatchOperation.ADD_ENTITY, entity=EngineeringEntity(
            id=e.id, kind=e.kind, name=e.name, parent_id=e.parent_id, metadata=dict(e.metadata),
            source_refs=tuple(dict(e.metadata).get("evidence_refs", [])) + tuple(dict(e.metadata).get("assumption_refs", [])))) for e in entities]
        relationships = tuple(PlannedRelationship(c.id + "-edge", c.source_id, c.target_id, c.connection_type) for c in connections)
        operations += [GraphOperation(PatchOperation.ADD_RELATIONSHIP, relationship=Relationship(id=r.id, source_id=r.source_id, target_id=r.target_id, type=r.type, metadata={"connection_id": r.id.removesuffix("-edge")})) for r in relationships]
        patch = GraphPatch("patch-auto-irrigation-v1", tuple(operations), "Create verified automatic irrigation project")
        plan = ProjectPlan(request, tuple(entities), relationships, patch,
            (RepresentationRequest(project_id, "system_diagram"),), VerificationRequest(patch.id, ("structure", "electrical", "physical", "safety")),
            (WorkspaceEventProposal("project.started", project_id),), subsystems, components, connections,
            ("Use low-voltage DC only", "Separate water from electronics"))
        plan.validate()
        return plan

    def propose_mosfet_replacement(self, graph):
        driver = next((entity for entity in graph.find(kind=EntityKind.COMPONENT)
                       if entity.metadata.get("family", entity.metadata.get("role")) in {"mosfet_driver", "motor_driver", "relay"}
                       or "driver" in str(entity.metadata.get("role", "")).lower()
                       or "driver_type" in entity.metadata.get("parameters", {})), None)
        if driver is None:
            raise ValueError("no compatible driver component")
        metadata = dict(driver.metadata)
        metadata.update({"role": "pump switching", "parameters": {"logic_voltage_v": 3.3, "load_voltage_v": 5.0, "max_current_a": 3.0, "driver_type": "logic-level-mosfet", "flyback_protection": True}, "description": "Logic-level MOSFET driver with flyback diode."})
        operations = [GraphOperation(PatchOperation.UPDATE_ENTITY, target_id=driver.id, changes={"name": "Logic-level MOSFET driver", "metadata": metadata, "verification_status": "conceptual"})]
        for relationship in graph.relationships.values():
            if driver.id not in {relationship.source_id, relationship.target_id}:
                continue
            relationship_metadata = dict(relationship.metadata)
            relationship_metadata["driver_type"] = "logic-level-mosfet"
            operations.append(GraphOperation(PatchOperation.UPDATE_RELATIONSHIP, target_id=relationship.id, changes={"metadata": relationship_metadata}))
        return GraphPatch("patch-relay-to-mosfet", tuple(operations), f"Upgrade {driver.name} to a logic-level MOSFET driver", graph.current_revision_id)

    @staticmethod
    def _id(project_name: str, role: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", "-", project_name.lower()).strip("-")
        return f"{role}-{uuid5(NAMESPACE_URL, f'aura:{normalized}:{role}').hex}"
