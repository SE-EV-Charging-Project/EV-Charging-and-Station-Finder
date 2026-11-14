"""
Battery Level Input and Range Calculations (REQ-F3-01 / CS19-055 / Appendix B.1, B.2 / booking/battery.py).
Handles entering and updating vehicle battery percentage, state-of-charge tracking, and driving range calculations.
"""

import math
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.booking.validators import validate_battery_level_input
from app.models.charger import Charger, CurrentType
from app.models.station import Station
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.schemas.booking import (
    BatteryLevelResponse,
    ChargingCostEstimateResponse,
    ChargingTimeEstimateResponse,
    EnergyEstimateResponse,
)
from app.services.audit_service import AuditService


def compute_usable_range(
    battery_kwh: float,
    consumption_kwh_100km: float,
    current_soc: int,
    reserve: int = 10,
) -> float:
    """
    Compute usable driving range in km (Appendix B.1):
    max(0, (SoC_now - reserve) / 100 * battery_kWh) / (consumption_kWh_per_100km / 100),
    where reserve = 10 percentage points.
    """
    if consumption_kwh_100km <= 0 or battery_kwh <= 0:
        return 0.0
    factor = consumption_kwh_100km / 100.0
    effective_soc = max(0.0, float(current_soc - reserve))
    usable_kwh = (effective_soc / 100.0) * battery_kwh
    return round(usable_kwh / factor, 1)


def compute_estimated_range(
    battery_kwh: float,
    consumption_kwh_100km: float,
    current_soc: int | None = None,
) -> float:
    """
    Compute total estimated driving range in km based on current SoC (or 100% full battery).
    """
    if consumption_kwh_100km <= 0 or battery_kwh <= 0:
        return 0.0
    factor = consumption_kwh_100km / 100.0
    soc_pct = 100.0 if current_soc is None else float(current_soc)
    return round(((soc_pct / 100.0) * battery_kwh) / factor, 1)


def compute_energy_required(
    battery_kwh: float,
    current_soc: int,
    target_soc: int = 80,
    efficiency: float = 0.90,
) -> float:
    """
    Compute energy required in kWh to charge from current_soc to target_soc (Appendix B.1):
    (SoC_target - SoC_now) / 100 * battery_kWh / 0.90, where 0.90 is the assumed charging efficiency.
    Returns 0.0 if current_soc >= target_soc.
    """
    if current_soc >= target_soc or battery_kwh <= 0 or efficiency <= 0:
        return 0.0
    delta_soc = float(target_soc - current_soc)
    return round((delta_soc / 100.0 * battery_kwh) / efficiency, 2)


def estimate_energy_required(
    db: Session,
    user: User,
    vehicle_id: int,
    target_soc: int = 80,
) -> EnergyEstimateResponse:
    """Estimate energy needed to charge an owned vehicle to the requested SoC."""
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)
    if vehicle.current_soc is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter the vehicle's current battery level before requesting an energy estimate.",
        )

    _, validated_target = validate_battery_level_input(
        battery_level=vehicle.current_soc,
        target_soc=target_soc,
    )
    energy_required_kwh = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
    )
    return EnergyEstimateResponse(
        vehicle_id=vehicle.id,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
        battery_capacity_kwh=vehicle.battery_kwh,
        energy_required_kwh=energy_required_kwh,
        message="Energy estimate calculated successfully.",
    )


def compute_charging_time_minutes(
    energy_required_kwh: float,
    effective_charging_power_kw: float,
) -> float:
    """Estimate charging duration from energy required and effective power."""
    try:
        energy_value = float(energy_required_kwh)
        power_value = float(effective_charging_power_kw)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Energy and effective charging power must be numeric.",
        )
    if not math.isfinite(energy_value) or energy_value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Energy required must be a finite, non-negative value.",
        )
    if not math.isfinite(power_value) or power_value <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Effective charging power must be a finite value greater than zero.",
        )
    return round(energy_value / power_value * 60.0, 1)


def compute_slot_length_minutes(estimated_charging_time_minutes: float) -> int:
    """Round a non-negative estimate up to the next 15-minute slot boundary."""
    if isinstance(estimated_charging_time_minutes, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estimated charging time must be numeric.",
        )
    try:
        time_value = float(estimated_charging_time_minutes)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estimated charging time must be numeric.",
        )
    if not math.isfinite(time_value) or time_value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Estimated charging time must be a finite, non-negative value.",
        )
    return int(math.ceil(time_value / 15.0) * 15)


