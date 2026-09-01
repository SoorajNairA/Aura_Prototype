from __future__ import annotations

from dataclasses import replace

import pytest

from aura.planner.schemas import ProjectRequest
from aura.planner.service import PlannerService
from aura.verification.delta import DeltaClassification, FindingIdentity, compare_verification
from aura.verification.service import VerificationService


SCENARIOS=(
    ("solar_tracker","Build a tabletop two-axis solar tracker","axis","MECH_CONTROLLED_AXIS_MISSING"),
    ("soil_pump","Build an automatic soil-moisture pump","direct_load","ELEC_DRIVER_REQUIRED"),
    ("variable_fan","Build a variable-speed DC fan with temperature sensing","direct_load","ELEC_DRIVER_REQUIRED"),
    ("remote_car","Build a remote-controlled car with two driven wheels","mechanical","MECH_301"),
    ("pan_tilt","Build a two-axis pan tilt camera","axis","MECH_CONTROLLED_AXIS_MISSING"),
    ("tank_filler","Build an automatic tank filler using a distance sensor and pump","sensor_power","ELEC_POWER_REQUIRED"),
    ("sliding_door","Build an automatic sliding door with a linear drive","mechanical","MECH_301"),
)


def generate(name,objective):
    return PlannerService().plan(ProjectRequest(name,objective,(objective,)))


def mutate(plan,kind):
    if kind=="axis":
        actuators=[item for item in plan.components if item.parameters.get("controlled_axis_ids")]
        target=actuators[-1]
        return replace(plan,components=tuple(replace(item,parameters=dict(item.parameters)|{"controlled_axis_ids":[]}) if item.id==target.id else item for item in plan.components))
    if kind=="direct_load":
        load=next(item for item in plan.components if item.role in {"small_dc_pump","fan"})
        controller=next(item for item in plan.components if item.role=="microcontroller_board")
        edge=next(item for item in plan.connections if item.target_id==load.id and item.connection_type=="switched-power")
        signal=next(item for item in controller.interfaces if item.startswith("signal-"))
        direct=replace(edge,source_id=controller.id,source_interface=signal,connection_type="control")
        return replace(plan,connections=tuple(direct if item.id==edge.id else item for item in plan.connections))
    if kind=="mechanical":
        edge=next(item for item in plan.connections if item.connection_type=="mechanical" and "wheel" in f"{item.source_id} {item.target_id}")
        return replace(plan,connections=tuple(item for item in plan.connections if item.id!=edge.id))
    sensor=next(item for item in plan.components if "sensor" in item.id)
    return replace(plan,connections=tuple(item for item in plan.connections if not (item.target_id==sensor.id and item.connection_type=="power")))


@pytest.mark.parametrize("name,objective,mutation,expected",SCENARIOS,ids=[item[0] for item in SCENARIOS])
def test_fresh_generated_project_mutation_matrix(name,objective,mutation,expected):
    plan=generate(name,objective)
    baseline=VerificationService().verify(plan)
    damaged=VerificationService().verify(mutate(plan,mutation))
    delta=compare_verification(baseline,damaged)
    assert not any(item.blocking for item in baseline.findings)
    assert expected in [item.check for item in damaged.findings if item.blocking]
    assert delta.classification is DeltaClassification.WORSENS
    assert delta.blocking_introduced_count>=1
    # Provenance/resolution findings unrelated to the mutation retain their
    # structured identity instead of randomly disappearing or changing.
    baseline_generic={FindingIdentity.from_finding(item) for item in baseline.findings if item.check=="generic-component"}
    damaged_generic={FindingIdentity.from_finding(item) for item in damaged.findings if item.check=="generic-component"}
    assert baseline_generic==damaged_generic


def test_generated_fan_supports_two_step_incremental_repair():
    original=generate("repair_fan","Build a variable-speed DC fan with temperature sensing")
    direct=mutate(original,"direct_load")
    sensor=next(item for item in direct.components if item.role=="temperature_sensor")
    twice_broken=replace(direct,connections=tuple(item for item in direct.connections if not (item.target_id==sensor.id and item.connection_type=="power")))
    first_result=VerificationService().verify(twice_broken)

    # Restore only the driver/load architecture; sensor power remains absent.
    original_load_edge=next(item for item in original.connections if item.connection_type=="switched-power")
    partly_fixed=replace(twice_broken,connections=tuple(original_load_edge if item.id==original_load_edge.id else item for item in twice_broken.connections))
    partial_result=VerificationService().verify(partly_fixed)
    partial_delta=compare_verification(first_result,partial_result)
    assert partial_delta.classification is DeltaClassification.IMPROVES
    assert partial_delta.blocking_resolved_count>=1 and partial_delta.blocking_introduced_count==0
    assert partial_delta.readiness_after=="BUILD_INCOMPLETE"
    assert "ELEC_POWER_REQUIRED" in [item.check for item in partial_result.findings if item.blocking]

    final_result=VerificationService().verify(original)
    final_delta=compare_verification(partial_result,final_result)
    assert final_delta.classification is DeltaClassification.RESOLVES_ALL
    assert final_delta.readiness_after in {"SUPPORTED","SUPPORTED_WITH_LIMITATIONS"}


def test_generated_repair_keeps_unrelated_findings_stable():
    original=generate("stable_fan","Build a variable-speed DC fan with temperature sensing")
    damaged=mutate(original,"direct_load")
    before=VerificationService().verify(damaged);after=VerificationService().verify(original)
    delta=compare_verification(before,after)
    unchanged={FindingIdentity.from_finding(item) for item in delta.unchanged_findings}
    expected={FindingIdentity.from_finding(item) for item in before.findings if item.check in {"generic-component","catalogue-properties","representation-provenance"}}
    assert expected<=unchanged
