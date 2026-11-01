from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.vehicle import (
    VehicleCreateRequest,
    VehicleUpdateRequest,
    VehicleResponse,
    VehicleListResponse,
    VehicleDeleteResponse,
    VehicleValidationRulesResponse,
    VehicleValidationCheckRequest,
    VehicleValidationCheckResponse,
    VehicleSummaryCardResponse,
    VehicleSummaryCardListResponse,
)
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
    "/validation-rules",
    response_model=VehicleValidationRulesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle validation rules",
    description="Returns metadata specification rules and valid bounds for EV vehicles (REQ-F1-19 / CS19-019 / Appendix B.3)."
)
def get_vehicle_validation_rules() -> VehicleValidationRulesResponse:
    return VehicleService.get_validation_rules()


@router.post(
    "/validate",
    response_model=VehicleValidationCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate vehicle inputs",
    description="Performs pre-save inline validation for vehicle values against Appendix B ranges (REQ-F1-19 / CS19-019)."
)
def validate_vehicle(
    payload: VehicleValidationCheckRequest,
    current_user: User = Depends(get_current_user),
) -> VehicleValidationCheckResponse:
    return VehicleService.validate_vehicle_inputs(payload=payload)


@router.get(
    "/summary/cards",
    response_model=VehicleSummaryCardListResponse,
    status_code=status.HTTP_200_OK,
    summary="List vehicle summary cards",
    description="Lists summary cards for all vehicles of the authenticated driver with compatibility icons (REQ-F1-20 / CS19-020)."
)
def list_vehicle_summary_cards(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleSummaryCardListResponse:
    return VehicleService.list_vehicle_summaries(db=db, user=current_user)


@router.get(
    "/{vehicle_id}/summary",
    response_model=VehicleSummaryCardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle summary card",
    description="Displays a summary card for a specific vehicle showing compatibility icons and calculated ranges (REQ-F1-20 / CS19-020)."
)
def get_vehicle_summary_card(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleSummaryCardResponse:
    return VehicleService.get_vehicle_summary(db=db, vehicle_id=vehicle_id, user=current_user)


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
    vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=current_user)
    return VehicleResponse.model_validate(vehicle)


@router.patch(
    "/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit vehicle details",
    description="Updates specifications or details of an existing vehicle (CS19-021 / REQ-F1-21)."
)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.update_vehicle(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.delete(
    "/{vehicle_id}",
    response_model=VehicleDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vehicle",
    description="Deletes a vehicle from the authenticated driver's account (CS19-021 / REQ-F1-21)."
)
def remove_vehicle(
    vehicle_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleDeleteResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.remove_vehicle(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
        ip_address=client_ip,
    )

