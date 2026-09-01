from __future__ import annotations

from enum import Enum
from typing import Any


class CapabilityStatus(str, Enum):
    SUPPORTED="SUPPORTED"
    SUPPORTED_WITH_LIMITATIONS="SUPPORTED_WITH_LIMITATIONS"
    UNSUPPORTED="UNSUPPORTED"
    NEEDS_CLARIFICATION="NEEDS_CLARIFICATION"


CAPABILITY_MANIFEST:dict[str,Any]={
    "domain":"low_voltage_mechatronics",
    "supportedComponentFamilies":["microcontroller_board","environmental_sensor","distance_sensor","moisture_sensor","temperature_sensor","light_sensor","small_dc_motor","servo","small_dc_pump","fan","mosfet_driver","relay_module","motor_driver","diode","resistor","low_voltage_power_source","enclosure","reservoir","tube","shaft","simple_arm","mounting_plate","generic_mechanical_part","display","indicator","container","lid","hinge"],
    "supportedMechanicalTemplates":["filleted_enclosure","loft","pipe","box","controller_board","sensor_board","driver_board","power_module","dc_motor","servo","fan","pump","container","lid","hinge","semantic_proxy"],
    "supportedElectricalKinds":["controller","sensor","mosfet","relay","motor","servo","diode","resistor","power_source","indicator","display"],
    "supportedConnections":["signal","control","power","regulated-power","switched-power","ground","fluid","structural","mechanical"],
    "supportedVerificationRules":["semantic_reference_integrity","units","voltage_compatibility","current_capacity","high_current_driver","flyback_protection","common_ground","dimensional_consistency","enclosure_fit","wet_electronics_separation","connection_validity"],
    "supportedRepresentations":["mechanical_3d","circuit_schematic","system_diagram","semantic_proxy"],
    "unsupportedCapabilities":["mains_electrical","medical_device","weapons","vehicles","aircraft","buildings","industrial_machinery","manufacturing_certification","fea","cfd","emi_certification","thermal_certification","battery_safety_certification","fatigue_analysis"],
}

def classify_objective(objective:str)->dict[str,Any]:
    text=objective.lower().strip()
    if len(text.split()) < 4 or text in {"build me something cool.","build me something cool"}:
        return {"status":CapabilityStatus.NEEDS_CLARIFICATION.value,"reasons":["The objective does not identify a device, function, or measurable behavior."],"questions":["What should the device sense, move, or control?"]}
    outside={"aircraft":"aircraft engineering","passenger jet":"aircraft engineering","welding cell":"industrial machinery","factory robot":"industrial machinery","medical":"medical devices","weapon":"weapons","building":"building engineering","mains":"mains electrical engineering"}
    hits=sorted({label for word,label in outside.items() if word in text})
    if hits:
        return {"status":CapabilityStatus.UNSUPPORTED.value,"reasons":[f"Current capability excludes {', '.join(hits)}."],"supportedAlternative":"A small low-voltage conceptual mechatronic analogue may be created instead."}
    if "robotic arm" in text or "robot arm" in text:
        return {"status":CapabilityStatus.SUPPORTED_WITH_LIMITATIONS.value,"reasons":["A low-voltage servo-driven conceptual arm is supported; payload, structural analysis, precision kinematics, and manufacturing readiness are not verified."]}
    keywords=("esp32","sensor","fan","feeder","weather","tank","servo","motor","pump","monitor","controller","automation","robotic","temperature","humidity","lid","irrigation")
    if any(word in text for word in keywords):
        return {"status":CapabilityStatus.SUPPORTED.value,"reasons":["Objective is within bounded small low-voltage mechatronics."]}
    return {"status":CapabilityStatus.SUPPORTED_WITH_LIMITATIONS.value,"reasons":["Only supported low-voltage mechatronic portions will be constructed; other claims remain conceptual."]}

def compact_capability_context()->str:
    m=CAPABILITY_MANIFEST
    return (f"Domain: {m['domain']}. Component families: {', '.join(m['supportedComponentFamilies'])}. "
        f"Representations: {', '.join(m['supportedMechanicalTemplates'])}. Verification: {', '.join(m['supportedVerificationRules'])}. "
        f"Never claim: {', '.join(m['unsupportedCapabilities'])}.")
