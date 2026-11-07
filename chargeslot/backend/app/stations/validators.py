"""
Station and Charger Value Validators (REQ-F2-04 / CS19-030 / stations/validators.py).
Enforces SRS Appendix B.4 validation ranges and data integrity rules for all stations,
chargers, and connector types with field-level rejection messages.
"""

import re
from typing import Any
from fastapi import HTTPException, status
from app.models.vehicle import ConnectorType


APPENDIX_B_STATION_RULES: dict[str, dict[str, Any]] = {
    "name": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 100,
        "description": "Station name (1 to 100 characters; non-empty).",
    },
    "address": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 200,
        "description": "Street address (1 to 200 characters; non-empty).",
    },
    "latitude": {
        "required": True,
        "type": "decimal",
        "min": -90.0,
        "max": 90.0,
        "unit": "degrees",
        "description": "Station latitude coordinate [-90.0, 90.0].",
    },
    "longitude": {
        "required": True,
        "type": "decimal",
        "min": -180.0,
        "max": 180.0,
        "unit": "degrees",
        "description": "Station longitude coordinate [-180.0, 180.0].",
    },
    "amenities": {
        "required": False,
        "type": "list",
        "item_type": "string",
        "description": "Optional list of station amenities e.g. restroom, cafe, parking, wifi.",
    },
    "operating_hours": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 100,
        "description": "Daily opening hours e.g. '24 hours' or '08:00-22:00'.",
    },
    "contact_phone": {
        "required": True,
        "type": "string",
        "min_length": 5,
        "max_length": 20,
        "description": "Station contact phone number (5 to 20 digits, E.164 allowed).",
    },
    "contact_email": {
        "required": False,
        "type": "string",
        "max_length": 120,
        "description": "Optional contact email address.",
    },
}

APPENDIX_B_CHARGER_RULES: dict[str, dict[str, Any]] = {
    "power_kw": {
        "required": True,
        "type": "decimal",
        "min": 1.0,
        "max": 400.0,
        "unit": "kW",
        "description": "Rated power of the charger in kW (1.0 to 400.0 kW).",
    },
    "current_type": {
        "required": True,
        "type": "enum",
        "allowed_values": ["AC", "DC"],
        "description": "Current type: AC or DC.",
    },
    "connector_type": {
        "required": True,
        "type": "enum",
        "allowed_values": [ct.value for ct in ConnectorType],
        "description": "Standardized connector type: CCS2, CHAdeMO, Type 2, GB/T.",
    },
    "gateway_id": {
        "required": True,
        "type": "string",
        "min_length": 1,
        "max_length": 100,
        "description": "Charge point identifier matching gateway / OCPP hardware.",
    },
}

PHONE_REGEX = re.compile(r"^\+?[0-9\s\-()]{5,20}$")
EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_station_values(
    data: dict[str, Any], partial: bool = False
) -> tuple[bool, dict[str, str]]:
    """
    Validates station attributes against Appendix B.4 and REQ-F2-04 rules.
    Returns (is_valid, errors_dict) with field-level rejection messages.
    """
    errors: dict[str, str] = {}

    # 1. Name validation
    if "name" in data and data["name"] is not None:
        name = str(data["name"]).strip()
        if not name:
            errors["name"] = "Station name is required and cannot be empty."
        elif len(name) > 100:
            errors["name"] = "Station name must not exceed 100 characters."
    elif not partial:
        errors["name"] = "Station name is required (REQ-F2-04)."

    # 2. Address validation
    if "address" in data and data["address"] is not None:
        address = str(data["address"]).strip()
        if not address:
            errors["address"] = "Station address is required and cannot be empty."
        elif len(address) > 200:
            errors["address"] = "Station address must not exceed 200 characters."
    elif not partial:
        errors["address"] = "Station address is required (REQ-F2-04)."

    # 3. Latitude validation [-90.0, 90.0]
    if "latitude" in data and data["latitude"] is not None:
        try:
            lat = float(data["latitude"])
            if lat < -90.0 or lat > 90.0:
                errors["latitude"] = "Latitude must be between -90.0 and 90.0 degrees (REQ-F2-04)."
        except (ValueError, TypeError):
            errors["latitude"] = "Latitude must be a valid decimal number."
    elif not partial:
        errors["latitude"] = "Latitude coordinate is required (REQ-F2-04)."

    # 4. Longitude validation [-180.0, 180.0]
    if "longitude" in data and data["longitude"] is not None:
        try:
            lon = float(data["longitude"])
            if lon < -180.0 or lon > 180.0:
                errors["longitude"] = "Longitude must be between -180.0 and 180.0 degrees (REQ-F2-04)."
        except (ValueError, TypeError):
            errors["longitude"] = "Longitude must be a valid decimal number."
    elif not partial:
        errors["longitude"] = "Longitude coordinate is required (REQ-F2-04)."

    # 5. Operating hours validation
    if "operating_hours" in data and data["operating_hours"] is not None:
        hours = str(data["operating_hours"]).strip()
        if not hours:
            errors["operating_hours"] = "Operating hours cannot be empty."
        elif len(hours) > 100:
            errors["operating_hours"] = "Operating hours must not exceed 100 characters."
    elif not partial:
        errors["operating_hours"] = "Operating hours are required (REQ-F2-04)."

    # 6. Contact phone validation
    if "contact_phone" in data and data["contact_phone"] is not None:
        phone = str(data["contact_phone"]).strip()
        if not phone:
            errors["contact_phone"] = "Contact phone cannot be empty."
        elif len(phone) < 5 or len(phone) > 20 or not PHONE_REGEX.match(phone):
            errors["contact_phone"] = "Contact phone must be a valid telephone number between 5 and 20 digits."
    elif not partial:
        errors["contact_phone"] = "Contact phone is required (REQ-F2-04)."

    # 7. Contact email validation (optional)
    if "contact_email" in data and data["contact_email"] is not None and data["contact_email"] != "":
        email = str(data["contact_email"]).strip()
        if len(email) > 120 or not EMAIL_REGEX.match(email):
            errors["contact_email"] = "Contact email must be a valid email address not exceeding 120 characters."

    # 8. Amenities validation (optional list)
    if "amenities" in data and data["amenities"] is not None:
        if not isinstance(data["amenities"], list):
            errors["amenities"] = "Amenities must be a list of strings."
        else:
            for item in data["amenities"]:
                if not isinstance(item, str) or len(item.strip()) == 0:
                    errors["amenities"] = "Amenities must contain non-empty string labels."
                    break

    is_valid = len(errors) == 0
    return is_valid, errors


