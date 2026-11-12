"""
Battery Input Validation (REQ-F3-01 / REQ-F3-02 / Appendix B / booking/validators.py).
Validates battery state-of-charge percentages, boundaries, and consistency.
"""

import math
from typing import Any
from fastapi import HTTPException, status


APPENDIX_B_BATTERY_RULES = {
    "battery_level": {
        "required": True,
        "type": "integer",
        "min": 0,
        "max": 100,
        "unit": "%",
        "description": "Current vehicle battery State of Charge percentage (0 to 100%).",
    },
    "target_soc": {
        "required": False,
        "default": 80,
        "type": "integer",
        "min": 0,
        "max": 100,
        "unit": "%",
        "description": "Target battery State of Charge percentage (default 80%).",
    },
    "low_battery_threshold": {
        "default": 20,
        "unit": "%",
        "description": "Configurable threshold at or below which low-battery assistance is triggered (Appendix B.2).",
    },
    "reserve": {
        "default": 10,
        "unit": "%",
        "description": "Buffer deducted before calculating usable driving range (Appendix B.1).",
    },
    "charging_time": {
        "formula": "energy_required_kwh / effective_charging_power_kw * 60",
        "unit": "minutes",
        "description": "Estimated time based on vehicle and charger power limits (REQ-F3-07).",
    },
    "slot_length": {
        "formula": "ceil(estimated_charging_time_minutes / 15) * 15",
        "unit": "minutes",
        "description": "Charging slot duration rounded up to a 15-minute boundary (REQ-F3-08).",
    },
    "charging_cost": {
        "formula": "energy_required_kwh * station_price_per_kwh",
        "unit": "INR",
        "description": "Estimated charging cost at the station's configured tariff (REQ-F3-09).",
    },
}


def get_battery_rules() -> dict[str, Any]:
    """Return documented Appendix B battery calculation and validation rules."""
    return APPENDIX_B_BATTERY_RULES


def _validate_integer_percentage(value: Any, field_name: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be an integer between 0% and 100%.",
        )

    try:
        numeric_value = float(value)
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be numeric, got: {value!r}.",
        )

    if not math.isfinite(numeric_value) or not numeric_value.is_integer():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be an integer between 0% and 100%, got: {value!r}.",
        )
    if numeric_value < 0 or numeric_value > 100:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{field_name} must be between 0% and 100%, got {numeric_value}%.",
        )
    return int(numeric_value)


def validate_battery_level_input(
    battery_level: Any,
    target_soc: Any = None,
) -> tuple[int, int]:
    """
    Validate battery level and target SoC against Appendix B rules.
    Returns (validated_battery_level, validated_target_soc) as integers.
    Raises HTTPException(422 or 400) on malformed or out-of-range data.
    """
    if battery_level is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Current battery level is mandatory.",
        )

    int_battery = _validate_integer_percentage(battery_level, "Battery level")

    int_target = 80
    if target_soc is not None:
        int_target = _validate_integer_percentage(target_soc, "Target battery level")

    return int_battery, int_target
