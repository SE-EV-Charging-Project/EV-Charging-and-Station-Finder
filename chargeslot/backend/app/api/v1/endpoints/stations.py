from datetime import date, datetime
from fastapi import APIRouter, Depends, Path, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_operator, require_admin, get_current_user
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.station import StationStatus
from app.schemas.station import (
    StationCreateRequest,
    StationUpdateRequest,
    StationResponse,
    StationListResponse,
    StationDeactivateResponse,
    StationValidationRulesResponse,
    StationValidationCheckRequest,
    StationValidationCheckResponse,
    ChargerValidationCheckRequest,
    ChargerValidationCheckResponse,
    StationRejectRequest,
    StationApprovalResponse,
    StationApprovalGateStatusResponse,
    StationApprovalGateActionRequest,
    StationBookableSlotsResponse,
    StationSlotTimelineResponse,
    EstimatedWaitTimeResponse,
)
from app.dashboard.timeline import get_station_slot_timeline
from app.dashboard.wait import get_station_estimated_wait_time
from app.stations.slots import (
    MAX_SLOT_DAYS_AHEAD,
    MIN_SLOT_DAYS_AHEAD,
    generate_station_bookable_slots,
)
from app.schemas.charger import (
    StationOutOfServiceMarkingRequest,
    ChargerOutOfServiceResponse,
)
from app.schemas.maintenance import (
    MaintenanceWindowResponse,
    MaintenanceWindowListResponse,
)
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
    StationTextSearchRequest,
    StationTextSearchResponse,
    ClusteredMapViewRequest,
    ClusteredMapViewResponse,
    PaginatedStationListResponse,
)
from app.services.station_service import StationService
from app.services.charger_service import ChargerService
from app.services.maintenance_service import MaintenanceService
from app.services.discovery_service import DiscoveryService

router = APIRouter(prefix="/stations", tags=["Stations"])


