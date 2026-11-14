from datetime import datetime
from pydantic import BaseModel, Field, EmailStr, ConfigDict, field_validator
from app.models.station import StationStatus


class StationCreateRequest(BaseModel):
    """
    Payload for creating a new Station (CS19-027 / REQ-F2-01 / Appendix B.4).
    """
    name: str = Field(..., min_length=1, max_length=100, description="Station name")
    address: str = Field(..., min_length=1, max_length=200, description="Street address")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="Latitude in decimal degrees [-90, 90]")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="Longitude in decimal degrees [-180, 180]")
    amenities: list[str] = Field(default_factory=list, description="Available amenities e.g. restroom, cafe, parking, wifi")
    operating_hours: str = Field(default="24 hours", min_length=1, max_length=100, description="Operating hours e.g. '24 hours' or '08:00-22:00'")
    contact_phone: str = Field(..., min_length=5, max_length=20, description="Station contact phone number")
    contact_email: EmailStr | None = Field(default=None, description="Optional contact email")
    price_per_kwh: float | None = Field(default=None, ge=0.0, description="Tariff price per kWh in INR")

    @field_validator("name", "address", "operating_hours", "contact_phone")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Field cannot be empty or only whitespace")
        return s


class StationUpdateRequest(BaseModel):
    """
    Payload for editing an existing Station (CS19-027 / REQ-F2-01).
    """
    name: str | None = Field(default=None, min_length=1, max_length=100)
    address: str | None = Field(default=None, min_length=1, max_length=200)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    amenities: list[str] | None = None
    operating_hours: str | None = Field(default=None, min_length=1, max_length=100)
    contact_phone: str | None = Field(default=None, min_length=5, max_length=20)
    contact_email: EmailStr | None = None
    price_per_kwh: float | None = Field(default=None, ge=0.0)
    is_active: bool | None = None

    @field_validator("name", "address", "operating_hours", "contact_phone")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be empty or only whitespace")
            return s
        return v


class StationResponse(BaseModel):
    """
    Response model for station data.
    """
    id: int
    operator_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    amenities: list[str]
    operating_hours: str
    contact_phone: str
    contact_email: str | None
    price_per_kwh: float | None = None
    status: StationStatus
    is_active: bool
    rejection_reason: str | None = None
    reviewed_by_admin_id: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StationListResponse(BaseModel):
    """
    Paginated list of stations.
    """
    items: list[StationResponse]
    total: int
    page: int
    page_size: int


class StationDeactivateResponse(BaseModel):
    """
    Response model when a station is deactivated.
    """
    message: str
    station_id: int
    is_active: bool
    status: StationStatus


class StationValidationRulesResponse(BaseModel):
    """
    Response model for Appendix B.4 validation constraints (REQ-F2-04 / CS19-030).
    """
    station_rules: dict
    charger_rules: dict


class StationValidationCheckRequest(BaseModel):
    """
    Payload for dry-run station validation check without database mutation.
    """
    data: dict
    partial: bool = False


class StationValidationCheckResponse(BaseModel):
    """
    Response for dry-run station validation check.
    """
    valid: bool
    errors: dict[str, str]
    message: str


class ChargerValidationCheckRequest(BaseModel):
    """
    Payload for dry-run charger validation check without database mutation.
    """
    data: dict
    partial: bool = False


class ChargerValidationCheckResponse(BaseModel):
    """
    Response for dry-run charger validation check.
    """
    valid: bool
    errors: dict[str, str]
    message: str


class StationRejectRequest(BaseModel):
    """
    Payload for rejecting a station (REQ-F2-03 / CS19-029).
    """
    reason: str = Field(..., min_length=3, max_length=500, description="Reason for rejection")

    @field_validator("reason")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("Rejection reason cannot be empty")
        return s


class StationApprovalResponse(BaseModel):
    """
    Response for station approval/rejection moderation actions.
    """
    id: int
    name: str
    status: StationStatus
    is_active: bool
    rejection_reason: str | None = None
    reviewed_by_admin_id: int | None = None
    reviewed_at: datetime | None = None
    message: str

    model_config = ConfigDict(from_attributes=True)


class StationApprovalGateStatusResponse(BaseModel):
    """
    Status payload for SW Architecture route GET /api/v1/stations/station-approval-gate.
    """
    station_id: int
    station_name: str
    status: StationStatus
    is_active: bool
    visible_to_drivers: bool
    can_approve: bool
    rejection_reason: str | None = None
    reviewed_by_admin_id: int | None = None
    reviewed_at: datetime | None = None


class StationApprovalGateActionRequest(BaseModel):
    """
    Payload for SW Architecture route POST /api/v1/stations/station-approval-gate.
    """
    station_id: int
    action: str = Field(..., description="Action to perform: 'approve' or 'reject'")
    reason: str | None = Field(default=None, max_length=500, description="Rejection reason if action is 'reject'")


class BookableSlotItem(BaseModel):
    """
    Represents an individual 15-minute bookable slot on a connector (REQ-F2-22 / CS19-048).
    """
    slot_id: str = Field(..., description="Unique deterministic slot identifier")
    station_id: int
    charger_id: int
    charger_name: str | None = None
    connector_id: int
    connector_type: str
    power_kw: float
    current_type: str
    start_time: datetime
    end_time: datetime
    duration_minutes: int = 15
    is_available: bool
    is_bookable: bool
    is_booked: bool = False
    is_maintenance: bool = False
    is_past: bool = False
    blocked_reason: str | None = None
    booking_id: int | None = None
    booking_status: str | None = None


class ConnectorSlotsSummary(BaseModel):
    """
    Aggregated 15-minute slot schedule and metrics for a single connector (REQ-F2-22).
    """
    connector_id: int
    connector_type: str
    charger_id: int
    charger_name: str | None = None
    power_kw: float
    current_type: str
    is_operational: bool
    total_slots: int
    available_slots: int
    booked_slots: int
    blocked_slots: int
    slots: list[BookableSlotItem] = Field(default_factory=list)


class StationBookableSlotsResponse(BaseModel):
    """
    Generated bookable 15-minute slots for every connector up to 7 days ahead
    (REQ-F2-22 / CS19-048 / SW Architecture route /stations/slot-generation).
    """
    station_id: int
    station_name: str
    operating_hours: str
    slot_interval_minutes: int = 15
    days_ahead: int
    start_date: datetime | str
    end_date: datetime | str
    total_connectors: int
    total_slots: int
    total_available_slots: int
    total_booked_slots: int
    total_blocked_slots: int
    connectors: list[ConnectorSlotsSummary] = Field(default_factory=list)
    generated_at: datetime


# Re-export slot timeline schemas (REQ-F2-23 / CS19-049)
from app.schemas.dashboard import (
    TimelineSlotState,
    TimelineSlotItem,
    ConnectorTimelineSummary,
    StationSlotTimelineResponse,
)




