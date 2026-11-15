from datetime import datetime, time, timedelta, timezone

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.booking.slots import (
    ACTIVE_BOOKING_STATUSES,
    SLOT_INTERVAL_MINUTES,
    _slot_claims_for_booking,
)
from app.booking.state import transition_booking_status
from app.discovery.search import haversine_distance
from app.models.booking import Booking, BookingStatus
from app.models.booking_payment_event import (
    BookingPaymentEvent,
    BookingPaymentEventStatus,
)
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.charging_session_start_command import (
    ChargingSessionStartCommand,
    SessionStartCommandStatus,
)
from app.models.maintenance import MaintenanceWindow
from app.models.station import Station, StationStatus
from app.models.vehicle import Vehicle
from app.services.notification_service import create_in_app_notification
from app.stations.slots import does_slot_overlap_window, ensure_utc, parse_operating_hours


def _slot_starts(booking: Booking) -> list[datetime]:
    slot_start = ensure_utc(booking.start_time)
    slot_end = ensure_utc(booking.end_time)
    starts: list[datetime] = []
    while slot_start < slot_end:
        starts.append(slot_start)
        slot_start += timedelta(minutes=SLOT_INTERVAL_MINUTES)
    return starts


def _fits_opening_hours(
    station: Station,
    start_time: datetime,
    end_time: datetime,
) -> bool:
    opening, closing = parse_operating_hours(station.operating_hours)
    start = ensure_utc(start_time)
    end = ensure_utc(end_time)
    if start.date() != end.date():
        return False
    start_minutes = start.hour * 60 + start.minute
    end_minutes = end.hour * 60 + end.minute
    opening_minutes = opening.hour * 60 + opening.minute
    closing_minutes = closing.hour * 60 + closing.minute
    if closing == time(23, 59, 59):
        closing_minutes = 24 * 60
    return opening_minutes <= start_minutes and end_minutes <= closing_minutes


def _candidate_is_available(
    db: Session,
    *,
    booking: Booking,
    charger: Charger,
) -> bool:
    start_time = ensure_utc(booking.start_time)
    end_time = ensure_utc(booking.end_time)
    conflicting_charger_booking = (
        db.query(Booking.id)
        .filter(
            Booking.id != booking.id,
            Booking.charger_id == charger.id,
            Booking.status.in_(ACTIVE_BOOKING_STATUSES),
            Booking.start_time < end_time,
            Booking.end_time > start_time,
            or_(
                Booking.status != BookingStatus.HELD,
                Booking.hold_expires_at.is_(None),
                Booking.hold_expires_at > datetime.now(timezone.utc),
            ),
        )
        .first()
    )
    if conflicting_charger_booking is not None:
        return False
    if booking.vehicle_id is not None:
        conflicting_vehicle_booking = (
            db.query(Booking.id)
            .filter(
                Booking.id != booking.id,
                Booking.vehicle_id == booking.vehicle_id,
                Booking.status.in_(ACTIVE_BOOKING_STATUSES),
                Booking.start_time < end_time,
                Booking.end_time > start_time,
                or_(
                    Booking.status != BookingStatus.HELD,
                    Booking.hold_expires_at.is_(None),
                    Booking.hold_expires_at > datetime.now(timezone.utc),
                ),
            )
            .first()
        )
        if conflicting_vehicle_booking is not None:
            return False

    slot_starts = _slot_starts(booking)
    for slot_start in slot_starts:
        if (
            db.query(BookingSlotClaim.id)
            .filter(
                BookingSlotClaim.booking_id != booking.id,
                BookingSlotClaim.charger_id == charger.id,
                BookingSlotClaim.slot_start_time == slot_start,
            )
            .first()
            is not None
        ):
            return False
        if booking.vehicle_id is not None and (
            db.query(BookingSlotClaim.id)
            .filter(
                BookingSlotClaim.booking_id != booking.id,
                BookingSlotClaim.vehicle_id == booking.vehicle_id,
                BookingSlotClaim.slot_start_time == slot_start,
            )
            .first()
            is not None
        ):
            return False

    windows = (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.station_id == charger.station_id,
            MaintenanceWindow.start_time < end_time,
            MaintenanceWindow.end_time > start_time,
            or_(
                MaintenanceWindow.charger_id.is_(None),
                MaintenanceWindow.charger_id == charger.id,
            ),
        )
        .all()
    )
    return not any(
        does_slot_overlap_window(
            start_time,
            end_time,
            window.start_time,
            window.end_time,
        )
        for window in windows
    )


