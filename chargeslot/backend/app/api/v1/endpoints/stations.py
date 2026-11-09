from fastapi import APIRouter, Depends, Query, Request, status
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
)
from app.services.station_service import StationService

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

