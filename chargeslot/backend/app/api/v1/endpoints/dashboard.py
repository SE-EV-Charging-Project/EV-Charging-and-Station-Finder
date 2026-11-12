from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.dashboard.views import get_live_connector_status_display
from app.db.session import get_db
from app.models.user import User
from app.schemas.dashboard import LiveConnectorStatusDisplayResponse

router = APIRouter(tags=["Live Status Dashboard"])


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
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> LiveConnectorStatusDisplayResponse:
    return get_live_connector_status_display(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        status_filter=status_filter,
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

