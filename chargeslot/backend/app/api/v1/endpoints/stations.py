from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_operator, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.station import StationStatus
from app.schemas.station import (
    StationCreateRequest,
    StationUpdateRequest,
    StationResponse,
    StationListResponse,
    StationDeactivateResponse,
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
    summary="List operator stations",
    description="Returns stations scoped to the authenticated operator (REQ-F1-12). Administrators see all stations.",
)
def list_stations(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    is_active: bool | None = Query(None, description="Filter by active status"),
    status_filter: StationStatus | None = Query(None, alias="status", description="Filter by approval status"),
    q: str | None = Query(None, description="Search term for station name or address"),
    current_user: User = Depends(require_operator),
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
    "/{station_id}",
    response_model=StationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get station details",
    description="Retrieves station details. Operators can access only their own stations (REQ-F1-12, REQ-F2-01).",
)
def get_station(
    station_id: int,
    current_user: User = Depends(require_operator),
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
