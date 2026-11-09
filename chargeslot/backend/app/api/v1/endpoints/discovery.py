from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationSearchRequest,
    NearbyStationSearchResponse,
)
from app.services.discovery_service import DiscoveryService

router = APIRouter(tags=["Station Discovery"])


@router.get(
    "/stations/nearby-station-search",
    response_model=NearbyStationSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Nearby station search (SW Architecture Route)",
    description=(
        "Displays nearby stations on a map and in a list based on driver's location "
        "within a selectable radius (default 10 km, range 1 to 50 km) (REQ-F2-07 / CS19-033)."
    ),
)
def get_nearby_stations(
    latitude: float = Query(
        ...,
        ge=-90.0,
        le=90.0,
        description="Driver latitude coordinate [-90.0, 90.0]",
    ),
    longitude: float = Query(
        ...,
        ge=-180.0,
        le=180.0,
        description="Driver longitude coordinate [-180.0, 180.0]",
    ),
    radius_km: float = Query(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Search radius in kilometers [1.0, 50.0] (default: 10.0 km)",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NearbyStationSearchResponse:
    return DiscoveryService.get_nearby_stations(
        db=db,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        limit=limit,
        user=current_user,
    )


@router.post(
    "/stations/nearby-station-search",
    response_model=NearbyStationSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Nearby station search with JSON payload",
    description="POST alternative to query nearby stations using request body (REQ-F2-07).",
)
def post_nearby_stations(
    payload: NearbyStationSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> NearbyStationSearchResponse:
    return DiscoveryService.get_nearby_stations(
        db=db,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_km=payload.radius_km,
        limit=payload.limit,
        user=current_user,
    )

