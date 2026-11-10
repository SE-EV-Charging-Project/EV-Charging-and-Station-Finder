"""
Battery Input Validation (REQ-F3-01 / REQ-F3-02 / Appendix B / booking/validators.py).
Validates battery state-of-charge percentages, boundaries, and consistency.
"""

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
}


def get_battery_rules() -> dict[str, Any]:
    """Return documented Appendix B battery calculation and validation rules."""
    return APPENDIX_B_BATTERY_RULES


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

    try:
        val = float(battery_level)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Battery level must be numeric, got: {battery_level!r}.",
        )

    if val < 0.0 or val > 100.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Battery level must be between 0% and 100%, got {val}%.",
        )

    int_battery = round(val)

    # Validate target_soc if supplied
    int_target = 80
    if target_soc is not None:
        try:
            target_val = float(target_soc)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Target battery level must be numeric, got: {target_soc!r}.",
            )

        if target_val < 0.0 or target_val > 100.0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Target battery level must be between 0% and 100%, got {target_val}%.",
            )
        int_target = round(target_val)

    return int_battery, int_target
