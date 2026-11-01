from typing import Any
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.models.vehicle import ConnectorType


class VehicleCreateRequest(BaseModel):
    make: str = Field(..., min_length=1, max_length=40, description="Vehicle make (e.g. Tesla, Tata, Nissan)")
    model: str = Field(..., min_length=1, max_length=40, description="Vehicle model (e.g. Model 3, Nexon EV, Leaf)")
    battery_kwh: float = Field(..., ge=5.0, le=250.0, description="Battery capacity in kWh (5 to 250 kWh)")
    connector_type: ConnectorType = Field(..., description="Connector type (CCS2, CHAdeMO, Type 2, GB/T)")
    max_ac_kw: float = Field(..., ge=1.0, le=50.0, description="Maximum AC charging rate in kW (1 to 50 kW)")
    max_dc_kw: float = Field(default=0.0, ge=0.0, le=400.0, description="Maximum DC charging rate in kW (0 if none, or 10 to 400 kW)")
    consumption_kwh_100km: float = Field(..., ge=5.0, le=50.0, description="Energy consumption in kWh per 100 km (5 to 50 kWh/100km)")
    registration_no: str | None = Field(default=None, max_length=15, description="Optional vehicle registration number")
    is_default: bool = Field(default=False, description="Set as driver's default vehicle")

    @field_validator("make")
    @classmethod
    def validate_make(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Vehicle make cannot be empty or whitespace.")
        return trimmed

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Vehicle model cannot be empty or whitespace.")
        return trimmed

    @field_validator("registration_no")
    @classmethod
    def validate_registration_no(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip().upper()
        return trimmed if trimmed else None

    @field_validator("max_dc_kw")
    @classmethod
    def validate_max_dc_kw(cls, v: float) -> float:
        if 0.0 < v < 10.0:
            raise ValueError("Maximum DC power must be 0 kW (unsupported) or between 10 kW and 400 kW.")
        return v


class VehicleUpdateRequest(BaseModel):
    make: str | None = Field(default=None, min_length=1, max_length=40, description="Vehicle make (e.g. Tesla, Tata)")
    model: str | None = Field(default=None, min_length=1, max_length=40, description="Vehicle model (e.g. Model 3, Nexon EV)")
    battery_kwh: float | None = Field(default=None, ge=5.0, le=250.0, description="Battery capacity in kWh (5 to 250 kWh)")
    connector_type: ConnectorType | None = Field(default=None, description="Connector type (CCS2, CHAdeMO, Type 2, GB/T)")
    max_ac_kw: float | None = Field(default=None, ge=1.0, le=50.0, description="Maximum AC charging rate in kW (1 to 50 kW)")
    max_dc_kw: float | None = Field(default=None, ge=0.0, le=400.0, description="Maximum DC charging rate in kW (0 if none, or 10 to 400 kW)")
    consumption_kwh_100km: float | None = Field(default=None, ge=5.0, le=50.0, description="Energy consumption in kWh per 100 km (5 to 50 kWh/100km)")
    registration_no: str | None = Field(default=None, max_length=15, description="Optional vehicle registration number")
    is_default: bool | None = Field(default=None, description="Set as driver's default vehicle")

    @field_validator("make")
    @classmethod
    def validate_make(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Vehicle make cannot be empty or whitespace.")
        return trimmed

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Vehicle model cannot be empty or whitespace.")
        return trimmed

    @field_validator("registration_no")
    @classmethod
    def validate_registration_no(cls, v: str | None) -> str | None:
        if v is None:
            return None
        trimmed = v.strip().upper()
        return trimmed if trimmed else None

    @field_validator("max_dc_kw")
    @classmethod
    def validate_max_dc_kw(cls, v: float | None) -> float | None:
        if v is not None and 0.0 < v < 10.0:
            raise ValueError("Maximum DC power must be 0 kW (unsupported) or between 10 kW and 400 kW.")
        return v


class VehicleDeleteResponse(BaseModel):
    message: str
    vehicle_id: int
    status: str = "success"


class VehicleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    make: str
    model: str
    battery_kwh: float
    connector_type: ConnectorType
    max_ac_kw: float
    max_dc_kw: float
    consumption_kwh_100km: float
    registration_no: str | None = None
    is_default: bool
    created_at: datetime
    updated_at: datetime


class VehicleListResponse(BaseModel):
    total: int
    items: list[VehicleResponse]


# ==============================================================================
# Vehicle Validation Schemas (CS19-019 / REQ-F1-19 / REQ-F1-24)
# ==============================================================================

class VehicleValidationRulesResponse(BaseModel):
    rules: dict[str, Any]
    status: str = "success"


class VehicleValidationCheckRequest(BaseModel):
    make: str | None = None
    model: str | None = None
    battery_kwh: float | None = None
    connector_type: str | None = None
    max_ac_kw: float | None = None
    max_dc_kw: float | None = None
    consumption_kwh_100km: float | None = None
    registration_no: str | None = None


class VehicleValidationCheckResponse(BaseModel):
    is_valid: bool
    errors: dict[str, str] = {}
    message: str


# ==============================================================================
# Vehicle Summary Card Schemas (CS19-020 / REQ-F1-20)
# ==============================================================================

class VehicleSummaryCardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_id: int
    user_id: int
    make: str
    model: str
    display_title: str
    registration_no: str | None = None
    is_default: bool
    battery_kwh: float
    connector_type: ConnectorType
    connector_icon: str
    current_type: str
    max_ac_kw: float
    max_dc_kw: float
    fast_charging_support: bool
    consumption_kwh_100km: float
    estimated_range_km: float
    usable_range_km: float
    compatibility_badges: list[str]


class VehicleSummaryCardListResponse(BaseModel):
    total: int
    items: list[VehicleSummaryCardResponse]


# ==============================================================================
# Vehicle Limit & Default Schemas (CS19-022 / REQ-F1-22)
# ==============================================================================

class SetDefaultVehicleRequest(BaseModel):
    vehicle_id: int = Field(..., description="ID of the vehicle to set as primary default")


class VehicleLimitAndDefaultResponse(BaseModel):
    max_vehicles_allowed: int = 5
    current_vehicle_count: int
    can_add_more: bool
    default_vehicle_id: int | None = None
    default_vehicle: VehicleResponse | None = None
    message: str


class SetDefaultVehicleResponse(BaseModel):
    success: bool = True
    message: str
    default_vehicle: VehicleResponse

