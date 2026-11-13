"""
Booking Schemas (Feature 3: Battery-Aware Booking and Auto-Booking / CS19-055 / REQ-F3-01).
"""

import math
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
        if isinstance(v, bool):
            raise ValueError("Battery level must be an integer between 0% and 100%.")
        try:
            numeric_val = float(v)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Battery level must be numeric, got: {v!r}.")
        if not math.isfinite(numeric_val) or not numeric_val.is_integer():
            raise ValueError("Battery level must be an integer between 0% and 100%.")
        if numeric_val < 0.0 or numeric_val > 100.0:
            raise ValueError(f"Battery level must be between 0% and 100%, got {numeric_val}%.")
        return int(numeric_val)

    @field_validator("target_soc", mode="before")
    @classmethod
    def validate_target_soc(cls, v: Any) -> int | None:
        if v is None:
            return 80
        if isinstance(v, bool):
            raise ValueError("Target battery level must be an integer between 0% and 100%.")
        try:
            numeric_val = float(v)
        except (ValueError, TypeError, OverflowError):
            raise ValueError(f"Target battery level must be numeric, got: {v!r}.")
        if not math.isfinite(numeric_val) or not numeric_val.is_integer():
            raise ValueError("Target battery level must be an integer between 0% and 100%.")
        if numeric_val < 0.0 or numeric_val > 100.0:
            raise ValueError(f"Target battery level must be between 0% and 100%, got {numeric_val}%.")
        return int(numeric_val)


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


class ChargingTimeEstimateRequest(BaseModel):
    """Request a charging-time estimate for an owned vehicle and a charger."""

    vehicle_id: int = Field(..., gt=0)
    charger_id: int = Field(..., gt=0)
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)


class ChargingTimeEstimateResponse(BaseModel):
    """Estimated charge energy, effective power, and charging duration."""

    vehicle_id: int
    charger_id: int
    current_soc: int
    target_soc: int
    energy_required_kwh: float
    effective_charging_power_kw: float
    estimated_charging_time_minutes: float
    slot_length_minutes: int
    message: str


class ChargingCostEstimateRequest(BaseModel):
    """Request a tariff-based estimate for charging an owned vehicle."""

    vehicle_id: int = Field(..., gt=0)
    station_id: int = Field(..., gt=0)
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)


class ChargingCostEstimateResponse(BaseModel):
    """Estimated energy, station tariff, and charging cost."""

    vehicle_id: int
    station_id: int
    current_soc: int
    target_soc: int
    energy_required_kwh: float
    price_per_kwh: float
    estimated_cost: float
    currency: str = "INR"
    message: str


class RecommendedSlotItem(BaseModel):
    """A compatible, available slot with its stable recommendation rank."""

    rank: int
    station_id: int
    station_name: str
    charger_id: int
    start_time: datetime
    end_time: datetime
    energy_required_kwh: float
    estimated_charging_time_minutes: float
    slot_length_minutes: int
    price_per_kwh: float | None
    estimated_cost: float | None


class RecommendedSlotsResponse(BaseModel):
    """Ranked compatible slots for a vehicle and requested date."""

    total: int
    items: list[RecommendedSlotItem]


class ManualSlotBookingRequest(BaseModel):
    """Request to book a specific available compatible slot."""

    station_id: int = Field(..., gt=0, strict=True)
    charger_id: int = Field(..., gt=0, strict=True)
    vehicle_id: int = Field(..., gt=0, strict=True)
    start_time: datetime
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)


class ManualSlotBookingResponse(BaseModel):
    """Confirmed manual booking and the resulting charging estimate."""

    booking_id: int
    station_id: int
    charger_id: int
    vehicle_id: int
    start_soc: int
    target_soc: int
    energy_required_kwh: float
    estimated_charging_time_minutes: float
    slot_length_minutes: int
    start_time: datetime
    end_time: datetime
    status: str


class SlotHoldResponse(BaseModel):
    """Temporary slot hold while payment is being processed."""

    booking_id: int
    station_id: int
    charger_id: int
    vehicle_id: int
    start_time: datetime
    end_time: datetime
    status: str
    hold_expires_at: datetime
