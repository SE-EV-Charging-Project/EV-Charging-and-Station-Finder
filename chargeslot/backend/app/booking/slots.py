"""Compatible charging-slot recommendation and manual booking (REQ-F3-10/11)."""

from datetime import date, datetime, time, timedelta, timezone
import math

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.booking.battery import (
    compute_charging_cost,
    compute_charging_time_minutes,
    compute_energy_required,
    compute_slot_length_minutes,
    get_target_vehicle,
)
from app.booking.validators import validate_battery_level_input
from app.models.booking import Booking, BookingStatus
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.maintenance import MaintenanceWindow
from app.models.station import Station, StationStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.booking import (
    ManualSlotBookingResponse,
    RecommendedSlotItem,
    RecommendedSlotsResponse,
    SlotHoldResponse,
)
from app.services.audit_service import AuditService
from app.stations.slots import (
    does_slot_overlap_window,
    ensure_utc,
    parse_operating_hours,
)

SLOT_INTERVAL_MINUTES = 15
ACTIVE_BOOKING_STATUSES = (
    BookingStatus.HELD,
    BookingStatus.CONFIRMED,
    BookingStatus.ACTIVE,
)


def _validate_estimate_inputs(
    db: Session,
    user: User,
    vehicle_id: int,
    target_soc: int,
) -> tuple[Vehicle, int]:
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)
    if vehicle.current_soc is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Enter the vehicle's current battery level before selecting a slot.",
        )

    _, validated_target = validate_battery_level_input(
        battery_level=vehicle.current_soc,
        target_soc=target_soc,
    )
    if validated_target <= vehicle.current_soc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target SoC must be greater than the vehicle's current SoC.",
        )
    return vehicle, validated_target


def _slot_length_for_vehicle(
    vehicle: Vehicle,
    charger: Charger,
    target_soc: int,
) -> tuple[float, int, float] | None:
    if (
        vehicle.current_soc is None
        or not charger.is_active
        or charger.is_out_of_service
        or charger.power_kw <= 0
    ):
        return None

    vehicle_power_kw = (
        vehicle.max_ac_kw
        if charger.current_type == CurrentType.AC
        else vehicle.max_dc_kw
    )
    if vehicle_power_kw <= 0:
        return None

    effective_power_kw = min(float(charger.power_kw), float(vehicle_power_kw))
    energy_required_kwh = compute_energy_required(
        battery_kwh=vehicle.battery_kwh,
        current_soc=vehicle.current_soc,
        target_soc=target_soc,
    )
    charging_time_minutes = compute_charging_time_minutes(
        energy_required_kwh=energy_required_kwh,
        effective_charging_power_kw=effective_power_kw,
    )
    slot_length_minutes = compute_slot_length_minutes(charging_time_minutes)
    if slot_length_minutes <= 0:
        return None
    return energy_required_kwh, slot_length_minutes, charging_time_minutes


def _overlaps_existing_booking(
    charger_id: int,
    start_time: datetime,
    end_time: datetime,
    bookings: list[Booking],
) -> bool:
    return any(
        (booking.charger_id is None or booking.charger_id == charger_id)
        and max(start_time, ensure_utc(booking.start_time))
        < min(end_time, ensure_utc(booking.end_time))
        for booking in bookings
    )


def _release_stale_slot_claims(db: Session, now_utc: datetime) -> None:
    expired_hold_ids = [
        booking_id
        for (booking_id,) in (
            db.query(Booking.id)
            .filter(
                Booking.status == BookingStatus.HELD,
                Booking.hold_expires_at <= now_utc,
            )
            .all()
        )
    ]
    if expired_hold_ids:
        db.query(Booking).filter(Booking.id.in_(expired_hold_ids)).update(
            {Booking.status: BookingStatus.EXPIRED},
            synchronize_session=False,
        )

    stale_booking_ids = select(Booking.id).where(
            or_(
                Booking.status.notin_(ACTIVE_BOOKING_STATUSES),
                Booking.end_time <= now_utc,
                and_(
                    Booking.status == BookingStatus.HELD,
                    Booking.hold_expires_at <= now_utc,
                ),
            )
    )
    deleted_count = (
        db.query(BookingSlotClaim)
        .filter(BookingSlotClaim.booking_id.in_(stale_booking_ids))
        .delete(synchronize_session=False)
    )
    if expired_hold_ids or deleted_count:
        db.commit()


