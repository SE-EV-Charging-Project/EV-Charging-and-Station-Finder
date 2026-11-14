"""
Navigation API Endpoints (REQ-F2-25, REQ-F2-26, REQ-F2-27).

Covers:
- Route preview from driver location to destination station (REQ-F2-25 / CS19-051).
- Turn-by-turn navigation hand-off via deep links (REQ-F2-26 / CS19-052).
- Driver ETA versus slot start comparison and warning/reschedule options (REQ-F2-27 / CS19-053).
"""

from datetime import datetime
from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.navigation.eta import (
    DEFAULT_GRACE_PERIOD_MINUTES,
    check_driver_eta_versus_slot,
)
from app.navigation.handoff import generate_navigation_handoff
from app.navigation.routes import calculate_route_preview
from app.schemas.navigation import (
    ETASlotCheckResponse,
    NavigationHandoffResponse,
    RoutePreviewResponse,
)

router = APIRouter(prefix="/navigation", tags=["Navigation"])


# ---------------------------------------------------------------------------
# Route Preview Endpoints (REQ-F2-25 / CS19-051)
# ---------------------------------------------------------------------------


@router.get(
    "/route-preview",
    response_model=RoutePreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get route preview to charging station (REQ-F2-25 / CS19-051)",
    description=(
        "Displays a route preview from the driver's current coordinates to a station, "
        "including road distance and estimated travel time with current traffic (REQ-F2-25)."
    ),
)
@router.get(
    "/preview",
    response_model=RoutePreviewResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_navigation_route_preview(
    station_id: int = Query(..., description="Target station ID"),
    latitude: float = Query(..., description="Driver origin latitude [-90.0, 90.0]"),
    longitude: float = Query(..., description="Driver origin longitude [-180.0, 180.0]"),
    traffic_condition: str | None = Query(
        default=None,
        description="Optional traffic condition: low, normal, heavy, severe",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoutePreviewResponse:
    return calculate_route_preview(
        db=db,
        user=current_user,
        station_id=station_id,
        origin_latitude=latitude,
        origin_longitude=longitude,
        traffic_condition=traffic_condition,
    )


@router.get(
    "/{station_id}/route-preview",
    response_model=RoutePreviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get route preview to charging station by path ID (REQ-F2-25)",
    description="Path-based route preview endpoint for a destination station.",
)
@router.get(
    "/{station_id}/preview",
    response_model=RoutePreviewResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_navigation_route_preview_by_id(
    station_id: int = Path(..., description="Target station ID"),
    latitude: float = Query(..., description="Driver origin latitude [-90.0, 90.0]"),
    longitude: float = Query(..., description="Driver origin longitude [-180.0, 180.0]"),
    traffic_condition: str | None = Query(
        default=None,
        description="Optional traffic condition: low, normal, heavy, severe",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RoutePreviewResponse:
    return calculate_route_preview(
        db=db,
        user=current_user,
        station_id=station_id,
        origin_latitude=latitude,
        origin_longitude=longitude,
        traffic_condition=traffic_condition,
    )


# ---------------------------------------------------------------------------
# Navigation Hand-off Endpoints (REQ-F2-26 / CS19-052)
# ---------------------------------------------------------------------------


@router.get(
    "/navigation-hand-off",
    response_model=NavigationHandoffResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate navigation deep links to station (REQ-F2-26 / CS19-052)",
    description=(
        "Allows driver to start turn-by-turn navigation in external navigation apps "
        "through deep links (Google Maps, Apple Maps, Waze, and geo: URI) (REQ-F2-26)."
    ),
)
@router.get(
    "/handoff",
    response_model=NavigationHandoffResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_navigation_handoff(
    station_id: int = Query(..., description="Target station ID"),
    app_type: str | None = Query(
        default=None,
        description="Optional app type: google_maps, apple_maps, waze, generic_geo",
    ),
    origin_latitude: float | None = Query(
        default=None,
        description="Optional origin latitude [-90.0, 90.0]",
    ),
    origin_longitude: float | None = Query(
        default=None,
        description="Optional origin longitude [-180.0, 180.0]",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NavigationHandoffResponse:
    return generate_navigation_handoff(
        db=db,
        user=current_user,
        station_id=station_id,
        app_type=app_type,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
    )


@router.get(
    "/{station_id}/navigation-hand-off",
    response_model=NavigationHandoffResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate navigation deep links to station by path ID (REQ-F2-26)",
    description="Path-based navigation hand-off deep link endpoint.",
)
@router.get(
    "/{station_id}/handoff",
    response_model=NavigationHandoffResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_navigation_handoff_by_id(
    station_id: int = Path(..., description="Target station ID"),
    app_type: str | None = Query(
        default=None,
        description="Optional app type: google_maps, apple_maps, waze, generic_geo",
    ),
    origin_latitude: float | None = Query(
        default=None,
        description="Optional origin latitude [-90.0, 90.0]",
    ),
    origin_longitude: float | None = Query(
        default=None,
        description="Optional origin longitude [-180.0, 180.0]",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NavigationHandoffResponse:
    return generate_navigation_handoff(
        db=db,
        user=current_user,
        station_id=station_id,
        app_type=app_type,
        origin_latitude=origin_latitude,
        origin_longitude=origin_longitude,
    )


# ---------------------------------------------------------------------------
# ETA versus Slot Check Endpoints (REQ-F2-27 / CS19-053)
# ---------------------------------------------------------------------------


@router.get(
    "/eta-versus-slot-check",
    response_model=ETASlotCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Compare driver ETA with slot start time (REQ-F2-27 / CS19-053)",
    description=(
        "Compares the driver's estimated arrival time with the slot start time for a confirmed booking. "
        "Warns the driver and offers reschedule, extend, or cancel options when projected late (REQ-F2-27)."
    ),
)
@router.get(
    "/eta-check",
    response_model=ETASlotCheckResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def get_eta_slot_check(
    booking_id: int = Query(..., description="Target booking ID"),
    latitude: float = Query(..., description="Driver origin latitude [-90.0, 90.0]"),
    longitude: float = Query(..., description="Driver origin longitude [-180.0, 180.0]"),
    traffic_condition: str | None = Query(
        default=None,
        description="Optional traffic condition: low, normal, heavy, severe",
    ),
    grace_period_minutes: int = Query(
        default=DEFAULT_GRACE_PERIOD_MINUTES,
        ge=0,
        description="Grace period in minutes (default 15 per BR-06)",
    ),
    current_time: datetime | None = Query(
        default=None,
        description="Optional evaluation timestamp",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ETASlotCheckResponse:
    return check_driver_eta_versus_slot(
        db=db,
        user=current_user,
        booking_id=booking_id,
        driver_latitude=latitude,
        driver_longitude=longitude,
        traffic_condition=traffic_condition,
        current_time=current_time,
        grace_period_minutes=grace_period_minutes,
    )


@router.get(
    "/bookings/{booking_id}/eta-check",
    response_model=ETASlotCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Compare driver ETA with slot start time by booking ID (REQ-F2-27)",
    description="Path-based ETA versus slot check endpoint for a specific booking.",
)
def get_eta_slot_check_by_booking_id(
    booking_id: int = Path(..., description="Target booking ID"),
    latitude: float = Query(..., description="Driver origin latitude [-90.0, 90.0]"),
    longitude: float = Query(..., description="Driver origin longitude [-180.0, 180.0]"),
    traffic_condition: str | None = Query(
        default=None,
        description="Optional traffic condition: low, normal, heavy, severe",
    ),
    grace_period_minutes: int = Query(
        default=DEFAULT_GRACE_PERIOD_MINUTES,
        ge=0,
        description="Grace period in minutes (default 15 per BR-06)",
    ),
    current_time: datetime | None = Query(
        default=None,
        description="Optional evaluation timestamp",
    ),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ETASlotCheckResponse:
    return check_driver_eta_versus_slot(
        db=db,
        user=current_user,
        booking_id=booking_id,
        driver_latitude=latitude,
        driver_longitude=longitude,
        traffic_condition=traffic_condition,
        current_time=current_time,
        grace_period_minutes=grace_period_minutes,
    )
