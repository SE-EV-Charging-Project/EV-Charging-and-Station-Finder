from datetime import datetime
from pydantic import BaseModel, Field

from app.schemas.discovery import StationAvailabilityMarker


class ConnectorLiveStatusItem(BaseModel):
    """
    Live connector telemetry status and last update timestamp for dashboard display
    (REQ-F2-18 / CS19-044).
    """

    connector_id: int
    charger_id: int
    charger_name: str | None = None
    station_id: int
    station_name: str
    gateway_id: str
    connector_type: str
    power_kw: float
    current_type: str
    status: str
    is_stale: bool = False
    last_update: datetime
    seconds_since_update: int
    is_active: bool
    is_out_of_service: bool
    out_of_service_reason: str | None = None
    expected_return_time: datetime | None = None
    latest_error_code: str | None = None


class LiveConnectorStatusDisplayResponse(BaseModel):
    """
    Live connector status display payload for a charging station or connector
    (REQ-F2-18 / CS19-044).
    """

    station_id: int
    station_name: str
    station_status: str
    is_active: bool
    availability_summary: StationAvailabilityMarker
    total_connectors: int
    available_connectors: int
    occupied_connectors: int
    reserved_connectors: int
    faulted_connectors: int
    offline_connectors: int
    unknown_connectors: int = 0
    last_status_update: datetime | None = None
    retrieved_at: datetime
    connectors: list[ConnectorLiveStatusItem] = Field(default_factory=list)


class StaleConnectorStatusItem(BaseModel):
    """
    Connector status representation with >120s staleness fallback
    ('Status unknown') per REQ-F2-20 / CS19-046.
    """

    connector_id: int
    charger_id: int
    charger_name: str | None = None
    station_id: int
    station_name: str
    gateway_id: str
    connector_type: str
    power_kw: float
    current_type: str
    status: str
    is_stale: bool
    status_reason: str
    last_update: datetime | None = None
    seconds_since_update: int
    stale_threshold_seconds: int
    is_active: bool
    is_out_of_service: bool


class StaleStatusHandlingResponse(BaseModel):
    """
    Station or connector staleness evaluation summary replacing stale connector
    statuses with 'Status unknown' (REQ-F2-20 / CS19-046).
    """

    station_id: int
    station_name: str
    station_status: str
    is_active: bool
    stale_threshold_seconds: int
    status_unknown_label: str
    total_connectors: int
    fresh_connectors: int
    stale_connectors: int
    unknown_status_connectors: int
    last_status_update: datetime | None = None
    evaluated_at: datetime
    connectors: list[StaleConnectorStatusItem] = Field(default_factory=list)


class ReservedConnectorStatusItem(BaseModel):
    """
    Connector status item reflecting reserved status when an active confirmed booking
    starts within 15 minutes (REQ-F2-21 / CS19-047).
    """

    connector_id: int
    charger_id: int
    charger_name: str | None = None
    station_id: int
    station_name: str
    gateway_id: str
    connector_type: str
    power_kw: float
    current_type: str
    raw_status: str
    status: str
    is_reserved: bool
    reservation_window_minutes: int
    booking_id: int | None = None
    booking_user_id: int | None = None
    booking_vehicle_id: int | None = None
    booking_start_time: datetime | None = None
    booking_end_time: datetime | None = None
    minutes_until_booking: float | None = None
    last_update: datetime | None = None
    seconds_since_update: int = 0
    is_active: bool
    is_out_of_service: bool
    out_of_service_reason: str | None = None
    expected_return_time: datetime | None = None
    latest_error_code: str | None = None


class ReservedStatusResponse(BaseModel):
    """
    Station or connector reserved status summary evaluating confirmed bookings
    starting within 15 minutes (REQ-F2-21 / CS19-047).
    """

    station_id: int
    station_name: str
    station_status: str
    is_active: bool
    reservation_window_minutes: int
    total_connectors: int
    reserved_connectors: int
    available_connectors: int
    occupied_connectors: int
    faulted_connectors: int
    offline_connectors: int
    unknown_connectors: int = 0
    last_status_update: datetime | None = None
    evaluated_at: datetime
    connectors: list[ReservedConnectorStatusItem] = Field(default_factory=list)