def compute_charging_cost(energy_required_kwh: float, price_per_kwh: float) -> float:
    """Calculate the estimated charging cost using a station's per-kWh tariff."""
    if isinstance(energy_required_kwh, bool) or isinstance(price_per_kwh, bool):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Energy required and price per kWh must be numeric.",
        )
    try:
        energy_value = float(energy_required_kwh)
        price_value = float(price_per_kwh)
    except (TypeError, ValueError, OverflowError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Energy required and price per kWh must be numeric.",
        )
    if not math.isfinite(energy_value) or energy_value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Energy required must be a finite, non-negative value.",
        )
    if not math.isfinite(price_value) or price_value < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Price per kWh must be a finite, non-negative value.",
        )
    return round(energy_value * price_value, 2)


def get_target_vehicle(
    db: Session,
    user: User,
    vehicle_id: int | None = None,
) -> Vehicle:
    """
    Find and authorize access to target vehicle for the current user.
    If vehicle_id is None, retrieves driver's primary default vehicle.
    Enforces driver ownership and role permissions.
    """
    if user.role not in [UserRole.DRIVER, UserRole.ADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers and administrators can access vehicle battery levels.",
        )

    if vehicle_id is not None:
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle with ID {vehicle_id} not found.",
            )
        # Check ownership: non-admin driver cannot modify another user's vehicle
        if user.role != UserRole.ADMIN and vehicle.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access or modify this vehicle.",
            )
        return vehicle

    # Fall back to user's default vehicle
    vehicle = (
        db.query(Vehicle)
        .filter(Vehicle.user_id == user.id, Vehicle.is_default.is_(True))
        .first()
    )
    if not vehicle:
        # Fall back to any vehicle owned by the driver
        vehicle = db.query(Vehicle).filter(Vehicle.user_id == user.id).first()

    if not vehicle:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Driver does not have any registered vehicles.",
        )

    return vehicle


def estimate_charging_time(
    db: Session,
    user: User,
    vehicle_id: int,
    charger_id: int,
    target_soc: int = 80,
) -> ChargingTimeEstimateResponse:
    """Estimate charge time using owned vehicle data and a charger's rated power."""
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)
    if vehicle.current_soc is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter the vehicle's current battery level before requesting a charging-time estimate.",
        )

    _, validated_target = validate_battery_level_input(
        battery_level=vehicle.current_soc,
        target_soc=target_soc,
    )
    charger = db.query(Charger).filter(Charger.id == charger_id).first()
    if charger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charger with ID {charger_id} not found.",
        )

    vehicle_power_kw = (
        vehicle.max_ac_kw
        if charger.current_type == CurrentType.AC
        else vehicle.max_dc_kw
    )
    if vehicle_power_kw <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Vehicle does not support {charger.current_type.value} charging.",
        )

    effective_power_kw = min(float(charger.power_kw), float(vehicle_power_kw))
    energy_required_kwh = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
    )
    charging_time_minutes = compute_charging_time_minutes(
        energy_required_kwh=energy_required_kwh,
        effective_charging_power_kw=effective_power_kw,
    )
    slot_length_minutes = compute_slot_length_minutes(charging_time_minutes)
    return ChargingTimeEstimateResponse(
        vehicle_id=vehicle.id,
        charger_id=charger.id,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
        energy_required_kwh=energy_required_kwh,
        effective_charging_power_kw=effective_power_kw,
        estimated_charging_time_minutes=charging_time_minutes,
        slot_length_minutes=slot_length_minutes,
        message="Charging time estimate calculated successfully.",
    )


def estimate_charging_cost(
    db: Session,
    user: User,
    vehicle_id: int,
    station_id: int,
    target_soc: int = 80,
) -> ChargingCostEstimateResponse:
    """Estimate charging cost using an owned vehicle and station tariff."""
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)
    if vehicle.current_soc is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter the vehicle's current battery level before requesting a cost estimate.",
        )
    _, validated_target = validate_battery_level_input(
        battery_level=vehicle.current_soc,
        target_soc=target_soc,
    )

    station = db.query(Station).filter(Station.id == station_id).first()
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found.",
        )
    if station.price_per_kwh is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Station tariff is not configured; charging cost cannot be estimated.",
        )

    energy_required_kwh = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
    )
    estimated_cost = compute_charging_cost(
        energy_required_kwh=energy_required_kwh,
        price_per_kwh=station.price_per_kwh,
    )
    return ChargingCostEstimateResponse(
        vehicle_id=vehicle.id,
        station_id=station.id,
        current_soc=vehicle.current_soc,
        target_soc=validated_target,
        energy_required_kwh=energy_required_kwh,
        price_per_kwh=station.price_per_kwh,
        estimated_cost=estimated_cost,
        message="Charging cost estimate calculated successfully.",
    )


