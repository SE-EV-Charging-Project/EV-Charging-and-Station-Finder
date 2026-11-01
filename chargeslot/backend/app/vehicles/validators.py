"""
Vehicle Value Validators (REQ-F1-24 / CS19-024 / vehicles/validators.py).
Enforces SRS Appendix B.3 validation ranges and data integrity rules for all EV vehicles.
"""

from typing import Any
from fastapi import HTTPException, status
from app.models.vehicle import ConnectorType


APPENDIX_B_VEHICLE_RULES = {
    "make": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 40,
        "description": "Vehicle make/manufacturer name (up to 40 characters; non-empty).",
    },
    "model": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 40,
        "description": "Vehicle model name (up to 40 characters; non-empty).",
    },
    "battery_kwh": {
        "required": True,
        "type": "decimal",
        "min": 5.0,
        "max": 250.0,
        "unit": "kWh",
        "description": "Battery capacity in kWh (5 to 250 kWh).",
    },
    "connector_type": {
        "required": True,
        "type": "enum",
        "allowed_values": [ct.value for ct in ConnectorType],
        "description": "Standardized charging connector type: CCS2, CHAdeMO, Type 2, GB/T.",
    },
    "max_ac_kw": {
        "required": True,
        "type": "decimal",
        "min": 1.0,
        "max": 50.0,
        "unit": "kW",
        "description": "Maximum AC charging rate in kW (1 to 50 kW).",
    },
    "max_dc_kw": {
        "required": False,
        "type": "decimal",
        "default": 0.0,
        "min_if_supported": 10.0,
        "max": 400.0,
        "unit": "kW",
        "description": "Maximum DC charging rate in kW (0 if unsupported, or 10 to 400 kW).",
    },
    "consumption_kwh_100km": {
        "required": True,
        "type": "decimal",
        "min": 5.0,
        "max": 50.0,
        "unit": "kWh/100km",
        "description": "Energy consumption in kWh per 100 km (5 to 50 kWh/100km).",
    },
    "registration_no": {
        "required": False,
        "type": "string",
        "max_length": 15,
        "description": "Optional vehicle registration or license plate number (up to 15 characters).",
    },
    "max_vehicles_per_driver": {
        "max": 5,
        "description": "Maximum allowable vehicles per driver account (REQ-F1-22).",
    },
}


def get_appendix_b_rules() -> dict[str, Any]:
    """
    Returns the complete schema of vehicle fields and boundary limits from Appendix B.3.
    """
    return APPENDIX_B_VEHICLE_RULES


def validate_vehicle_values(data: dict[str, Any]) -> tuple[bool, dict[str, str]]:
    """
    Validates a vehicle data dictionary against SRS Appendix B.3 ranges.
    Returns (is_valid, errors_dict).
    """
    errors: dict[str, str] = {}

    # 1. make
    if "make" in data and data["make"] is not None:
        val = str(data["make"]).strip()
        if not val:
            errors["make"] = "Vehicle make cannot be empty or blank."
        elif len(val) > 40:
            errors["make"] = "Vehicle make cannot exceed 40 characters."

    # 2. model
    if "model" in data and data["model"] is not None:
        val = str(data["model"]).strip()
        if not val:
            errors["model"] = "Vehicle model cannot be empty or blank."
        elif len(val) > 40:
            errors["model"] = "Vehicle model cannot exceed 40 characters."

    # 3. battery_kwh (5 - 250)
    if "battery_kwh" in data and data["battery_kwh"] is not None:
        try:
            val_f = float(data["battery_kwh"])
            if val_f < 5.0 or val_f > 250.0:
                errors["battery_kwh"] = "Battery capacity must be between 5.0 and 250.0 kWh (Appendix B.3)."
        except (ValueError, TypeError):
            errors["battery_kwh"] = "Battery capacity must be a valid numeric decimal between 5.0 and 250.0 kWh."

    # 4. connector_type
    if "connector_type" in data and data["connector_type"] is not None:
        raw_c = data["connector_type"]
        if hasattr(raw_c, "value"):
            c_val = str(raw_c.value).strip()
        else:
            c_val = str(raw_c).strip()
        allowed = [ct.value for ct in ConnectorType]
        if c_val not in allowed:
            errors["connector_type"] = f"Invalid connector type '{c_val}'. Allowed values: {', '.join(allowed)}."

    # 5. max_ac_kw (1 - 50)
    if "max_ac_kw" in data and data["max_ac_kw"] is not None:
        try:
            val_f = float(data["max_ac_kw"])
            if val_f < 1.0 or val_f > 50.0:
                errors["max_ac_kw"] = "Maximum AC charging rate must be between 1.0 and 50.0 kW (Appendix B.3)."
        except (ValueError, TypeError):
            errors["max_ac_kw"] = "Maximum AC charging rate must be a valid numeric decimal between 1.0 and 50.0 kW."

    # 6. max_dc_kw (0 or 10 - 400)
    if "max_dc_kw" in data and data["max_dc_kw"] is not None:
        try:
            val_f = float(data["max_dc_kw"])
            if val_f < 0.0 or (0.0 < val_f < 10.0) or val_f > 400.0:
                errors["max_dc_kw"] = "Maximum DC charging rate must be 0 kW (unsupported) or between 10.0 and 400.0 kW (Appendix B.3)."
        except (ValueError, TypeError):
            errors["max_dc_kw"] = "Maximum DC charging rate must be a valid numeric decimal (0 or 10.0 to 400.0 kW)."

    # 7. consumption_kwh_100km (5 - 50)
    if "consumption_kwh_100km" in data and data["consumption_kwh_100km"] is not None:
        try:
            val_f = float(data["consumption_kwh_100km"])
            if val_f < 5.0 or val_f > 50.0:
                errors["consumption_kwh_100km"] = "Energy consumption must be between 5.0 and 50.0 kWh per 100 km (Appendix B.3)."
        except (ValueError, TypeError):
            errors["consumption_kwh_100km"] = "Energy consumption must be a valid numeric decimal between 5.0 and 50.0 kWh/100km."

    # 8. registration_no (max 15 chars)
    if "registration_no" in data and data["registration_no"] is not None:
        val = str(data["registration_no"]).strip()
        if len(val) > 15:
            errors["registration_no"] = "Vehicle registration number cannot exceed 15 characters (Appendix B.3)."

    return len(errors) == 0, errors


def enforce_vehicle_values(data: dict[str, Any]) -> None:
    """
    Validates vehicle data and raises HTTPException 422 Unprocessable Entity
    with specific error details if values violate Appendix B.3 (REQ-F1-24).
    """
    is_valid, errors = validate_vehicle_values(data)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Vehicle specifications violate allowed ranges defined in Appendix B.3 (REQ-F1-24).",
                "errors": errors,
            },
        )
