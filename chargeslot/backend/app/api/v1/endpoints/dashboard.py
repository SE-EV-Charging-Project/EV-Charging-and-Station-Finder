from fastapi import APIRouter, Depends, Path, Query, WebSocket, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.dashboard.realtime import station_status_websocket_handler
from app.dashboard.staleness import (
    DEFAULT_STALE_THRESHOLD_SECONDS,
    get_stale_connector_status_display,
)
from app.dashboard.views import get_live_connector_status_display
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import (
    LiveConnectorStatusDisplayResponse,
    StaleStatusHandlingResponse,
)

router = APIRouter(tags=["Live Status Dashboard"])
ws_router = APIRouter(tags=["Live Status Dashboard WebSocket"])


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

