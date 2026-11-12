from fastapi import APIRouter, Depends, Request, status, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.booking import (
    BatteryLevelInputRequest,
    BatteryLevelResponse,
    BatteryRulesResponse,
    ChargingCostEstimateRequest,
    ChargingCostEstimateResponse,
    ChargingTimeEstimateRequest,
    ChargingTimeEstimateResponse,
)
from app.services.booking_service import BookingService

router = APIRouter(prefix="/bookings", tags=["Bookings"])


@router.post(
    "/battery-level-input",
    response_model=BatteryLevelResponse,
    status_code=status.HTTP_200_OK,
    summary="Enter or update vehicle battery level",
    description="Allows a driver to enter and update their current vehicle battery level (SoC) as a percentage (REQ-F3-01 / CS19-055 / SW Architecture Page 7).",
)
@router.patch(
    "/battery-level-input",
    response_model=BatteryLevelResponse,
    status_code=status.HTTP_200_OK,
    summary="Update vehicle battery level",
    description="Update current vehicle battery level percentage (REQ-F3-01 / CS19-055).",
    include_in_schema=False,
)
def post_battery_level_input(
    payload: BatteryLevelInputRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatteryLevelResponse:
    client_ip = request.client.host if request.client else None
    return BookingService.set_battery_level(
        db=db,
        user=current_user,
        battery_level=payload.battery_level,
        vehicle_id=payload.vehicle_id,
        target_soc=payload.target_soc,
        ip_address=client_ip,
    )


@router.get(
    "/battery-level-input",
    response_model=BatteryLevelResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle battery level and driving range",
    description="Retrieves current battery level (SoC), target SoC, usable range, and estimated range (REQ-F3-01 / CS19-055 / SW Architecture Page 7).",
)
def get_battery_level_input(
    vehicle_id: int | None = Query(default=None, description="Optional vehicle ID; defaults to driver default vehicle"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BatteryLevelResponse:
    return BookingService.get_battery_level(
        db=db,
        user=current_user,
        vehicle_id=vehicle_id,
    )


@router.get(
    "/battery-rules",
    response_model=BatteryRulesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get Appendix B battery calculation rules",
    description="Returns documented calculation and validation rules for battery levels, range calculations, and defaults.",
)
def get_battery_rules() -> BatteryRulesResponse:
    return BatteryRulesResponse(
        rules=BookingService.get_battery_rules(),
        status="success",
    )


@router.post(
    "/charging-time-estimate",
    response_model=ChargingTimeEstimateResponse,
    status_code=status.HTTP_200_OK,
    summary="Estimate vehicle charging time",
    description="Estimates charging time from the vehicle's current SoC, target SoC, battery capacity, and effective charger power (REQ-F3-07 / CS19-061).",
)
def post_charging_time_estimate(
    payload: ChargingTimeEstimateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargingTimeEstimateResponse:
    return BookingService.estimate_charging_time(
        db=db,
        user=current_user,
        vehicle_id=payload.vehicle_id,
        charger_id=payload.charger_id,
        target_soc=payload.target_soc,
    )


@router.post(
    "/cost-estimate",
    response_model=ChargingCostEstimateResponse,
    status_code=status.HTTP_200_OK,
    summary="Estimate vehicle charging cost",
    description="Estimates charging cost using the vehicle's current SoC, target SoC, battery capacity, and station tariff (REQ-F3-09 / CS19-063).",
)
def post_charging_cost_estimate(
    payload: ChargingCostEstimateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargingCostEstimateResponse:
    return BookingService.estimate_charging_cost(
        db=db,
        user=current_user,
        vehicle_id=payload.vehicle_id,
        station_id=payload.station_id,
        target_soc=payload.target_soc,
    )
