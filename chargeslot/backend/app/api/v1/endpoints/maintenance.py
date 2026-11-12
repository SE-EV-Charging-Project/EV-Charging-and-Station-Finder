from fastapi import APIRouter, Depends, Request, Query, status
from sqlalchemy.orm import Session

from app.api.deps import require_operator, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.maintenance import (
    MaintenanceWindowCreateRequest,
    MaintenanceWindowUpdateRequest,
    MaintenanceWindowResponse,
    MaintenanceWindowListResponse,
    SlotAvailabilityCheckRequest,
    SlotAvailabilityCheckResponse,
)
from app.services.maintenance_service import MaintenanceService

router = APIRouter(tags=["Maintenance Windows & Slot Availability"])


# =========================================================================
# Architecture Doc Page 6: Global Station Maintenance Windows Query
# =========================================================================

@router.get(
    "/stations/maintenance-windows",
    response_model=MaintenanceWindowListResponse,
    summary="List maintenance windows across stations",
    description="Lists maintenance windows (SW Architecture Doc Page 6). Scoped by operator tenancy for operators, approved active stations for drivers, or all for admins.",
)
def list_all_maintenance_windows(
    station_id: int | None = Query(default=None, description="Filter by station ID"),
    charger_id: int | None = Query(default=None, description="Filter by charger ID"),
    active_only: bool = Query(default=False, description="Filter active/upcoming maintenance windows"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
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


# =========================================================================
# Station Specific Maintenance Windows Endpoints
# =========================================================================

@router.post(
    "/stations/{station_id}/maintenance-windows",
    response_model=MaintenanceWindowResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Define maintenance window",
    description="Defines a maintenance window for a station or specific charger, removing affected slots from availability (REQ-F2-06 / CS19-032).",
)
def create_maintenance_window(
    station_id: int,
    payload: MaintenanceWindowCreateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> MaintenanceWindowResponse:
    client_ip = request.client.host if request.client else None
    window = MaintenanceService.create_maintenance_window(
        db=db,
        station_id=station_id,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )
    return MaintenanceWindowResponse.model_validate(window)


@router.get(
    "/stations/{station_id}/maintenance-windows",
    response_model=MaintenanceWindowListResponse,
    summary="List station maintenance windows",
    description="Lists all maintenance windows defined for the specified station.",
)
def list_station_maintenance_windows(
    station_id: int,
    charger_id: int | None = Query(default=None, description="Filter by charger ID"),
    active_only: bool = Query(default=False, description="Filter active/upcoming windows"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
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


@router.post(
    "/stations/{station_id}/check-slot-availability",
    response_model=SlotAvailabilityCheckResponse,
    summary="Check slot availability against maintenance windows",
    description="Evaluates candidate time slots against active maintenance windows and removes affected slots from availability (REQ-F2-06 / §5.2.4).",
)
def check_slot_availability(
    station_id: int,
    payload: SlotAvailabilityCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SlotAvailabilityCheckResponse:
    available_slots, removed_slots = MaintenanceService.check_slot_availability(
        db=db,
        station_id=station_id,
        slots=payload.slots,
    )
    return SlotAvailabilityCheckResponse(
        total_slots=len(payload.slots),
        available_count=len(available_slots),
        removed_count=len(removed_slots),
        available_slots=available_slots,
        removed_slots=removed_slots,
    )


# =========================================================================
# Maintenance Window Detail, Update, Delete Endpoints
# =========================================================================

@router.get(
    "/maintenance-windows/{window_id}",
    response_model=MaintenanceWindowResponse,
    summary="Get maintenance window",
    description="Retrieves details of a maintenance window by ID.",
)
def get_maintenance_window(
    window_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> MaintenanceWindowResponse:
    window = MaintenanceService.get_maintenance_window(
        db=db,
        window_id=window_id,
        user=current_user,
    )
    return MaintenanceWindowResponse.model_validate(window)


@router.put(
    "/maintenance-windows/{window_id}",
    response_model=MaintenanceWindowResponse,
    summary="Update maintenance window",
    description="Updates an existing maintenance window.",
)
def update_maintenance_window(
    window_id: int,
    payload: MaintenanceWindowUpdateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> MaintenanceWindowResponse:
    client_ip = request.client.host if request.client else None
    window = MaintenanceService.update_maintenance_window(
        db=db,
        window_id=window_id,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )
    return MaintenanceWindowResponse.model_validate(window)


@router.delete(
    "/maintenance-windows/{window_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete maintenance window",
    description="Deletes a maintenance window, restoring slot availability.",
)
def delete_maintenance_window(
    window_id: int,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> dict:
    client_ip = request.client.host if request.client else None
    MaintenanceService.delete_maintenance_window(
        db=db,
        window_id=window_id,
        user=current_user,
        ip_address=client_ip,
    )
    return {"message": f"Maintenance window {window_id} successfully deleted."}

