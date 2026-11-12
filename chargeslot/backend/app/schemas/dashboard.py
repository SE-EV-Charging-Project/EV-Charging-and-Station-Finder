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
    last_status_update: datetime | None = None
    retrieved_at: datetime
    connectors: list[ConnectorLiveStatusItem] = Field(default_factory=list)