def _slot_claims_for_booking(booking: Booking) -> list[BookingSlotClaim]:
    if booking.charger_id is None:
        raise RuntimeError("Cannot claim a booking without a charger.")

    start_time = ensure_utc(booking.start_time)
    end_time = ensure_utc(booking.end_time)
    if (
        start_time.minute % SLOT_INTERVAL_MINUTES != 0
        or start_time.second != 0
        or start_time.microsecond != 0
        or end_time.minute % SLOT_INTERVAL_MINUTES != 0
        or end_time.second != 0
        or end_time.microsecond != 0
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Booking times must align to 15-minute slot boundaries.",
        )

    claims: list[BookingSlotClaim] = []
    slot_start = start_time
    while slot_start < end_time:
        claims.append(
            BookingSlotClaim(
                charger_id=booking.charger_id,
                slot_start_time=slot_start,
                booking_id=booking.id,
            )
        )
        slot_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)
    return claims


def _candidate_slots(
    db: Session,
    user: User,
    vehicle_id: int,
    target_soc: int,
    slot_date: date,
    station_id: int | None = None,
) -> list[RecommendedSlotItem]:
    vehicle, validated_target = _validate_estimate_inputs(
        db=db,
        user=user,
        vehicle_id=vehicle_id,
        target_soc=target_soc,
    )
    now_utc = datetime.now(timezone.utc)
    if slot_date < now_utc.date():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Slot date cannot be in the past.",
        )

    station_query = db.query(Station).filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )
    if station_id is not None:
        station_query = station_query.filter(Station.id == station_id)
    stations = station_query.order_by(Station.id.asc()).all()
    if station_id is not None and not stations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active approved station with ID {station_id} not found.",
        )
    if not stations:
        return []

    station_ids = [station.id for station in stations]
    compatible_chargers = (
        db.query(Charger)
        .join(Connector, Connector.charger_id == Charger.id)
        .filter(
            Charger.station_id.in_(station_ids),
            Charger.is_active.is_(True),
            Charger.is_out_of_service.is_(False),
            Connector.connector_type == vehicle.connector_type,
            Connector.status.notin_(
                [
                    ConnectorStatus.RESERVED,
                    ConnectorStatus.FAULTED,
                    ConnectorStatus.OFFLINE,
                ]
            ),
        )
        .distinct()
        .order_by(Charger.id.asc())
        .all()
    )
    chargers_by_station: dict[int, list[Charger]] = {}
    for charger in compatible_chargers:
        chargers_by_station.setdefault(charger.station_id, []).append(charger)

    day_start = datetime.combine(slot_date, time.min, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    windows = (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.station_id.in_(station_ids),
            MaintenanceWindow.start_time < day_end,
            MaintenanceWindow.end_time > day_start,
        )
        .all()
    )
    windows_by_station: dict[int, list[MaintenanceWindow]] = {}
    for window in windows:
        windows_by_station.setdefault(window.station_id, []).append(window)

    bookings = (
        db.query(Booking)
        .filter(
            Booking.station_id.in_(station_ids),
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            or_(
                Booking.status != BookingStatus.HELD,
                Booking.hold_expires_at.is_(None),
                Booking.hold_expires_at > now_utc,
            ),
            Booking.start_time < day_end,
            Booking.end_time > day_start,
        )
        .all()
    )
    bookings_by_station: dict[int, list[Booking]] = {}
    for booking in bookings:
        if booking.station_id is not None:
            bookings_by_station.setdefault(booking.station_id, []).append(booking)

    candidates: list[RecommendedSlotItem] = []
    for station in stations:
        open_time, close_time = parse_operating_hours(station.operating_hours)
        opening = datetime.combine(slot_date, open_time, tzinfo=timezone.utc)
        closing = (
            day_end
            if close_time == time(23, 59, 59)
            else datetime.combine(slot_date, close_time, tzinfo=timezone.utc)
        )
        if closing <= opening:
            continue

        opening_minutes = open_time.hour * 60 + open_time.minute
        first_grid_minute = (
            (opening_minutes + SLOT_INTERVAL_MINUTES - 1)
            // SLOT_INTERVAL_MINUTES
            * SLOT_INTERVAL_MINUTES
        )
        first_candidate_start = day_start + timedelta(minutes=first_grid_minute)

        for charger in chargers_by_station.get(station.id, []):
            estimate = _slot_length_for_vehicle(
                vehicle=vehicle,
                charger=charger,
                target_soc=validated_target,
            )
            if estimate is None:
                continue
            energy_required_kwh, slot_length_minutes, charging_time_minutes = estimate
            duration = timedelta(minutes=slot_length_minutes)
            candidate_start = first_candidate_start
            while candidate_start + duration <= closing:
                slot_end = candidate_start + duration
                if candidate_start > now_utc:
                    overlaps_maintenance = any(
                        (window.charger_id is None or window.charger_id == charger.id)
                        and does_slot_overlap_window(
                            candidate_start,
                            slot_end,
                            window.start_time,
                            window.end_time,
                        )
                        for window in windows_by_station.get(station.id, [])
                    )
                    overlaps_booking = _overlaps_existing_booking(
                        charger_id=charger.id,
                        start_time=candidate_start,
                        end_time=slot_end,
                        bookings=bookings_by_station.get(station.id, []),
                    )
                    if not overlaps_maintenance and not overlaps_booking:
                        price = station.price_per_kwh
                        cost = (
                            compute_charging_cost(energy_required_kwh, price)
                            if price is not None
                            else None
                        )
                        candidates.append(
                            RecommendedSlotItem(
                                rank=0,
                                station_id=station.id,
                                station_name=station.name,
                                charger_id=charger.id,
                                start_time=candidate_start,
                                end_time=slot_end,
                                energy_required_kwh=energy_required_kwh,
                                estimated_charging_time_minutes=charging_time_minutes,
                                slot_length_minutes=slot_length_minutes,
                                price_per_kwh=price,
                                estimated_cost=cost,
                            )
                        )
                candidate_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)

    # Earlier starts rank first; ties prefer configured lower tariffs, then shorter slots.
    candidates.sort(
        key=lambda item: (
            item.start_time,
            item.price_per_kwh is None,
            item.price_per_kwh if item.price_per_kwh is not None else math.inf,
            item.slot_length_minutes,
            item.station_id,
            item.charger_id,
        )
    )
    return [
        item.model_copy(update={"rank": rank})
        for rank, item in enumerate(candidates, start=1)
    ]


