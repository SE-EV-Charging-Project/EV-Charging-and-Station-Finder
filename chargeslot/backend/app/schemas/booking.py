"""
Booking Schemas (Feature 3: Battery-Aware Booking and Auto-Booking / CS19-055 / REQ-F3-01).
"""

import math
from datetime import date, datetime
from typing import Literal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


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
    auto_booking_suggested: bool = False
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


class EnergyEstimateRequest(BaseModel):
    """Request an energy estimate for an owned vehicle."""

    vehicle_id: int = Field(..., gt=0)
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)


class EnergyEstimateResponse(BaseModel):
    """Estimated battery energy required to reach the target state of charge."""

    vehicle_id: int
    current_soc: int
    target_soc: int
    battery_capacity_kwh: float
    energy_required_kwh: float
    message: str


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
    score: float | None = None
    available_factors: list[str] = Field(default_factory=list)
    unavailable_factors: list[str] = Field(default_factory=list)
    selection_reasons: list[str] = Field(default_factory=list)


class RecommendedSlotsResponse(BaseModel):
    """Ranked compatible slots for a vehicle and requested date."""

    total: int
    items: list[RecommendedSlotItem]


class AutoBookRequest(BaseModel):
    """Request an auto-booking suggestion or a temporary hold for a reachable slot."""

    vehicle_id: int = Field(..., gt=0)
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    slot_date: date
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)
    confirmation_mode: Literal["confirm_first", "book_immediately"] = "confirm_first"


class AutoBookResponse(BaseModel):
    """Best reachable slot, resulting hold if requested, or actionable alternatives."""

    status: Literal["suggested", "held", "no_slot", "configuration_required"]
    selected_slot: RecommendedSlotItem | None = None
    booking_id: int | None = None
    booking_status: str | None = None
    reservation_fee_amount: float | None = None
    hold_expires_at: datetime | None = None
    alternatives: list[RecommendedSlotItem] = Field(default_factory=list)
    unavailable_factors: list[str] = Field(default_factory=list)
    message: str


class BookingCheckinRequest(BaseModel):
    """Prove arrival with the signed booking QR or paired coordinates."""

    qr_code_payload: str | None = Field(default=None, min_length=1, max_length=500)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def require_one_checkin_method(self):
        has_qr = self.qr_code_payload is not None
        has_coordinates = self.latitude is not None and self.longitude is not None
        partial_coordinates = (self.latitude is None) != (self.longitude is None)
        if partial_coordinates or has_qr == has_coordinates:
            raise ValueError(
                "Provide either a QR code payload or both latitude and longitude."
            )
        return self


class BookingCheckinResponse(BaseModel):
    booking_id: int
    checked_in_at: datetime
    message: str


class RemoteStartRequest(BaseModel):
    """Request session start on the assigned connector or a compatible alternative."""

    connector_id: int | None = Field(default=None, gt=0)


class ManualSlotBookingRequest(BaseModel):
    """Request to book a specific available compatible slot."""

    station_id: int = Field(..., gt=0, strict=True)
    charger_id: int = Field(..., gt=0, strict=True)
    vehicle_id: int = Field(..., gt=0, strict=True)
    start_time: datetime
    target_soc: int = Field(default=80, ge=0, le=100, strict=True)


class ManualSlotBookingResponse(BaseModel):
    """Held manual booking, reservation fee, and the resulting charging estimate."""

    booking_id: int
    station_id: int
    charger_id: int
    vehicle_id: int
    start_soc: int
    target_soc: int
    energy_required_kwh: float
    estimated_charging_time_minutes: float
    slot_length_minutes: int
    reservation_fee_amount: float
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
    reservation_fee_amount: float
    hold_expires_at: datetime


class PaymentConfirmationWebhookRequest(BaseModel):
    """Verified payment-provider event for a held booking reservation fee."""

    provider_event_id: str = Field(..., min_length=1, max_length=120)
    provider_reference: str | None = Field(default=None, max_length=120)
    amount_inr: float = Field(..., ge=0, allow_inf_nan=False)
    currency: Literal["INR"] = "INR"
    status: Literal["Succeeded", "Failed"]


class PaymentConfirmationResponse(BaseModel):
    """Result of recording a provider-verified reservation payment event."""

    booking_id: int
    booking_status: str
    payment_status: str
    reservation_fee_amount: float
    booking_reference: str | None = None
    qr_code_payload: str | None = None
    refund_due_amount: float = 0.0
    message: str


class BookingModificationRequest(BaseModel):
    """Request to move a confirmed booking to another compatible slot."""

    charger_id: int = Field(..., gt=0, strict=True)
    start_time: datetime


class BookingModificationResponse(BaseModel):
    """Confirmed booking after its charger or time has been changed."""

    booking_id: int
    station_id: int
    charger_id: int
    vehicle_id: int
    start_time: datetime
    end_time: datetime
    status: str


class BookingCancellationResponse(BaseModel):
    """Cancellation result and any late cancellation fee due."""

    booking_id: int
    status: str
    cancellation_fee_amount: float
    currency: str = "INR"
    is_late_cancellation: bool
    message: str
