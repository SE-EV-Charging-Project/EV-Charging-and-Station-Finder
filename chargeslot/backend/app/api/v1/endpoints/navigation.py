"""
Navigation API Endpoints (REQ-F2-25 / CS19-051).

Provides route preview from driver origin coordinates to a destination charging station,
including road distance, estimated travel time with current traffic, waypoints, and fallbacks.
"""

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.navigation.routes import calculate_route_preview
from app.schemas.navigation import RoutePreviewResponse

router = APIRouter(prefix="/navigation", tags=["Navigation"])


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
