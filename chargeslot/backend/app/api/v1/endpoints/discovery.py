from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationSearchRequest,
    NearbyStationSearchResponse,
    StationAvailabilityMarker,
    StationAvailabilityMarkersResponse,
    BatchAvailabilityMarkersRequest,
    StationFilterRequest,
    StationFilterResponse,
    StationSortRequest,
    StationSortResponse,
    StationSortBy,
    SortOrder,
    StationTextSearchRequest,
    StationTextSearchResponse,
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


# =========================================================================
# Availability Markers Endpoints (REQ-F2-08 / CS19-034 / Architecture Doc Page 6)
# =========================================================================

@router.get(
    "/stations/availability-markers",
    response_model=StationAvailabilityMarkersResponse,
    status_code=status.HTTP_200_OK,
    summary="Get station availability markers (SW Architecture Route)",
    description=(
        "Retrieves colour-coded availability markers for stations showing available/total connectors "
        "and accessible status text labels (REQ-F2-08 / CS19-034)."
    ),
)
def get_availability_markers(
    station_id: int | None = Query(default=None, description="Optional specific station ID"),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0, description="Optional center latitude"),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0, description="Optional center longitude"),
    radius_km: float = Query(default=10.0, ge=1.0, le=50.0, description="Radius in km [1.0, 50.0]"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationAvailabilityMarkersResponse:
    return DiscoveryService.get_availability_markers(
        db=db,
        station_id=station_id,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        user=current_user,
    )


@router.patch(
    "/stations/availability-markers",
    response_model=StationAvailabilityMarkersResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch query availability markers via PATCH (SW Architecture Route)",
    description="Matching SW Architecture Page 6 PATCH method: Batch retrieve availability markers for station IDs.",
)
def patch_availability_markers(
    payload: BatchAvailabilityMarkersRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationAvailabilityMarkersResponse:
    return DiscoveryService.get_availability_markers(
        db=db,
        station_ids=payload.station_ids,
        user=current_user,
    )


@router.post(
    "/stations/availability-markers",
    response_model=StationAvailabilityMarkersResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch query availability markers via POST",
    description="Batch retrieve availability markers for a list of station IDs (REQ-F2-08).",
)
def post_availability_markers(
    payload: BatchAvailabilityMarkersRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationAvailabilityMarkersResponse:
    return DiscoveryService.get_availability_markers(
        db=db,
        station_ids=payload.station_ids,
        user=current_user,
    )


@router.get(
    "/stations/{station_id}/availability-marker",
    response_model=StationAvailabilityMarker,
    status_code=status.HTTP_200_OK,
    summary="Get single station availability marker",
    description="Retrieves the colour-coded availability marker for a specific station (REQ-F2-08).",
)
def get_single_station_availability_marker(
    station_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationAvailabilityMarker:
    response = DiscoveryService.get_availability_markers(
        db=db,
        station_id=station_id,
        user=current_user,
    )
    if not response.markers:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found or not active.",
        )
    return response.markers[0]


# =========================================================================
# Station Filtering Endpoints (REQ-F2-09 / CS19-035 / Architecture Doc Page 6)
# =========================================================================

@router.get(
    "/stations/filter-stations",
    response_model=StationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter stations (SW Architecture Route)",
    description=(
        "Filters stations by connector type, minimum power, availability now, "
        "maximum price per kWh, amenities, and vehicle compatibility (REQ-F2-09 / CS19-035)."
    ),
)
def get_filter_stations(
    connector_types: list[str] | None = Query(default=None, description="Connector types: CCS2, CHAdeMO, Type 2, GB/T"),
    min_power_kw: float | None = Query(default=None, ge=0.0, le=500.0, description="Minimum power in kW"),
    available_now: bool | None = Query(default=None, description="Only stations with Available connectors"),
    max_price_kwh: float | None = Query(default=None, ge=0.0, description="Max price per kWh"),
    amenities: list[str] | None = Query(default=None, description="Required amenities e.g. WiFi, Cafe"),
    vehicle_id: int | None = Query(default=None, description="Vehicle ID for compatibility filtering"),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0, description="Center latitude"),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0, description="Center longitude"),
    radius_km: float = Query(default=10.0, ge=1.0, le=50.0, description="Radius in km [1.0, 50.0]"),
    sort_by: str | None = Query(default=None, description="Sort criteria: distance, price, power, availability (REQ-F2-10)"),
    sort_order: str | None = Query(default=None, description="Sort direction: 'asc' or 'desc'"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationFilterResponse:
    return DiscoveryService.filter_stations(
        db=db,
        user=current_user,
        connector_types=connector_types,
        min_power_kw=min_power_kw,
        available_now=available_now,
        max_price_kwh=max_price_kwh,
        amenities=amenities,
        vehicle_id=vehicle_id,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/stations/filter-stations",
    response_model=StationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter stations with JSON payload",
    description="POST alternative to filter stations using request body (REQ-F2-09).",
)
def post_filter_stations(
    payload: StationFilterRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationFilterResponse:
    return DiscoveryService.filter_stations(
        db=db,
        user=current_user,
        connector_types=payload.connector_types,
        min_power_kw=payload.min_power_kw,
        available_now=payload.available_now,
        max_price_kwh=payload.max_price_kwh,
        amenities=payload.amenities,
        vehicle_id=payload.vehicle_id,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_km=payload.radius_km,
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
        limit=payload.limit,
        offset=payload.offset,
    )


# =========================================================================
# Station Sorting Endpoints (REQ-F2-10 / CS19-036 / Architecture Doc Page 6)
# =========================================================================

@router.get(
    "/stations/sort-stations",
    response_model=StationSortResponse,
    status_code=status.HTTP_200_OK,
    summary="Sort stations (SW Architecture Route)",
    description=(
        "Sorts charging stations by distance, price, power, or availability (REQ-F2-10 / CS19-036). "
        "Allows ascending or descending ordering with intelligent defaults."
    ),
)
def get_sort_stations(
    sort_by: str = Query(
        default="distance",
        description="Sort criteria: distance, price, power, availability (REQ-F2-10)",
    ),
    sort_order: str | None = Query(
        default=None,
        description="Sort direction: 'asc' or 'desc'. Defaults: distance/price: asc, power/availability: desc",
    ),
    latitude: float | None = Query(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Driver latitude coordinate [-90.0, 90.0]",
    ),
    longitude: float | None = Query(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Driver longitude coordinate [-180.0, 180.0]",
    ),
    radius_km: float = Query(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Search radius in kilometers [1.0, 50.0]",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationSortResponse:
    return DiscoveryService.sort_stations(
        db=db,
        user=current_user,
        sort_by=sort_by,
        sort_order=sort_order,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/stations/sort-stations",
    response_model=StationSortResponse,
    status_code=status.HTTP_200_OK,
    summary="Sort stations with JSON payload",
    description="POST alternative to sort stations by distance, price, power, or availability (REQ-F2-10).",
)
def post_sort_stations(
    payload: StationSortRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationSortResponse:
    return DiscoveryService.sort_stations(
        db=db,
        user=current_user,
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_km=payload.radius_km,
        station_ids=payload.station_ids,
        limit=payload.limit,
        offset=payload.offset,
    )


# =========================================================================
# Station Free-Text Search Endpoints (REQ-F2-11 / CS19-037 / Architecture Doc Page 6)
# =========================================================================

@router.get(
    "/stations/text-search",
    response_model=StationTextSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search stations by text (SW Architecture Route)",
    description=(
        "Searches charging stations by name, address, or geographic area (REQ-F2-11 / CS19-037). "
        "Case-insensitive matching with relevance ranking and visibility gating."
    ),
)
def get_text_search_stations(
    q: str = Query(
        ...,
        alias="query",
        min_length=1,
        max_length=100,
        description="Search term matching station name, address, or area",
    ),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0, description="Driver latitude"),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0, description="Driver longitude"),
    radius_km: float | None = Query(default=None, ge=1.0, le=50.0, description="Search radius in km"),
    sort_by: str | None = Query(default=None, description="Optional sort criteria: distance, price, power, availability"),
    sort_order: str | None = Query(default=None, description="Optional sort order: asc, desc"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationTextSearchResponse:
    return DiscoveryService.text_search_stations(
        db=db,
        query=q,
        user=current_user,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/stations/text-search",
    response_model=StationTextSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search stations by text with JSON payload",
    description="POST alternative to search stations by text query in request body (REQ-F2-11).",
)
def post_text_search_stations(
    payload: StationTextSearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationTextSearchResponse:
    return DiscoveryService.text_search_stations(
        db=db,
        query=payload.query,
        user=current_user,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_km=payload.radius_km,
        sort_by=payload.sort_by,
        sort_order=payload.sort_order,
        limit=payload.limit,
        offset=payload.offset,
    )



