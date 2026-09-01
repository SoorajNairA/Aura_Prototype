from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class InterfaceDefinition:
    name: str
    kind: str
    position: tuple[float, float, float] = (0, 0, 0)
    orientation: tuple[float, float, float, float] = (0, 0, 0, 1)
    axis: tuple[float, float, float] | None = None
    compatible: tuple[str, ...] = ()
    clearance_mm: float = 0


def component_interfaces(family: str, dimensions: tuple[float, float, float], parameters: dict[str, Any] | None = None) -> tuple[InterfaceDefinition, ...]:
    """Return reusable physical/electrical interfaces for a component family."""
    width, length, height = dimensions
    electrical = {
        "controller": (("power", "electrical_power_in"), ("ground", "electrical_ground"), *((f"signal-{index}", "control_output") for index in range(1, 9))),
        "microcontroller_board": (("power", "electrical_power_in"), ("ground", "electrical_ground"), *((f"signal-{index}", "control_output") for index in range(1, 9))),
        "servo": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "control_input")),
        "low_voltage_power_source": (("power", "electrical_power_out"), ("ground", "electrical_ground")),
        "system power": (("power", "electrical_power_out"), ("ground", "electrical_ground")),
        "temperature_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "light_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "environmental_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "distance_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "soil_moisture_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "motion_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "orientation_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "conceptual_sensor": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
        "indicator": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "control_input")),
        "fan": (("power", "electrical_power_in"), ("ground", "electrical_ground")),
        "small_dc_motor": (("power", "electrical_power_in"), ("ground", "electrical_ground")),
        "small_dc_pump": (("power", "electrical_power_in"), ("ground", "electrical_ground")),
        "mosfet_driver": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "control_input"), ("load-output", "electrical_power_out")),
        "motor_driver": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "control_input"), ("load-output", "electrical_power_out")),
        "relay_module": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "control_input"), ("load-output", "electrical_power_out")),
        "bare_relay": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("load-output", "electrical_power_out")),
        "flyback_diode": (("anode", "passive_terminal"), ("cathode", "passive_terminal")),
        "resistor": (("terminal-a", "passive_terminal"), ("terminal-b", "passive_terminal")),
        "wireless_module": (("power", "electrical_power_in"), ("ground", "electrical_ground"), ("signal", "signal_output")),
    }
    electrical_ports = electrical.get(family, ())
    result = []
    for index, (name, kind) in enumerate(electrical_ports):
        # Electrical ports live on a visible edge/cable exit rather than at the
        # component centre.  Exact pin pitch remains conceptual, but every port
        # has a deterministic world-resolvable location for future wire routing.
        if family == "servo":
            position = (width / 2, -length / 2, -height * .25 + index * 2)
        elif family in {"controller", "microcontroller_board", "mosfet_driver", "motor_driver", "relay_module", "bare_relay", "wireless_module"}:
            position = (-width / 2 + min(index, 4) * width / 4, -length / 2, height / 2)
        elif family in {"low_voltage_power_source", "system power"}:
            position = ((-1 if index else 1) * width * .22, -length / 2, height / 2)
        else:
            position = (-width / 2 + index * max(width / max(len(electrical_ports), 1), 2), -length / 2, height / 2)
        result.append(InterfaceDefinition(name, kind, position, compatible=("electrical_connector",)))
    if family in {"servo", "small_dc_motor"}:
        output_name = "output" if family == "servo" else "shaft"
        output_axis = tuple((parameters or {}).get("output_axis", (0, 0, 1))) if family == "servo" else (0, -1, 0)
        half_extent = abs(output_axis[0])*width/2 + abs(output_axis[1])*length/2 + abs(output_axis[2])*height/2
        output_position = tuple(value*(half_extent+3) for value in output_axis)
        result += [
            InterfaceDefinition(output_name, "rotating_output", output_position, axis=output_axis, compatible=("rotating_input",)),
            InterfaceDefinition("body-mount", "fixed_mount", (0, 0, -height / 2), axis=(0, 0, -1), compatible=("structural_face",)),
        ]
        if family == "servo":
            result.append(InterfaceDefinition("cable-exit", "cable_exit", (width / 2, -length / 2, -height * .25), axis=(1, 0, 0), compatible=("cable_exit",)))
    elif family == "drive_wheel":
        result.append(InterfaceDefinition("hub-input", "rotating_input", (0, 0, 0), axis=(0, 1, 0), compatible=("rotating_output",)))
    elif family == "linear_drive":
        # A reusable rotary-to-linear transmission.  The actuator mates to the
        # input; the moving panel mates to the linear output.  It is deliberately
        # separate from a rotary joint so a sliding mechanism cannot silently
        # collapse into a revolute arm layout.
        result += [
            InterfaceDefinition("rotating-input", "rotating_input", (0, -length / 2, 0), axis=(0, -1, 0), compatible=("rotating_output",)),
            InterfaceDefinition("linear-output", "linear_output", (0, length / 2, 0), axis=(0, 1, 0), compatible=("linear_input",)),
        ]
    elif family == "sliding_panel":
        result += [
            InterfaceDefinition("linear-input", "linear_input", (0, -length / 2, height / 2), axis=(0, 1, 0), compatible=("linear_output",)),
            InterfaceDefinition("end-face", "structural_face", (0, length / 2, 0), axis=(0, 0, 1), compatible=("fixed_mount", "structural_face")),
        ]
    elif family == "articulated_link":
        result += [
            # The joint axis crosses the proximal end of the beam; it is not
            # collinear with the beam length.  This gives rotary mechanisms a
            # readable arm/frame rather than a stack along the shaft axis.
            InterfaceDefinition("joint-input", "rotating_input", (0, 0, -height / 2), axis=(0, 1, 0), compatible=("rotating_output", "hinge_axis")),
            InterfaceDefinition("end-face", "structural_face", (0, 0, height / 2), axis=(0, 0, 1), compatible=("fixed_mount", "structural_face")),
        ]
    elif family in {"rotating_platform", "camera_platform"}:
        result += [
            InterfaceDefinition("joint-input", "rotating_input", (0, 0, -height / 2), axis=(0, 0, 1), compatible=("rotating_output", "hinge_axis")),
            InterfaceDefinition("fixed-input", "fixed_mount", (0, 0, -height / 2), axis=(0, 0, -1), compatible=("structural_face",)),
            InterfaceDefinition("top-face", "structural_face", (0, 0, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)),
            InterfaceDefinition("sensor-mount", "structural_face", (width * .32, length * .28, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)),
        ]
    elif family in {"panel", "tool_platform"}:
        result += [
            InterfaceDefinition("fixed-input", "fixed_mount", (0, 0, -height / 2), axis=(0, 0, -1), compatible=("structural_face",)),
            InterfaceDefinition("front-face", "structural_face", (0, 0, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)),
            InterfaceDefinition("sensor-mount", "structural_face", (width * .34, length * .32, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)),
        ]
    elif family in {"simple_arm", "lid", "dispensing-mechanism", "generic_mechanical_part", "tracked_object"}:
        result += [
            InterfaceDefinition("joint-input", "rotating_input", (0, 0, -length / 2), axis=(0, 1, 0), compatible=("rotating_output", "hinge_axis")),
            InterfaceDefinition("end-face", "structural_face", (0, 0, length / 2), axis=(0, 0, 1), compatible=("fixed_mount", "structural_face")),
            InterfaceDefinition("fixed-input", "fixed_mount", (0, 0, -length / 2), axis=(0, 0, -1), compatible=("structural_face",)),
        ]
        if family == "lid":
            # A driven lid can use one rotary interface for the actuator and a
            # distinct hinge interface for its stationary support.
            result.append(InterfaceDefinition("hinge-input", "rotating_input", (width / 2, 0, -length / 2), axis=(0, 1, 0), compatible=("hinge_axis",)))
    elif family in {"mounting_plate", "base", "structural_frame", "enclosure", "container"}:
        # A support may carry more than one component.  These are distinct,
        # stable interfaces rather than an implicitly reusable component centre.
        result.append(InterfaceDefinition("mount-face", "structural_face", (0, 0, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)))
        if family in {"mounting_plate", "base", "structural_frame"}:
            for index, (x, y) in enumerate(((-.28, -.28), (-.28, .28), (.28, -.28), (.28, .28)), 1):
                result.append(InterfaceDefinition(f"mount-face-{index}", "structural_face", (width * x, length * y, height / 2), axis=(0, 0, 1), compatible=("fixed_mount",)))
        if family in {"mounting_plate", "base", "structural_frame"}:
            for index, (x, y) in enumerate(((-.28, -.28), (-.28, .28), (.28, -.28), (.28, .28)), 1):
                result.append(InterfaceDefinition(f"drive-mount-{index}", "structural_face", (width * x, length * y, -height / 2), axis=(0, 0, -1), compatible=("fixed_mount",)))
    elif family == "hinge":
        result.append(InterfaceDefinition("axis", "hinge_axis", (0, 0, 0), axis=(0, 1, 0), compatible=("rotating_input",)))
    if family in {"controller", "microcontroller_board", "low_voltage_power_source", "system power", "temperature_sensor", "light_sensor", "environmental_sensor", "distance_sensor", "soil_moisture_sensor", "motion_sensor", "orientation_sensor", "conceptual_sensor", "mosfet_driver", "motor_driver", "relay_module", "bare_relay", "wireless_module", "indicator", "flyback_diode", "resistor"}:
        result.append(InterfaceDefinition("body-mount", "fixed_mount", (0, 0, -height / 2), axis=(0, 0, -1), compatible=("structural_face",)))
    return tuple(result)


def interface_dict(owner: str, interface: InterfaceDefinition) -> dict[str, Any]:
    return {"interfaceId": f"{owner}:{interface.name}", "semanticId": owner, "type": interface.kind,
        "localPosition": list(interface.position), "localOrientation": list(interface.orientation),
        "axis": list(interface.axis) if interface.axis else None, "compatibleTypes": list(interface.compatible),
        "clearanceMm": interface.clearance_mm}
