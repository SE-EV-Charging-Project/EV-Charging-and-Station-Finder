"""
Booking Schemas (Feature 3: Battery-Aware Booking and Auto-Booking / CS19-055 / REQ-F3-01).
"""

from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Any


class BatteryLevelInputRequest(BaseModel):
    """
    Request model for driver battery level input (REQ-F3-01 / CS19-055).
    Accepts battery level percentage (0 to 100%), optional target SoC, and optional vehicle ID.
    Supports both 'battery_level', 'current_soc', and 'current_battery_percentage'.
    """
    model_config = ConfigDict(populate_by_name=True)

    battery_level: int = Field(
        ...,
        ge=0,
        le=100,
        description="Current vehicle battery State of Charge percentage (0 to 100%).",
        alias="current_soc",
    )
    target_soc: int | None = Field(
        default=80,
        ge=0,
        le=100,
        description="Target battery State of Charge percentage (default 80%).",
    )
    vehicle_id: int | None = Field(
        default=None,
        description="Optional vehicle ID; if omitted, operates on driver's primary default vehicle.",
    )

    @field_validator("battery_level", mode="before")
    @classmethod
    def validate_battery_level(cls, v: Any) -> int:
        if v is None:
            raise ValueError("Current battery level cannot be null or omitted.")
        try:
            numeric_val = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"Battery level must be numeric, got: {v!r}.")
        if numeric_val < 0.0 or numeric_val > 100.0:
            raise ValueError(f"Battery level must be between 0% and 100%, got {numeric_val}%.")
        return round(numeric_val)

    @field_validator("target_soc", mode="before")
    @classmethod
    def validate_target_soc(cls, v: Any) -> int | None:
        if v is None:
            return 80
        try:
            numeric_val = float(v)
        except (ValueError, TypeError):
            raise ValueError(f"Target battery level must be numeric, got: {v!r}.")
        if numeric_val < 0.0 or numeric_val > 100.0:
            raise ValueError(f"Target battery level must be between 0% and 100%, got {numeric_val}%.")
        return round(numeric_val)


class BatteryLevelResponse(BaseModel):
    """
    Response model for driver battery level and range calculation (REQ-F3-01 / CS19-055 / Appendix B).
    """
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: int
    user_id: int
    make: str
    model: str
    registration_no: str | None = None
    battery_kwh: float
    current_soc: int
    current_battery_percentage: int
    target_soc: int
    usable_range_km: float
    estimated_range_km: float
    energy_required_kwh: float
    is_low_battery: bool
    low_battery_threshold: int
    battery_updated_at: datetime | None = None
    message: str


class BatteryRulesResponse(BaseModel):
    """
    Response model detailing Appendix B battery rules and defaults.
    """
    rules: dict[str, Any]
    status: str = "success"