def enter_battery_level(
    db: Session,
    user: User,
    vehicle_id: int | None,
    battery_level: int,
    target_soc: int | None = None,
    ip_address: str | None = None,
) -> BatteryLevelResponse:
    """
    Allow a driver to enter and update their current vehicle battery level (REQ-F3-01 / CS19-055).
    Stores the value on the vehicle, calculates usable range, checks low-battery trigger, and logs action.
    """
    validated_soc, validated_target = validate_battery_level_input(
        battery_level=battery_level,
        target_soc=target_soc if target_soc is not None else getattr(user, "default_target_battery", 80),
    )

    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)

    # Persist updated battery level
    vehicle.current_soc = validated_soc
    vehicle.target_soc = validated_target
    vehicle.battery_updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(vehicle)

    # Audit logging
    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="VEHICLE_BATTERY_UPDATE",
        resource=f"vehicles/{vehicle.id}",
        details=f"Updated battery level to {validated_soc}% (target SoC: {validated_target}%) for {vehicle.make} {vehicle.model}",
        ip_address=ip_address,
        commit=True,
    )

    low_threshold = getattr(user, "low_battery_threshold", 20)
    is_low = validated_soc <= low_threshold
    usable_range = compute_usable_range(
        battery_kwh=vehicle.battery_kwh,
        consumption_kwh_100km=vehicle.consumption_kwh_100km,
        current_soc=validated_soc,
    )
    estimated_range = compute_estimated_range(
        battery_kwh=vehicle.battery_kwh,
        consumption_kwh_100km=vehicle.consumption_kwh_100km,
        current_soc=validated_soc,
    )
    energy_req = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=validated_soc,
        target_soc=validated_target,
    )

    return BatteryLevelResponse(
        vehicle_id=vehicle.id,
        user_id=vehicle.user_id,
        make=vehicle.make,
        model=vehicle.model,
        registration_no=vehicle.registration_no,
        battery_kwh=vehicle.battery_kwh,
        current_soc=validated_soc,
        current_battery_percentage=validated_soc,
        target_soc=validated_target,
        usable_range_km=usable_range,
        estimated_range_km=estimated_range,
        energy_required_kwh=energy_req,
        is_low_battery=is_low,
        low_battery_threshold=low_threshold,
        battery_updated_at=vehicle.battery_updated_at,
        message="Vehicle battery level updated successfully.",
    )


def get_vehicle_battery(
    db: Session,
    user: User,
    vehicle_id: int | None = None,
) -> BatteryLevelResponse:
    """
    Retrieve current battery level, target SoC, and driving ranges for a vehicle (REQ-F3-01 / CS19-055).
    """
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)

    current_soc = vehicle.current_soc if vehicle.current_soc is not None else 100
    target_soc = vehicle.target_soc if vehicle.target_soc is not None else 80
    low_threshold = getattr(user, "low_battery_threshold", 20)

    usable_range = compute_usable_range(
        battery_kwh=vehicle.battery_kwh,
        consumption_kwh_100km=vehicle.consumption_kwh_100km,
        current_soc=current_soc,
    )
    estimated_range = compute_estimated_range(
        battery_kwh=vehicle.battery_kwh,
        consumption_kwh_100km=vehicle.consumption_kwh_100km,
        current_soc=current_soc,
    )
    energy_req = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=current_soc,
        target_soc=target_soc,
    )

    return BatteryLevelResponse(
        vehicle_id=vehicle.id,
        user_id=vehicle.user_id,
        make=vehicle.make,
        model=vehicle.model,
        registration_no=vehicle.registration_no,
        battery_kwh=vehicle.battery_kwh,
        current_soc=current_soc,
        current_battery_percentage=current_soc,
        target_soc=target_soc,
        usable_range_km=usable_range,
        estimated_range_km=estimated_range,
        energy_required_kwh=energy_req,
        is_low_battery=current_soc <= low_threshold,
        low_battery_threshold=low_threshold,
        battery_updated_at=vehicle.battery_updated_at,
        message="Current vehicle battery level retrieved successfully.",
    )