def recommend_slots(
    db: Session,
    user: User,
    vehicle_id: int,
    slot_date: date,
    target_soc: int = 80,
    station_id: int | None = None,
    limit: int = 50,
) -> RecommendedSlotsResponse:
    items = _candidate_slots(
        db=db,
        user=user,
        vehicle_id=vehicle_id,
        target_soc=target_soc,
        slot_date=slot_date,
        station_id=station_id,
    )
    return RecommendedSlotsResponse(
        total=len(items),
        items=items[:limit],
    )


def _create_slot_booking(
    db: Session,
    user: User,
    station_id: int,
    vehicle_id: int,
    charger_id: int,
    start_time: datetime,
    target_soc: int = 80,
    ip_address: str | None = None,
    booking_status: BookingStatus = BookingStatus.CONFIRMED,
) -> tuple[Booking, float, int, float]:
    _release_stale_slot_claims(db, datetime.now(timezone.utc))
    vehicle, validated_target = _validate_estimate_inputs(
        db=db,
        user=user,
        vehicle_id=vehicle_id,
        target_soc=target_soc,
    )
    station = (
        db.query(Station)
        .filter(Station.id == station_id)
        .with_for_update()
        .first()
    )
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found.",
        )
    if station.status != StationStatus.APPROVED or not station.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Bookings are not available for this station.",
        )

    charger = (
        db.query(Charger)
        .filter(
            Charger.id == charger_id,
            Charger.station_id == station_id,
        )
        .first()
    )
    if charger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charger with ID {charger_id} was not found at station {station_id}.",
        )

    has_compatible_bookable_connector = (
        db.query(Connector.id)
        .filter(
            Connector.charger_id == charger.id,
            Connector.connector_type == vehicle.connector_type,
            Connector.status.notin_(
                [
                    ConnectorStatus.RESERVED,
                    ConnectorStatus.FAULTED,
                    ConnectorStatus.OFFLINE,
                ]
            ),
        )
        .first()
        is not None
    )
    if not has_compatible_bookable_connector:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected charger has no operational connector compatible with this vehicle.",
        )

    estimate = _slot_length_for_vehicle(vehicle, charger, validated_target)
    if estimate is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Selected charger cannot charge this vehicle.",
        )
    energy_required_kwh, slot_length_minutes, charging_time_minutes = estimate
    normalized_start = ensure_utc(start_time)
    candidates = _candidate_slots(
        db=db,
        user=user,
        vehicle_id=vehicle_id,
        target_soc=validated_target,
        slot_date=normalized_start.date(),
        station_id=station_id,
    )
    selected_slot = next(
        (
            item
            for item in candidates
            if item.charger_id == charger_id and item.start_time == normalized_start
        ),
        None,
    )
    if selected_slot is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Selected slot is outside operating hours, blocked, or already booked.",
        )

    now_utc = datetime.now(timezone.utc)
    booking = Booking(
        user_id=user.id,
        vehicle_id=vehicle.id,
        station_id=station.id,
        charger_id=charger.id,
        start_soc=vehicle.current_soc,
        target_soc=validated_target,
        est_energy_kwh=energy_required_kwh,
        est_duration_min=slot_length_minutes,
        booking_type="manual",
        status=booking_status,
        start_time=selected_slot.start_time,
        end_time=selected_slot.end_time,
        hold_expires_at=(
            now_utc + timedelta(minutes=5)
            if booking_status == BookingStatus.HELD
            else None
        ),
    )
    db.add(booking)
    db.flush()
    db.add_all(_slot_claims_for_booking(booking))
    try:
        db.flush()
    except IntegrityError as error:
        db.rollback()
        message = str(error.orig)
        postgres_constraint = getattr(
            getattr(error.orig, "diag", None),
            "constraint_name",
            None,
        )
        if (
            postgres_constraint == "uq_booking_slot_claim_charger_start"
            or "booking_slot_claims.charger_id, booking_slot_claims.slot_start_time"
            in message
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Selected slot was just booked by another request.",
            ) from error
        raise
    db.commit()
    db.refresh(booking)

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action=(
            "SLOT_HOLD_CREATED"
            if booking_status == BookingStatus.HELD
            else "MANUAL_BOOKING_CREATED"
        ),
        resource=f"Booking:{booking.id}",
        details=(
            f"{'Slot hold' if booking_status == BookingStatus.HELD else 'Manual booking'} "
            f"{booking.id} created for charger {charger.id} "
            f"from {booking.start_time.isoformat()} to {booking.end_time.isoformat()}."
        ),
        ip_address=ip_address,
    )

    return booking, energy_required_kwh, slot_length_minutes, charging_time_minutes