@router.post(
    "",
    response_model=StationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new charging station",
    description="Allows a Station Operator or Admin to create a station with location, amenities, operating hours, and contact details (REQ-F2-01 / CS19-027).",
)
def create_station(
    payload: StationCreateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> StationResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.create_station(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )
    return StationResponse.model_validate(station)


@router.get(
    "",
    response_model=StationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List stations",
    description="Returns stations with role scoping: Operators view own stations (REQ-F1-12), Admins view all, Drivers view approved active stations (REQ-F2-03).",
)
def list_stations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    status_filter: StationStatus | None = Query(None, alias="status", description="Filter by approval status"),
    q: str | None = Query(None, description="Search term for station name or address"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationListResponse:
    items, total = StationService.list_stations(
        db=db,
        user=current_user,
        is_active=is_active,
        status_filter=status_filter,
        search_query=q,
        page=page,
        page_size=page_size,
    )
    return StationListResponse(
        items=[StationResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/pending-approval",
    response_model=StationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List stations pending administrator approval",
    description="Returns all stations with status=pending awaiting administrative moderation review (REQ-F2-03 / CS19-029). Restricted to Administrators.",
)
def list_pending_stations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StationListResponse:
    items, total = StationService.list_pending_stations(
        db=db,
        admin=current_user,
        page=page,
        page_size=page_size,
    )
    return StationListResponse(
        items=[StationResponse.model_validate(s) for s in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/station-approval-gate",
    response_model=StationApprovalGateStatusResponse | StationListResponse,
    status_code=status.HTTP_200_OK,
    summary="Station approval gate inspection (SW Architecture Route)",
    description="Matching SW Architecture Page 6: Inspect approval gate and driver visibility status (REQ-F2-03 / CS19-029).",
)
def get_station_approval_gate(
    station_id: int | None = Query(None, description="Optional specific station ID to inspect"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if station_id is not None:
        status_data = StationService.get_approval_gate_status(
            db=db, user=current_user, station_id=station_id
        )
        return StationApprovalGateStatusResponse(**status_data)

    if current_user.role == UserRole.ADMIN:
        items, total = StationService.list_pending_stations(
            db=db, admin=current_user, page=page, page_size=page_size
        )
        return StationListResponse(
            items=[StationResponse.model_validate(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
        )
    else:
        items, total = StationService.list_stations(
            db=db, user=current_user, page=page, page_size=page_size
        )
        return StationListResponse(
            items=[StationResponse.model_validate(s) for s in items],
            total=total,
            page=page,
            page_size=page_size,
        )


@router.post(
    "/station-approval-gate",
    response_model=StationApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Process station approval gate action (SW Architecture Route)",
    description="Matching SW Architecture Page 6: Approve or reject station via moderation action (REQ-F2-03 / CS19-029).",
)
def post_station_approval_gate(
    payload: StationApprovalGateActionRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StationApprovalResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.process_gate_action(
        db=db,
        admin=current_user,
        station_id=payload.station_id,
        action=payload.action,
        reason=payload.reason,
        ip_address=client_ip,
    )
    msg = (
        f"Station '{station.name}' successfully approved and is now visible to drivers."
        if station.status == StationStatus.APPROVED
        else f"Station '{station.name}' rejected: {station.rejection_reason}"
    )
    return StationApprovalResponse(
        id=station.id,
        name=station.name,
        status=station.status,
        is_active=station.is_active,
        rejection_reason=station.rejection_reason,
        reviewed_by_admin_id=station.reviewed_by_admin_id,
        reviewed_at=station.reviewed_at,
        message=msg,
    )


@router.get(
    "/validation-rules",
    response_model=StationValidationRulesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Appendix B.4 validation constraints",
    description="Returns data types, required constraints, coordinate boundaries, and allowed connector types (REQ-F2-04 / CS19-030).",
)
def get_validation_rules(
    current_user: User = Depends(require_operator),
) -> StationValidationRulesResponse:
    rules = StationService.get_validation_rules()
    return StationValidationRulesResponse(
        station_rules=rules["station_rules"],
        charger_rules=rules["charger_rules"],
    )


@router.post(
    "/validate",
    response_model=StationValidationCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Dry-run station validation check",
    description="Validates station fields against Appendix B.4 and REQ-F2-04 without database mutation.",
)
def validate_station_check(
    payload: StationValidationCheckRequest,
    current_user: User = Depends(require_operator),
) -> StationValidationCheckResponse:
    is_valid, errors = StationService.validate_station_payload(
        data=payload.data,
        partial=payload.partial,
    )
    msg = (
        "Station values are valid per REQ-F2-04."
        if is_valid
        else "Station validation failed. Please correct the specified field errors."
    )
    return StationValidationCheckResponse(
        valid=is_valid,
        errors=errors,
        message=msg,
    )


@router.post(
    "/validate-charger",
    response_model=ChargerValidationCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Dry-run charger and connector validation check",
    description="Validates charger power rating, current type, and connector types against Appendix B.4 and REQ-F2-04 without saving.",
)
def validate_charger_check(
    payload: ChargerValidationCheckRequest,
    current_user: User = Depends(require_operator),
) -> ChargerValidationCheckResponse:
    is_valid, errors = StationService.validate_charger_payload(
        data=payload.data,
        partial=payload.partial,
    )
    msg = (
        "Charger and connector specifications are valid per REQ-F2-04."
        if is_valid
        else "Charger validation failed. Please correct the specified field errors."
    )
    return ChargerValidationCheckResponse(
        valid=is_valid,
        errors=errors,
        message=msg,
    )


# =========================================================================
# Out-of-Service Marking SW Architecture Routes (REQ-F2-05 / CS19-031)
# =========================================================================

@router.patch(
    "/out-of-service-marking",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Out-of-service marking (SW Architecture Route)",
    description="Matching SW Architecture Page 6: Mark charger out of service or return to service (REQ-F2-05 / CS19-031).",
)
@router.post(
    "/out-of-service-marking",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def patch_station_out_of_service_marking(
    payload: StationOutOfServiceMarkingRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerOutOfServiceResponse:
    client_ip = request.client.host if request.client else None
    if payload.is_out_of_service:
        if not payload.reason:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Reason is mandatory when marking a charger out of service (REQ-F2-05).",
            )
        if not payload.expected_return_time:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Expected return time is mandatory when marking a charger out of service (REQ-F2-05).",
            )
        charger, affected_count = ChargerService.mark_out_of_service(
            db=db,
            user=current_user,
            charger_id=payload.charger_id,
            reason=payload.reason,
            expected_return_time=payload.expected_return_time,
            ip_address=client_ip,
        )
    else:
        charger, affected_count = ChargerService.return_to_service(
            db=db,
            user=current_user,
            charger_id=payload.charger_id,
            note=payload.reason,
            ip_address=client_ip,
        )

    return ChargerOutOfServiceResponse(
        charger_id=charger.id,
        station_id=charger.station_id,
        name=charger.name,
        is_out_of_service=charger.is_out_of_service,
        out_of_service_reason=charger.out_of_service_reason,
        expected_return_time=charger.expected_return_time,
        out_of_service_at=charger.out_of_service_at,
        affected_connectors_count=affected_count,
        message=(
            f"Charger '{charger.name or charger.id}' marked out of service (REQ-F2-05)."
            if charger.is_out_of_service
            else f"Charger '{charger.name or charger.id}' returned to operational service."
        ),
    )


@router.get(
    "/out-of-service-marking",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get out-of-service status (SW Architecture Route)",
    description="Matching SW Architecture Page 6 GET alias: Inspect charger out-of-service status (REQ-F2-05 / CS19-031).",
)
def get_station_out_of_service_marking(
    charger_id: int = Query(..., description="Target charger ID"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargerOutOfServiceResponse:
    data = ChargerService.get_out_of_service_status(
        db=db,
        user=current_user,
        charger_id=charger_id,
    )
    return ChargerOutOfServiceResponse(**data)


@router.get(
    "/maintenance-windows",
    response_model=MaintenanceWindowListResponse,
    status_code=status.HTTP_200_OK,
    summary="List maintenance windows across stations (SW Architecture Route)",
    description="Matching SW Architecture Page 6: Query maintenance windows across stations (REQ-F2-06 / CS19-032).",
)
def get_station_maintenance_windows(
    station_id: int | None = Query(None, description="Filter by station ID"),
    charger_id: int | None = Query(None, description="Filter by charger ID"),
    active_only: bool = Query(False, description="Filter active/upcoming windows"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MaintenanceWindowListResponse:
    total, items = MaintenanceService.list_maintenance_windows(
        db=db,
        user=current_user,
        station_id=station_id,
        charger_id=charger_id,
        active_only=active_only,
        skip=skip,
        limit=limit,
    )
    return MaintenanceWindowListResponse(
        total=total,
        items=[MaintenanceWindowResponse.model_validate(w) for w in items],
    )


@router.get(
    "/nearby-station-search",
    response_model=NearbyStationSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Nearby station search (SW Architecture Route)",
    description=(
        "Displays nearby stations on a map and in a list based on driver's location "
        "within a selectable radius (default 10 km, range 1 to 50 km) (REQ-F2-07 / CS19-033)."
    ),
)
def get_station_nearby_search(
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
    "/nearby-station-search",
    response_model=NearbyStationSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Nearby station search with JSON payload",
    description="POST alternative to query nearby stations using request body (REQ-F2-07).",
)
def post_station_nearby_search(
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


@router.get(
    "/availability-markers",
    response_model=StationAvailabilityMarkersResponse,
    status_code=status.HTTP_200_OK,
    summary="Get station availability markers (SW Architecture Route)",
    description=(
        "Retrieves colour-coded availability markers for stations showing available/total connectors "
        "and accessible status text labels (REQ-F2-08 / CS19-034)."
    ),
)
def get_station_availability_markers(
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
    "/availability-markers",
    response_model=StationAvailabilityMarkersResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch query availability markers via PATCH (SW Architecture Route)",
    description="Matching SW Architecture Page 6 PATCH method: Batch retrieve availability markers for station IDs.",
)
def patch_station_availability_markers(
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
    "/filter-stations",
    response_model=StationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter stations (SW Architecture Route)",
    description=(
        "Filters stations by connector type, minimum power, availability now, "
        "maximum price per kWh, amenities, and vehicle compatibility. Vehicle filtering "
        "matches the connector type and AC/DC power capability (REQ-F3-05)."
    ),
)
def get_station_filter_stations(
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
    "/filter-stations",
    response_model=StationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter stations with JSON payload",
    description="POST alternative to filter stations using request body (REQ-F2-09).",
)
def post_station_filter_stations(
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


@router.get(
    "/reachable",
    response_model=StationFilterResponse,
    status_code=status.HTTP_200_OK,
    summary="Filter stations by vehicle reachability",
    description=(
        "Returns compatible stations whose self-hosted road-routing distance is within "
        "the selected vehicle's usable range (REQ-F3-04 / CS19-058)."
    ),
)
def get_reachable_stations(
    vehicle_id: int = Query(..., gt=0, description="Owned vehicle with a saved battery level"),
    latitude: float = Query(..., ge=-90.0, le=90.0, description="Current driver latitude"),
    longitude: float = Query(..., ge=-180.0, le=180.0, description="Current driver longitude"),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationFilterResponse:
    return DiscoveryService.get_reachable_stations(
        db=db,
        user=current_user,
        vehicle_id=vehicle_id,
        latitude=latitude,
        longitude=longitude,
        limit=limit,
        offset=offset,
    )


# =========================================================================
# Station Sorting Endpoints (REQ-F2-10 / CS19-036 / Architecture Doc Page 6)
# =========================================================================

@router.get(
    "/sort-stations",
    response_model=StationSortResponse,
    status_code=status.HTTP_200_OK,
    summary="Sort stations (SW Architecture Route)",
    description=(
        "Sorts charging stations by distance, price, power, or availability (REQ-F2-10 / CS19-036). "
        "Allows ascending or descending ordering with intelligent defaults."
    ),
)
def get_station_sort_stations(
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
    "/sort-stations",
    response_model=StationSortResponse,
    status_code=status.HTTP_200_OK,
    summary="Sort stations with JSON payload",
    description="POST alternative to sort stations by distance, price, power, or availability (REQ-F2-10).",
)
def post_station_sort_stations(
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
    "/text-search",
    response_model=StationTextSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search stations by text (SW Architecture Route)",
    description=(
        "Searches charging stations by name, address, or geographic area (REQ-F2-11 / CS19-037). "
        "Case-insensitive matching with relevance ranking and visibility gating."
    ),
)
def get_station_text_search(
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
    "/text-search",
    response_model=StationTextSearchResponse,
    status_code=status.HTTP_200_OK,
    summary="Search stations by text with JSON payload",
    description="POST alternative to search stations by text query in request body (REQ-F2-11).",
)
def post_station_text_search(
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


# =========================================================================
# Map Marker Clustering and Pagination Endpoints (REQ-F2-12 / CS19-038)
# =========================================================================

@router.get(
    "/map-view",
    response_model=ClusteredMapViewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get stations for map view with clustering (SW Architecture Route)",
    description=(
        "Retrieves stations for map display. Automatically clusters markers when >50 stations "
        "are in view per REQ-F2-12 / CS19-038."
    ),
)
def get_station_clustered_map_view(
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0, description="Center latitude"),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0, description="Center longitude"),
    radius_km: float = Query(default=50.0, ge=1.0, le=50.0, description="Search radius in km"),
    threshold: int = Query(default=50, ge=1, le=100, description="Clustering threshold (default: 50 per REQ-F2-12)"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClusteredMapViewResponse:
    return DiscoveryService.get_map_view(
        db=db,
        user=current_user,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        threshold=threshold,
    )


@router.post(
    "/map-view",
    response_model=ClusteredMapViewResponse,
    status_code=status.HTTP_200_OK,
    summary="Get stations for map view with clustering via JSON payload",
    description="POST alternative to query clustered map view (REQ-F2-12).",
)
def post_station_clustered_map_view(
    payload: ClusteredMapViewRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ClusteredMapViewResponse:
    return DiscoveryService.get_map_view(
        db=db,
        user=current_user,
        latitude=payload.latitude,
        longitude=payload.longitude,
        radius_km=payload.radius_km,
        threshold=payload.threshold,
    )


@router.get(
    "/paginated-search",
    response_model=PaginatedStationListResponse,
    status_code=status.HTTP_200_OK,
    summary="Get paginated list of stations (20/page default)",
    description=(
        "Retrieves paginated charging station list results defaulting to 20/page (REQ-F2-12 / CS19-038). "
        "Provides total_pages, has_next, and has_prev navigation indicators."
    ),
)
def get_station_paginated_search(
    page: int = Query(default=1, ge=1, description="Page number (1-indexed, default 1)"),
    page_size: int = Query(default=20, ge=1, le=100, description="Page size (default 20/page per REQ-F2-12)"),
    latitude: float | None = Query(default=None, ge=-90.0, le=90.0, description="Driver latitude"),
    longitude: float | None = Query(default=None, ge=-180.0, le=180.0, description="Driver longitude"),
    radius_km: float = Query(default=50.0, ge=1.0, le=50.0, description="Search radius in km"),
    sort_by: str | None = Query(default=None, description="Sort criteria: distance, price, power, availability"),
    sort_order: str | None = Query(default=None, description="Sort order: asc, desc"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaginatedStationListResponse:
    return DiscoveryService.get_paginated_stations(
        db=db,
        user=current_user,
        page=page,
        page_size=page_size,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
        sort_by=sort_by,
        sort_order=sort_order,
    )


# ---------------------------------------------------------------------------
# Slot Generation Query Endpoint (REQ-F2-22 / CS19-048)
# Must appear before /{station_id} to avoid FastAPI routing collision
# ---------------------------------------------------------------------------


@router.get(
    "/slot-generation",
    response_model=StationBookableSlotsResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate bookable 15-minute slots for connectors (SW Architecture Route)",
    description="Generates 15-minute bookable slots for every connector up to 7 days ahead (REQ-F2-22 / CS19-048).",
)
def generate_slots(
    station_id: int | None = Query(default=None, description="Station ID"),
    connector_id: int | None = Query(default=None, description="Connector ID (station_id inferred if omitted)"),
    days_ahead: int = Query(default=MAX_SLOT_DAYS_AHEAD, ge=1, le=MAX_SLOT_DAYS_AHEAD, description="Horizon in days (1..7)"),
    target_date: date | None = Query(default=None, description="Optional single date filter (YYYY-MM-DD) within 7 days"),
    available_only: bool = Query(default=False, description="Filter for bookable/available slots only"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationBookableSlotsResponse:
    return generate_station_bookable_slots(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        days_ahead=days_ahead,
        target_date=target_date,
        available_only=available_only,
    )


# ---------------------------------------------------------------------------
# Slot Timeline Query Endpoint (REQ-F2-23 / CS19-049)
# Must appear before /{station_id} to avoid FastAPI routing collision
# ---------------------------------------------------------------------------


@router.get(
    "/slot-timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline per connector (SW Architecture Route)",
    description=(
        "Displays, for a selected station and date, a slot timeline per connector in which "
        "each 15-minute slot is shown as Free, Booked, Blocked or Past (REQ-F2-23 / CS19-049)."
    ),
)
def get_slot_timeline(
    station_id: int | None = Query(default=None, description="Station ID"),
    connector_id: int | None = Query(default=None, description="Connector ID (station_id inferred if omitted)"),
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
# Estimated Wait Time Query Endpoint (REQ-F2-24 / CS19-050)
# Must appear before /{station_id} to avoid FastAPI routing collision
# ---------------------------------------------------------------------------


@router.get(
    "/estimated-wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time for station (SW Architecture Route)",
    description=(
        "Displays estimated wait time when all compatible connectors at a station are occupied, "
        "calculated from the expected end of active sessions (REQ-F2-24 / CS19-050)."
    ),
)
def get_estimated_wait_time(
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
    "/{station_id}",
    response_model=StationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get station details",
    description="Retrieves station details. Operators can access only their own stations (REQ-F1-12, REQ-F2-01). Drivers can view approved active stations; unapproved/inactive are hidden (REQ-F2-03).",
)
def get_station(
    station_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationResponse:
    station = StationService.get_station(
        db=db,
        user=current_user,
        station_id=station_id,
    )
    return StationResponse.model_validate(station)


@router.put(
    "/{station_id}",
    response_model=StationResponse,
    status_code=status.HTTP_200_OK,
    summary="Update station details",
    description="Updates station attributes. Content modifications reset approval status to 'pending' (REQ-F2-01, REQ-F2-03).",
)
def update_station(
    station_id: int,
    payload: StationUpdateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> StationResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.update_station(
        db=db,
        user=current_user,
        station_id=station_id,
        data=payload,
        ip_address=client_ip,
    )
    return StationResponse.model_validate(station)


@router.delete(
    "/{station_id}",
    response_model=StationDeactivateResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate a station",
    description="Deactivates a station by setting is_active=False and status=inactive (REQ-F2-01).",
)
def delete_station(
    station_id: int,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> StationDeactivateResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.deactivate_station(
        db=db,
        user=current_user,
        station_id=station_id,
        ip_address=client_ip,
    )
    return StationDeactivateResponse(
        message="Station successfully deactivated.",
        station_id=station.id,
        is_active=station.is_active,
        status=station.status,
    )


@router.post(
    "/{station_id}/deactivate",
    response_model=StationDeactivateResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate station explicitly",
    description="Action endpoint to deactivate a station (REQ-F2-01).",
)
def deactivate_station_action(
    station_id: int,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> StationDeactivateResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.deactivate_station(
        db=db,
        user=current_user,
        station_id=station_id,
        ip_address=client_ip,
    )
    return StationDeactivateResponse(
        message="Station successfully deactivated.",
        station_id=station.id,
        is_active=station.is_active,
        status=station.status,
    )


@router.post(
    "/{station_id}/approve",
    response_model=StationApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve station by Administrator",
    description="Transitions station status to 'approved', making it visible to drivers (REQ-F2-03 / CS19-029). Restricted to Administrators.",
)
def approve_station(
    station_id: int,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StationApprovalResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.approve_station(
        db=db,
        admin=current_user,
        station_id=station_id,
        ip_address=client_ip,
    )
    return StationApprovalResponse(
        id=station.id,
        name=station.name,
        status=station.status,
        is_active=station.is_active,
        rejection_reason=station.rejection_reason,
        reviewed_by_admin_id=station.reviewed_by_admin_id,
        reviewed_at=station.reviewed_at,
        message=f"Station '{station.name}' successfully approved and made visible to drivers (REQ-F2-03).",
    )


@router.post(
    "/{station_id}/reject",
    response_model=StationApprovalResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject station by Administrator",
    description="Transitions station status to 'rejected' with a mandatory reason; station remains hidden from drivers (REQ-F2-03 / CS19-029). Restricted to Administrators.",
)
def reject_station(
    station_id: int,
    payload: StationRejectRequest,
    request: Request,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> StationApprovalResponse:
    client_ip = request.client.host if request.client else None
    station = StationService.reject_station(
        db=db,
        admin=current_user,
        station_id=station_id,
        reason=payload.reason,
        ip_address=client_ip,
    )
    return StationApprovalResponse(
        id=station.id,
        name=station.name,
        status=station.status,
        is_active=station.is_active,
        rejection_reason=station.rejection_reason,
        reviewed_by_admin_id=station.reviewed_by_admin_id,
        reviewed_at=station.reviewed_at,
        message=f"Station '{station.name}' rejected: {station.rejection_reason} (REQ-F2-03).",
    )


@router.get(
    "/{station_id}/approval-status",
    response_model=StationApprovalGateStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get station approval gate status",
    description="Inspects whether a station is approved, pending, or rejected, and its visibility to drivers (REQ-F2-03 / CS19-029).",
)
def get_station_approval_status(
    station_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationApprovalGateStatusResponse:
    data = StationService.get_approval_gate_status(
        db=db,
        user=current_user,
        station_id=station_id,
    )
    return StationApprovalGateStatusResponse(**data)


# ---------------------------------------------------------------------------
# Slot Generation Path Endpoints (REQ-F2-22 / CS19-048)
# ---------------------------------------------------------------------------


@router.get(
    "/{station_id}/slot-generation",
    response_model=StationBookableSlotsResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate bookable slots for station (path route)",
    description="Generates 15-minute bookable slots for all connectors at a station up to 7 days ahead (REQ-F2-22 / CS19-048).",
)
@router.get(
    "/{station_id}/slots",
    response_model=StationBookableSlotsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get bookable slots for station",
    description="Path alias for bookable slot generation (REQ-F2-22).",
)
def generate_station_slots_by_id(
    station_id: int = Path(..., description="Target station ID"),
    days_ahead: int = Query(default=MAX_SLOT_DAYS_AHEAD, ge=1, le=MAX_SLOT_DAYS_AHEAD, description="Days ahead (1..7)"),
    target_date: date | None = Query(default=None, description="Optional single target date"),
    available_only: bool = Query(default=False, description="Return available slots only"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationBookableSlotsResponse:
    return generate_station_bookable_slots(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=None,
        days_ahead=days_ahead,
        target_date=target_date,
        available_only=available_only,
    )


@router.get(
    "/{station_id}/connectors/{connector_id}/slots",
    response_model=StationBookableSlotsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get bookable slots for specific connector",
    description="Generates 15-minute bookable slots for a single connector up to 7 days ahead (REQ-F2-22).",
)
def generate_connector_slots_by_id(
    station_id: int = Path(..., description="Target station ID"),
    connector_id: int = Path(..., description="Target connector ID"),
    days_ahead: int = Query(default=MAX_SLOT_DAYS_AHEAD, ge=1, le=MAX_SLOT_DAYS_AHEAD, description="Days ahead (1..7)"),
    target_date: date | None = Query(default=None, description="Optional single target date"),
    available_only: bool = Query(default=False, description="Return available slots only"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationBookableSlotsResponse:
    return generate_station_bookable_slots(
        db=db,
        user=current_user,
        station_id=station_id,
        connector_id=connector_id,
        days_ahead=days_ahead,
        target_date=target_date,
        available_only=available_only,
    )


# ---------------------------------------------------------------------------
# Slot Timeline Path Endpoints (REQ-F2-23 / CS19-049)
# ---------------------------------------------------------------------------


@router.get(
    "/{station_id}/slot-timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline for station (path route)",
    description="Displays 15-minute slot timeline for a station and date (REQ-F2-23).",
)
@router.get(
    "/{station_id}/timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline (short path alias)",
    description="Short path alias for slot timeline view (REQ-F2-23).",
)
def get_station_timeline_by_id(
    station_id: int = Path(..., description="Target station ID"),
    target_date: date | None = Query(default=None, description="Optional target date (YYYY-MM-DD), defaults to today"),
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
    "/{station_id}/connectors/{connector_id}/timeline",
    response_model=StationSlotTimelineResponse,
    status_code=status.HTTP_200_OK,
    summary="Display slot timeline for specific connector",
    description="Displays 15-minute slot timeline for a single connector and date (REQ-F2-23).",
)
def get_connector_timeline_by_id(
    station_id: int = Path(..., description="Target station ID"),
    connector_id: int = Path(..., description="Target connector ID"),
    target_date: date | None = Query(default=None, description="Optional target date (YYYY-MM-DD), defaults to today"),
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
# Estimated Wait Time Path Endpoints (REQ-F2-24 / CS19-050)
# ---------------------------------------------------------------------------


@router.get(
    "/{station_id}/estimated-wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time for station (path route)",
    description="Displays estimated wait time when all compatible connectors are occupied (REQ-F2-24).",
)
@router.get(
    "/{station_id}/wait-time",
    response_model=EstimatedWaitTimeResponse,
    status_code=status.HTTP_200_OK,
    summary="Display estimated wait time (short path alias)",
    description="Short path alias displaying estimated wait time for a station (REQ-F2-24).",
)
def get_station_wait_time_by_id(
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