def _find_alternative(
    db: Session,
    *,
    booking: Booking,
    failed_charger_id: int,
) -> tuple[Station, Charger, Connector] | None:
    if booking.vehicle_id is None or booking.station_id is None:
        return None
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    source_station = db.query(Station).filter(Station.id == booking.station_id).first()
    if vehicle is None or source_station is None:
        return None

    choices = (
        db.query(Station, Charger, Connector)
        .join(Charger, Charger.station_id == Station.id)
        .join(Connector, Connector.charger_id == Charger.id)
        .filter(
            Station.status == StationStatus.APPROVED,
            Station.is_active.is_(True),
            Charger.id != failed_charger_id,
            Charger.is_active.is_(True),
            Charger.is_out_of_service.is_(False),
            Connector.connector_type == vehicle.connector_type,
            Connector.status == ConnectorStatus.AVAILABLE,
        )
        .all()
    )
    choices.sort(
        key=lambda choice: (
            haversine_distance(
                source_station.latitude,
                source_station.longitude,
                choice[0].latitude,
                choice[0].longitude,
            ),
            choice[0].id,
            choice[1].id,
            choice[2].id,
        )
    )
    start_time = ensure_utc(booking.start_time)
    end_time = ensure_utc(booking.end_time)
    for station, charger, connector in choices:
        vehicle_power_kw = (
            vehicle.max_ac_kw
            if charger.current_type == CurrentType.AC
            else vehicle.max_dc_kw
        )
        if charger.power_kw <= 0 or vehicle_power_kw <= 0:
            continue
        if not _fits_opening_hours(station, start_time, end_time):
            continue
        if not _candidate_is_available(db, booking=booking, charger=charger):
            continue
        return station, charger, connector
    return None


def _mark_refund_due(db: Session, booking: Booking) -> float:
    payments = (
        db.query(BookingPaymentEvent)
        .filter(
            BookingPaymentEvent.booking_id == booking.id,
            BookingPaymentEvent.status == BookingPaymentEventStatus.SUCCEEDED,
        )
        .with_for_update()
        .all()
    )
    refund_amount = 0.0
    for payment in payments:
        payment.refund_due = True
        refund_amount += payment.amount_inr
    return round(refund_amount, 2)


def handle_faulted_connector(
    db: Session,
    *,
    connector: Connector,
    charger: Charger,
    fault_event_id: int,
    now: datetime | None = None,
) -> list[int]:
    now_utc = ensure_utc(now or datetime.now(timezone.utc))
    affected_bookings = (
        db.query(Booking)
        .filter(
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.REASSIGNED]
            ),
            Booking.end_time > now_utc,
            or_(
                Booking.connector_id == connector.id,
                and_(
                    Booking.charger_id == charger.id,
                    Booking.connector_id.is_(None),
                ),
            ),
        )
        .order_by(Booking.id.asc())
        .with_for_update()
        .all()
    )
    processed_ids: list[int] = []
    for booking in affected_bookings:
        pending_start_commands = (
            db.query(ChargingSessionStartCommand)
            .filter(
                ChargingSessionStartCommand.booking_id == booking.id,
                ChargingSessionStartCommand.status.in_(
                    [
                        SessionStartCommandStatus.PENDING,
                        SessionStartCommandStatus.ACCEPTED,
                    ]
                ),
            )
            .with_for_update()
            .all()
        )
        for command in pending_start_commands:
            command.status = SessionStartCommandStatus.FAILED
            command.error_code = "ConnectorFaulted"
            command.responded_at = now_utc
        alternative = _find_alternative(
            db,
            booking=booking,
            failed_charger_id=charger.id,
        )
        db.query(BookingSlotClaim).filter(
            BookingSlotClaim.booking_id == booking.id
        ).delete(synchronize_session=False)
        if alternative is None:
            transition_booking_status(booking, BookingStatus.CANCELLED)
            booking.cancellation_fee_amount = 0.0
            refund_amount = _mark_refund_due(db, booking)
            create_in_app_notification(
                db,
                user_id=booking.user_id,
                notification_type="booking_cancelled",
                title="Booking cancelled after charger fault",
                message=(
                    "No compatible available alternative was found. Your booking "
                    f"was cancelled and INR {refund_amount:.2f} is due for refund."
                ),
                payload={
                    "booking_id": booking.id,
                    "refund_due_inr": refund_amount,
                    "fault_event_id": fault_event_id,
                },
                dedupe_key=f"charger-fault:{fault_event_id}:booking:{booking.id}",
            )
        else:
            station, alternative_charger, alternative_connector = alternative
            transition_booking_status(booking, BookingStatus.REASSIGNED)
            booking.station_id = station.id
            booking.charger_id = alternative_charger.id
            booking.connector_id = alternative_connector.id
            booking.checked_in_at = None
            db.add_all(_slot_claims_for_booking(booking))
            db.flush()
            create_in_app_notification(
                db,
                user_id=booking.user_id,
                notification_type="booking_reassigned",
                title="Booking moved to an alternative charger",
                message=(
                    f"Your booking was moved to {station.name} at "
                    f"{station.address}. Please check in again at the new location."
                ),
                payload={
                    "booking_id": booking.id,
                    "station_id": station.id,
                    "station_name": station.name,
                    "address": station.address,
                    "charger_id": alternative_charger.id,
                    "connector_id": alternative_connector.id,
                    "fault_event_id": fault_event_id,
                },
                dedupe_key=f"charger-fault:{fault_event_id}:booking:{booking.id}",
            )
        processed_ids.append(booking.id)
    return processed_ids