def create_manual_slot_booking(
    db: Session,
    user: User,
    station_id: int,
    vehicle_id: int,
    charger_id: int,
    start_time: datetime,
    target_soc: int = 80,
    ip_address: str | None = None,
) -> ManualSlotBookingResponse:
    booking, energy_required_kwh, slot_length_minutes, charging_time_minutes = (
        _create_slot_booking(
            db=db,
            user=user,
            station_id=station_id,
            vehicle_id=vehicle_id,
            charger_id=charger_id,
            start_time=start_time,
            target_soc=target_soc,
            ip_address=ip_address,
        )
    )
    return ManualSlotBookingResponse(
        booking_id=booking.id,
        station_id=booking.station_id,
        charger_id=booking.charger_id,
        vehicle_id=booking.vehicle_id,
        start_soc=booking.start_soc,
        target_soc=booking.target_soc,
        energy_required_kwh=energy_required_kwh,
        estimated_charging_time_minutes=charging_time_minutes,
        slot_length_minutes=slot_length_minutes,
        start_time=ensure_utc(booking.start_time),
        end_time=ensure_utc(booking.end_time),
        status=booking.status.value,
    )


def create_slot_hold(
    db: Session,
    user: User,
    station_id: int,
    vehicle_id: int,
    charger_id: int,
    start_time: datetime,
    target_soc: int = 80,
    ip_address: str | None = None,
) -> SlotHoldResponse:
    booking, _, _, _ = _create_slot_booking(
        db=db,
        user=user,
        station_id=station_id,
        vehicle_id=vehicle_id,
        charger_id=charger_id,
        start_time=start_time,
        target_soc=target_soc,
        ip_address=ip_address,
        booking_status=BookingStatus.HELD,
    )
    if booking.hold_expires_at is None:
        raise RuntimeError("Persisted slot hold is missing its expiration time.")
    return SlotHoldResponse(
        booking_id=booking.id,
        station_id=booking.station_id,
        charger_id=booking.charger_id,
        vehicle_id=booking.vehicle_id,
        start_time=ensure_utc(booking.start_time),
        end_time=ensure_utc(booking.end_time),
        status=booking.status.value,
        hold_expires_at=ensure_utc(booking.hold_expires_at),
    )
