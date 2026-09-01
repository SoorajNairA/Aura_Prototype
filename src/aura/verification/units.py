from __future__ import annotations

from pint import DimensionalityError, UnitRegistry

ureg = UnitRegistry(autoconvert_offset_to_baseunit=True)


def quantity(value: float, unit: str):
    return value * ureg.parse_units(unit)


def compatible(value_a: float, unit_a: str, value_b: float, unit_b: str) -> bool:
    try:
        quantity(value_a, unit_a).to(unit_b)
        return True
    except (DimensionalityError, ValueError):
        return False


def in_range(value: float, unit: str, minimum: float, maximum: float, range_unit: str) -> bool:
    measured = quantity(value, unit).to(range_unit).magnitude
    return minimum <= measured <= maximum


def convert(value: float, unit: str, target_unit: str) -> float:
    return float(quantity(value, unit).to(target_unit).magnitude)
