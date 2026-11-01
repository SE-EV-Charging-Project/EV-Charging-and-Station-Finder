from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.vehicle import VehicleCreateRequest, VehicleResponse, VehicleListResponse
from app.services.vehicle_service import VehicleService

router = APIRouter(prefix="/vehicles", tags=["Vehicles"])


@router.post(
    "",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add a new EV vehicle",
    description="Registers an electric vehicle for the authenticated driver with charging and battery specifications (REQ-F1-18 / CS19-018)."
)
def add_vehicle(
    payload: VehicleCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.add_vehicle(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.get(
    "",
    response_model=VehicleListResponse,
    status_code=status.HTTP_200_OK,
    summary="List driver vehicles",
    description="Lists all electric vehicles owned by the authenticated driver."
)
def list_vehicles(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleListResponse:
    return VehicleService.list_vehicles(db=db, user=current_user)


@router.get(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle details",
    description="Fetches details for a specific vehicle by ID, ensuring driver data isolation."
)
def get_vehicle(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    return VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=current_user)