def validate_charger_values(
    data: dict[str, Any], partial: bool = False
) -> tuple[bool, dict[str, str]]:
    """
    Validates charger & connector attributes per Appendix B.4 and REQ-F2-04.
    Rejects invalid power, current type, or connector type with field-level errors.
    """
    errors: dict[str, str] = {}
    valid_connectors = {ct.value for ct in ConnectorType}
    valid_current_types = {"AC", "DC"}

    # 1. Power rating (1.0 to 400.0 kW)
    if "power_kw" in data and data["power_kw"] is not None:
        try:
            power = float(data["power_kw"])
            if power < 1.0 or power > 400.0:
                errors["power_kw"] = "Charger power must be between 1.0 and 400.0 kW (REQ-F2-04)."
        except (ValueError, TypeError):
            errors["power_kw"] = "Charger power must be a valid decimal number."
    elif not partial:
        errors["power_kw"] = "Charger power rating is required (REQ-F2-04)."

    # 2. Current type (AC or DC)
    if "current_type" in data and data["current_type"] is not None:
        current_type = str(data["current_type"]).strip().upper()
        if current_type not in valid_current_types:
            errors["current_type"] = f"Current type must be 'AC' or 'DC'. Received: {data['current_type']}"
    elif not partial:
        errors["current_type"] = "Current type (AC/DC) is required (REQ-F2-04)."

    # 3. Connector type
    if "connector_type" in data and data["connector_type"] is not None:
        conn_raw = str(data["connector_type"]).strip()
        matched = False
        for valid in valid_connectors:
            if conn_raw.lower() == valid.lower():
                matched = True
                break
        if not matched:
            allowed_str = ", ".join(sorted(valid_connectors))
            errors["connector_type"] = (
                f"Invalid connector type '{conn_raw}'. Must be one of: {allowed_str} (REQ-F2-04)."
            )
    elif not partial:
        errors["connector_type"] = "Connector type is required (REQ-F2-04)."

    # 4. Gateway ID
    if "gateway_id" in data and data["gateway_id"] is not None:
        gw = str(data["gateway_id"]).strip()
        if not gw:
            errors["gateway_id"] = "Gateway identifier cannot be empty."
        elif len(gw) > 100:
            errors["gateway_id"] = "Gateway identifier must not exceed 100 characters."
    elif not partial:
        errors["gateway_id"] = "Gateway charge point identifier is required (REQ-F2-04)."

    is_valid = len(errors) == 0
    return is_valid, errors


def enforce_station_values(data: dict[str, Any], partial: bool = False) -> None:
    """
    Enforces station validation per REQ-F2-04.
    Raises HTTP 422 Unprocessable Entity with field-level rejection dictionary if invalid.
    """
    is_valid, errors = validate_station_values(data, partial=partial)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Station validation failed (REQ-F2-04). Please correct the field errors.",
                "errors": errors,
            },
        )


def enforce_charger_values(data: dict[str, Any], partial: bool = False) -> None:
    """
    Enforces charger and connector validation per REQ-F2-04.
    Raises HTTP 422 Unprocessable Entity with field-level rejection dictionary if invalid.
    """
    is_valid, errors = validate_charger_values(data, partial=partial)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "Charger validation failed (REQ-F2-04). Please correct the field errors.",
                "errors": errors,
            },
        )


def get_station_validation_rules() -> dict[str, Any]:
    """
    Returns Appendix B.4 validation constraints for stations and chargers.
    """
    return {
        "station_rules": APPENDIX_B_STATION_RULES,
        "charger_rules": APPENDIX_B_CHARGER_RULES,
    }
