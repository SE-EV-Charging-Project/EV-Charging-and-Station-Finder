from datetime import date, datetime
from fastapi import APIRouter, Depends, Path, Query, WebSocket, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.dashboard.realtime import station_status_websocket_handler
from app.dashboard.staleness import (
    DEFAULT_STALE_THRESHOLD_SECONDS,
    get_stale_connector_status_display,
)
from app.dashboard.views import (
    get_live_connector_status_display,
    get_live_session_monitor,
)
from app.dashboard.state import (
    DEFAULT_RESERVATION_WINDOW_MINUTES,
    get_reserved_status_display,
)
from app.dashboard.timeline import get_station_slot_timeline
from app.dashboard.wait import get_station_estimated_wait_time
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    EstimatedWaitTimeResponse,
    LiveConnectorStatusDisplayResponse,
    LiveSessionMonitorResponse,
    ReservedStatusResponse,
    StaleStatusHandlingResponse,
    StationSlotTimelineResponse,
)

router = APIRouter(tags=["Live Status Dashboard"])
ws_router = APIRouter(tags=["Live Status Dashboard WebSocket"])


@router.get(
    "/bookings/{booking_id}/live-monitor",
    response_model=LiveSessionMonitorResponse,
    status_code=status.HTTP_200_OK,
    summary="Get meter-backed live charging session metrics",
    description=(
        "Returns live power, session energy, estimated SoC, elapsed time, and estimated cost. "
        "Clients should refresh every 30 seconds (REQ-F3-29)."
    ),
)
def display_live_session_monitor(
    booking_id: int = Path(..., gt=0, description="Active booking ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiveSessionMonitorResponse:
    return get_live_session_monitor(db=db, user=current_user, booking_id=booking_id)


@router.get(
    "/stations/live-status-display",
    response_model=LiveConnectorStatusDisplayResponse,
    status_code=status.HTTP_200_OK,
    summary="Display live connector status and last update time (SW Architecture Route)",
    description=(
        "Returns each connector's current status and time of last update for a station "
        "or specific connector (REQ-F2-18 / CS19-044)."
    ),
)
def display_live_connector_status(
    station_id: int | None = Query(default=None, description="Target station ID"),
    connector_id: int | None = Query(default=None, description="Optional specific connector ID"),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Optional status filter: Available, Occupied, Reserved, Faulted, Offline",
    ),
    apply_stale_fallback: bool = Query(
        default=False,
        description="When true, replaces >120s stale statuses with 'Status unknown' (REQ-F2-20)",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiveConnectorStatusDisplayResponse:
    return get_live_connector_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        status_filter=status_filter,
        apply_stale_fallback=apply_stale_fallback,
    )


@router.get(
    "/stations/stale-status-handling",
    response_model=StaleStatusHandlingResponse,
    status_code=status.HTTP_200_OK,
    summary="Display connector statuses with >120s 'Status unknown' fallback (SW Architecture Route)",
    description=(
        "Evaluates telemetry freshness for connectors at a station or specific connector and "
        "displays 'Status unknown' whenever no update has been received for more than 120 seconds "
        "(REQ-F2-20 / CS19-046)."
    ),
)
def display_stale_connector_status(
    station_id: int | None = Query(default=None, description="Target station ID"),
    connector_id: int | None = Query(default=None, description="Optional specific connector ID"),
    stale_threshold_seconds: int = Query(
        default=DEFAULT_STALE_THRESHOLD_SECONDS,
        description="Max telemetry age in seconds before reporting 'Status unknown' (default 120s)",
    ),
    stale_only: bool = Query(
        default=False,
        description="Filter returned list to stale connectors only",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StaleStatusHandlingResponse:
    return get_stale_connector_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        stale_threshold_seconds=stale_threshold_seconds,
        stale_only=stale_only,
    )


@router.get(
    "/stations/reserved-status",
    response_model=ReservedStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Display connector reserved status for confirmed bookings starting within 15 minutes (SW Architecture Route)",
    description=(
        "Evaluates confirmed bookings starting within the next 15 minutes and displays "
        "Reserved status for affected connectors (REQ-F2-21 / CS19-047)."
    ),
)
def display_reserved_connector_status(
    station_id: int | None = Query(default=None, description="Target station ID"),
    connector_id: int | None = Query(default=None, description="Optional specific connector ID"),
    window_minutes: int = Query(
        default=DEFAULT_RESERVATION_WINDOW_MINUTES,
        ge=1,
        le=120,
        description="Upcoming booking buffer in minutes to evaluate Reserved status (default 15m per REQ-F2-21)",
    ),
    reserved_only: bool = Query(
        default=False,
        description="Filter returned list to reserved connectors only",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservedStatusResponse:
    return get_reserved_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        window_minutes=window_minutes,
        reserved_only=reserved_only,
    )


@router.get(
    "/stations/{station_id}/reserved-status",
    response_model=ReservedStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Display connector reserved status for a station",
    description="Path alias returning connector reserved status for a station (REQ-F2-21).",
)
def display_station_reserved_status(
    station_id: int = Path(..., description="Target station ID"),
    window_minutes: int = Query(
        default=DEFAULT_RESERVATION_WINDOW_MINUTES,
        ge=1,
        le=120,
        description="Upcoming booking buffer in minutes (default 15m)",
    ),
    reserved_only: bool = Query(default=False, description="Filter to reserved connectors only"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservedStatusResponse:
    return get_reserved_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        window_minutes=window_minutes,
        reserved_only=reserved_only,
    )


@router.get(
    "/connectors/{connector_id}/reserved-status",
    response_model=ReservedStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Display reserved status for a single connector",
    description="Path alias returning reserved status for one connector (REQ-F2-21).",
)
def display_single_connector_reserved_status(
    connector_id: int = Path(..., description="Target connector ID"),
    window_minutes: int = Query(
        default=DEFAULT_RESERVATION_WINDOW_MINUTES,
        ge=1,
        le=120,
        description="Upcoming booking buffer in minutes (default 15m)",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservedStatusResponse:
    return get_reserved_status_display(
        db=db,
        user=current_user,
        connector_id=connector_id,
        window_minutes=window_minutes,
    )


@router.get(
    "/stations/{station_id}/chargers/{charger_id}/connectors/{connector_id}/reserved-status",
    response_model=ReservedStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Nested path alias to display reserved status for a specific connector",
    description="Nested REST path alias to evaluate connector reserved status (REQ-F2-21).",
)
def display_nested_connector_reserved_status(
    station_id: int = Path(..., description="Target station ID"),
    charger_id: int = Path(..., description="Target charger ID"),
    connector_id: int = Path(..., description="Target connector ID"),
    window_minutes: int = Query(
        default=DEFAULT_RESERVATION_WINDOW_MINUTES,
        ge=1,
        le=120,
        description="Upcoming booking buffer in minutes (default 15m)",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ReservedStatusResponse:
    return get_reserved_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        window_minutes=window_minutes,
    )


@router.get(
    "/stations/{station_id}/live-status",
    response_model=LiveConnectorStatusDisplayResponse,
    status_code=status.HTTP_200_OK,
    summary="Display live connector statuses for a station",
    description="Path alias returning live connector statuses and timestamps for a station (REQ-F2-18).",
)
def display_station_live_status(
    station_id: int = Path(..., description="Target station ID"),
    status_filter: str | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiveConnectorStatusDisplayResponse:
    return get_live_connector_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        status_filter=status_filter,
    )


@router.get(
    "/connectors/{connector_id}/live-status",
    response_model=LiveConnectorStatusDisplayResponse,
    status_code=status.HTTP_200_OK,
    summary="Display live status for a single connector",
    description="Path alias returning live status and time of last update for one connector (REQ-F2-18).",
)
def display_single_connector_live_status(
    connector_id: int = Path(..., description="Target connector ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiveConnectorStatusDisplayResponse:
    return get_live_connector_status_display(
        db=db,
        user=current_user,
        connector_id=connector_id,
    )


# ---------------------------------------------------------------------------
# Slot Timeline Endpoints (REQ-F2-23 / CS19-049)
# ---------------------------------------------------------------------------


@router.get(
    "/stations/slot-timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline per connector (SW Architecture Route)",
    description=(
        "Displays, for a selected station and date, a slot timeline per connector in which "
        "each 15-minute slot is shown as Free, Booked, Blocked or Past (REQ-F2-23 / CS19-049)."
    ),
)
def display_station_slot_timeline(
    station_id: int | None = Query(default=None, description="Target station ID"),
    connector_id: int | None = Query(default=None, description="Optional specific connector ID"),
    target_date: date | None = Query(default=None, description="Target date (YYYY-MM-DD), defaults to today"),
    status: str | None = Query(default=None, description="Filter slots by status: Free, Booked, Blocked, Past"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationSlotTimelineResponse:
    return get_station_slot_timeline(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        target_date=target_date,
        status_filter=status,
    )


@router.get(
    "/stations/{station_id}/slot-timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline for a station by path",
    description="Path route displaying slot timeline for a station and date (REQ-F2-23).",
)
@router.get(
    "/stations/{station_id}/timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline (short path alias)",
    description="Path alias displaying slot timeline for a station and date (REQ-F2-23).",
)
def display_station_slot_timeline_by_path(
    station_id: int = Path(..., description="Target station ID"),
    target_date: date | None = Query(default=None, description="Target date (YYYY-MM-DD), defaults to today"),
    status: str | None = Query(default=None, description="Filter slots by status: Free, Booked, Blocked, Past"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationSlotTimelineResponse:
    return get_station_slot_timeline(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=None,
        target_date=target_date,
        status_filter=status,
    )


@router.get(
    "/stations/{station_id}/connectors/{connector_id}/timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline for a single connector",
    description="Path route displaying slot timeline for a single connector and date (REQ-F2-23).",
)
def display_connector_slot_timeline_by_path(
    station_id: int = Path(..., description="Target station ID"),
    connector_id: int = Path(..., description="Target connector ID"),
    target_date: date | None = Query(default=None, description="Target date (YYYY-MM-DD), defaults to today"),
    status: str | None = Query(default=None, description="Filter slots by status: Free, Booked, Blocked, Past"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationSlotTimelineResponse:
    return get_station_slot_timeline(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        target_date=target_date,
        status_filter=status,
    )


# ---------------------------------------------------------------------------
# Estimated Wait Time Endpoints (REQ-F2-24 / CS19-050)
# ---------------------------------------------------------------------------


@router.get(
    "/stations/estimated-wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time for station (SW Architecture Route)",
    description=(
        "Displays estimated wait time when all compatible connectors at a station are occupied, "
        "calculated from the expected end of active sessions (REQ-F2-24 / CS19-050)."
    ),
)
def display_estimated_wait_time(
    station_id: int = Query(..., description="Target station ID"),
    vehicle_id: int | None = Query(default=None, description="Optional vehicle ID to evaluate connector compatibility"),
    connector_type: str | None = Query(default=None, description="Optional connector type filter (e.g. CCS2, Type 2, CHAdeMO, GB/T)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EstimatedWaitTimeResponse:
    return get_station_estimated_wait_time(
        db=db,
        user=current_user,
        station_id=station_id,
        vehicle_id=vehicle_id,
        connector_type=connector_type,
    )


@router.get(
    "/stations/{station_id}/estimated-wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time for station by path",
    description="Path route displaying estimated wait time when all compatible connectors are occupied (REQ-F2-24).",
)
@router.get(
    "/stations/{station_id}/wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time (short path alias)",
    description="Short path alias displaying estimated wait time for a station (REQ-F2-24).",
)
def display_station_estimated_wait_time_by_path(
    station_id: int = Path(..., description="Target station ID"),
    vehicle_id: int | None = Query(default=None, description="Optional vehicle ID to evaluate connector compatibility"),
    connector_type: str | None = Query(default=None, description="Optional connector type filter"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> EstimatedWaitTimeResponse:
    return get_station_estimated_wait_time(
        db=db,
        user=current_user,
        station_id=station_id,
        vehicle_id=vehicle_id,
        connector_type=connector_type,
    )


@ws_router.websocket("/ws/stations/status")
async def stream_station_status_updates(
    websocket: WebSocket,
    station_id: int | None = Query(default=None, description="Subscribed station ID"),
    token: str | None = Query(default=None, description="JWT access token"),
    db: Session = Depends(get_db),
) -> None:
    """
    Push live connector status changes over WebSocket to every open station
    dashboard (REQ-F2-19 / CS19-045 / SW Architecture Page 6).
    """
    await station_status_websocket_handler(
        websocket=websocket,
        station_id=station_id,
        db=db,
        token=token,
    )


@ws_router.websocket("/ws/stations/{station_id}/status")
async def stream_station_status_updates_by_path(
    websocket: WebSocket,
    station_id: int = Path(..., description="Subscribed station ID"),
    token: str | None = Query(default=None, description="JWT access token"),
    db: Session = Depends(get_db),
) -> None:
    """Path alias for live connector status push channel (REQ-F2-19)."""
    await station_status_websocket_handler(
        websocket=websocket,
        station_id=station_id,
        db=db,
        token=token,
    )

