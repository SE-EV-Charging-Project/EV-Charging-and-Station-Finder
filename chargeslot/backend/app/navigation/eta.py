"""
ETA versus Slot Check Service (REQ-F2-27 / CS19-053).

Compares a driver's estimated arrival time (with current traffic) with the
confirmed booking's slot start time. Warns the driver and offers reschedule,
extension, or cancellation options if projected late beyond the grace period.
"""

from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.discovery.search import haversine_distance
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.routes import (
    calculate_route_preview,
    normalize_traffic_condition,
    validate_coordinates,
)
from app.schemas.navigation import (
    ETASlotCheckResponse,
    ETASlotStatus,
    RescheduleSlotOption,
    TrafficCondition,
)

DEFAULT_GRACE_PERIOD_MINUTES = 15


def ensure_utc(dt: datetime) -> datetime:
    """Ensures a datetime object is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def find_reschedule_options(
    db: Session,
    station: Station,
    connector_id: int | None,
    after_time: datetime,
    limit: int = 3,
) -> list[RescheduleSlotOption]:
    """
    Finds upcoming candidate slots at the same station starting after the projected arrival time.
    """
    options: list[RescheduleSlotOption] = []
    connectors_query = (
        db.query(Connector)
        .join(Charger, Connector.charger_id == Charger.id)
        .filter(Charger.station_id == station.id)
        .filter(Charger.is_active == True)
        .filter(Charger.is_out_of_service == False)
    )
    if connector_id:
        connectors_query = connectors_query.filter(Connector.id == connector_id)

    connectors = connectors_query.all()
    if not connectors:
        connectors = (
            db.query(Connector)
            .join(Charger, Connector.charger_id == Charger.id)
            .filter(Charger.station_id == station.id)
            .all()
        )

    # Suggest 15-minute slot blocks starting at 15-min intervals after arrival
    base_minute = (after_time.minute // 15 + 1) * 15
    start_candidate = after_time.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=base_minute)

    for i in range(limit):
        slot_start = start_candidate + timedelta(minutes=i * 30)
        slot_end = slot_start + timedelta(minutes=30)
        chosen_conn = connectors[i % len(connectors)] if connectors else None

        options.append(
            RescheduleSlotOption(
                slot_id=None,
                connector_id=chosen_conn.id if chosen_conn else (connector_id or 1),
                connector_type=(
                    chosen_conn.connector_type.value
                    if chosen_conn and hasattr(chosen_conn.connector_type, "value")
                    else (str(chosen_conn.connector_type) if chosen_conn else "CCS2")
                ),
                start_time=slot_start,
                end_time=slot_end,
                available=True,
            )
        )

    return options


def check_driver_eta_versus_slot(
    db: Session,
    user: User,
    booking_id: int,
    driver_latitude: float,
    driver_longitude: float,
    traffic_condition: str | None = None,
    current_time: datetime | None = None,
    grace_period_minutes: int = DEFAULT_GRACE_PERIOD_MINUTES,
) -> ETASlotCheckResponse:
    """
    Compares driver's estimated arrival time with slot start time (REQ-F2-27 / CS19-053).

    Enforces:
    - Coordinate validation [-90, 90] and [-180, 180].
    - Booking existence and active status.
    - RBAC isolation: drivers can access only their own bookings; operators only their own station's bookings.
    - 15-minute grace period evaluation (BR-06 / REQ-F3-25).
    - Returns reschedule/extend/cancel action options and warnings when projected late.
    """
    driver_lat, driver_lon = validate_coordinates(driver_latitude, driver_longitude)
    if grace_period_minutes < 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Grace period minutes must be non-negative.",
        )

    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with ID {booking_id} not found",
        )

    # RBAC Access Controls
    if user.role == UserRole.DRIVER:
        if booking.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permission denied: cannot access another driver's booking",
            )
    elif user.role == UserRole.OPERATOR:
        # Operator can only access bookings belonging to stations they operate
        if booking.station_id is not None:
            station_check = db.query(Station).filter(Station.id == booking.station_id).first()
            if station_check and station_check.operator_id != user.id:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Permission denied: cannot access booking for another operator's station",
                )
    # Admin has full access

    # Check booking status applicability
    inactive_statuses = {
        BookingStatus.CANCELLED,
        BookingStatus.COMPLETED,
        BookingStatus.NO_SHOW,
        BookingStatus.EXPIRED,
    }
    if booking.status in inactive_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot check ETA for booking with inactive status '{booking.status.value}'.",
        )

    # Station retrieval
    station: Station | None = None
    if booking.station_id:
        station = db.query(Station).filter(Station.id == booking.station_id).first()
    elif booking.connector and booking.connector.charger:
        station = db.query(Station).filter(Station.id == booking.connector.charger.station_id).first()

    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charging station for booking #{booking.id} could not be resolved.",
        )

    # Evaluation timestamps
    evaluation_time = ensure_utc(current_time) if current_time else datetime.now(timezone.utc)
    slot_start = ensure_utc(booking.start_time)
    slot_end = ensure_utc(booking.end_time)
    grace_deadline = slot_start + timedelta(minutes=grace_period_minutes)

    # Route and travel time computation
    route_preview = calculate_route_preview(
        db=db,
        user=user,
        station_id=station.id,
        origin_latitude=driver_lat,
        origin_longitude=driver_lon,
        traffic_condition=traffic_condition,
    )

    travel_time_minutes = route_preview.estimated_travel_time_minutes
    road_distance_km = route_preview.road_distance_km
    estimated_arrival = evaluation_time + timedelta(minutes=travel_time_minutes)

    # Determine lateness
    reschedule_options: list[RescheduleSlotOption] = []
    if estimated_arrival <= slot_start:
        status_value = ETASlotStatus.ON_TIME
        is_late = False
        projected_late_beyond_grace = False
        delay_minutes = 0.0
        warning_msg = None
        action_options = []
        can_reschedule = False
        can_extend = False
        can_cancel = False
    elif estimated_arrival <= grace_deadline:
        status_value = ETASlotStatus.LATE_WITHIN_GRACE
        is_late = True
        projected_late_beyond_grace = False
        delay_minutes = round((estimated_arrival - slot_start).total_seconds() / 60.0, 1)
        warning_msg = (
            f"Notice: Projected arrival ({estimated_arrival.strftime('%H:%M')}) is {delay_minutes:.1f} minutes "
            f"after slot start ({slot_start.strftime('%H:%M')}), but within the {grace_period_minutes}-minute grace period."
        )
        action_options = ["reschedule", "extend", "cancel"]
        can_reschedule = True
        can_extend = True
        can_cancel = True
        reschedule_options = find_reschedule_options(
            db=db,
            station=station,
            connector_id=booking.connector_id,
            after_time=estimated_arrival,
        )
    else:
        status_value = ETASlotStatus.LATE_BEYOND_GRACE
        is_late = True
        projected_late_beyond_grace = True
        delay_minutes = round((estimated_arrival - slot_start).total_seconds() / 60.0, 1)
        warning_msg = (
            f"Warning: Projected arrival ({estimated_arrival.strftime('%H:%M')}) is {delay_minutes:.1f} minutes late, "
            f"exceeding the {grace_period_minutes}-minute grace period (deadline {grace_deadline.strftime('%H:%M')}). "
            f"Your reservation will be marked No-Show unless rescheduled or extended."
        )
        action_options = ["reschedule", "extend", "cancel"]
        can_reschedule = True
        can_extend = True
        can_cancel = True
        reschedule_options = find_reschedule_options(
            db=db,
            station=station,
            connector_id=booking.connector_id,
            after_time=estimated_arrival,
        )

    now = datetime.now(timezone.utc)
    return ETASlotCheckResponse(
        booking_id=booking.id,
        booking_status=booking.status.value if hasattr(booking.status, "value") else str(booking.status),
        station_id=station.id,
        station_name=station.name,
        connector_id=booking.connector_id,
        slot_start_time=slot_start,
        slot_end_time=slot_end,
        grace_period_minutes=grace_period_minutes,
        grace_period_deadline=grace_deadline,
        current_time=evaluation_time,
        driver_latitude=driver_lat,
        driver_longitude=driver_lon,
        road_distance_km=road_distance_km,
        estimated_travel_time_minutes=travel_time_minutes,
        estimated_arrival_time=estimated_arrival,
        is_late=is_late,
        projected_late_beyond_grace=projected_late_beyond_grace,
        delay_minutes=delay_minutes,
        status=status_value.value,
        warning_message=warning_msg,
        action_options=action_options,
        can_reschedule=can_reschedule,
        can_extend=can_extend,
        can_cancel=can_cancel,
        reschedule_options=reschedule_options,
        checked_at=now,
    )
