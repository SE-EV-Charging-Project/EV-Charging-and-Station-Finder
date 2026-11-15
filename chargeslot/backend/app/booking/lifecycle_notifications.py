from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.services.notification_service import create_in_app_notification
from app.stations.slots import ensure_utc

BOOKING_REMINDER_LEAD = timedelta(minutes=30)
IDLE_FEE_REMINDER_DELAY = timedelta(minutes=5)
IDLE_FEE_START_DELAY = timedelta(minutes=10)


def _update_idle_fee_amount(
    booking: Booking,
    *,
    through: datetime,
) -> None:
    if booking.idle_fee_started_at is None:
        return
    started_at = ensure_utc(booking.idle_fee_started_at)
    elapsed_seconds = max(0.0, (ensure_utc(through) - started_at).total_seconds())
    booking.idle_fee_amount = round(
        elapsed_seconds / 60 * settings.IDLE_FEE_RATE_INR_PER_MINUTE,
        2,
    )


def sweep_booking_reminders_and_idle_fees(
    db: Session,
    *,
    now: datetime | None = None,
) -> tuple[list[int], list[int]]:
    now_utc = ensure_utc(now or datetime.now(timezone.utc))
    booking_reminders: list[int] = []
    idle_fee_updates: list[int] = []

    upcoming_bookings = (
        db.query(Booking)
        .filter(
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.REASSIGNED]),
            Booking.start_time > now_utc,
            Booking.start_time <= now_utc + BOOKING_REMINDER_LEAD,
        )
        .order_by(Booking.id.asc())
        .with_for_update()
        .all()
    )
    for booking in upcoming_bookings:
        create_in_app_notification(
            db,
            user_id=booking.user_id,
            notification_type="booking_reminder",
            title="Upcoming charging booking",
            message=(
                "Your charging booking starts within 30 minutes. Please allow "
                "enough travel time and check in when you arrive."
            ),
            payload={
                "booking_id": booking.id,
                "start_time": ensure_utc(booking.start_time).isoformat(),
            },
            dedupe_key=f"booking-reminder:{booking.id}",
        )
        booking_reminders.append(booking.id)

    completed_bookings = (
        db.query(Booking)
        .filter(
            Booking.status == BookingStatus.COMPLETED,
            Booking.session_ended_at.isnot(None),
            Booking.idle_fee_ended_at.is_(None),
        )
        .order_by(Booking.id.asc())
        .with_for_update()
        .all()
    )
    for booking in completed_bookings:
        session_ended_at = ensure_utc(booking.session_ended_at)
        reminder_at = session_ended_at + IDLE_FEE_REMINDER_DELAY
        fee_start_at = session_ended_at + IDLE_FEE_START_DELAY

        if reminder_at <= now_utc:
            create_in_app_notification(
                db,
                user_id=booking.user_id,
                notification_type="idle_fee_reminder",
                title="Unplug your vehicle",
                message=(
                    "Your charging session has ended. Idle fees of "
                    f"INR {settings.IDLE_FEE_RATE_INR_PER_MINUTE:.2f} per minute "
                    "will start in five minutes if the connector remains occupied."
                ),
                payload={
                    "booking_id": booking.id,
                    "fee_start_at": fee_start_at.isoformat(),
                    "rate_inr_per_minute": settings.IDLE_FEE_RATE_INR_PER_MINUTE,
                },
                dedupe_key=f"idle-fee-reminder:{booking.id}",
            )
            booking_reminders.append(booking.id)

        if fee_start_at <= now_utc:
            if booking.idle_fee_started_at is None:
                booking.idle_fee_started_at = fee_start_at
                create_in_app_notification(
                    db,
                    user_id=booking.user_id,
                    notification_type="idle_fee_started",
                    title="Idle fee started",
                    message=(
                        f"Idle fees of INR "
                        f"{settings.IDLE_FEE_RATE_INR_PER_MINUTE:.2f} per minute "
                        "are now accruing while the connector remains occupied."
                    ),
                    payload={
                        "booking_id": booking.id,
                        "fee_started_at": fee_start_at.isoformat(),
                        "rate_inr_per_minute": settings.IDLE_FEE_RATE_INR_PER_MINUTE,
                    },
                    dedupe_key=f"idle-fee-started:{booking.id}",
                )
            _update_idle_fee_amount(booking, through=now_utc)
            idle_fee_updates.append(booking.id)

    if booking_reminders or idle_fee_updates:
        db.commit()
    return booking_reminders, idle_fee_updates


def finish_idle_fees_for_connector(
    db: Session,
    *,
    connector_id: int,
    ended_at: datetime,
) -> list[int]:
    ended_at_utc = ensure_utc(ended_at)
    bookings = (
        db.query(Booking)
        .filter(
            Booking.connector_id == connector_id,
            Booking.status == BookingStatus.COMPLETED,
            Booking.session_ended_at.isnot(None),
            Booking.idle_fee_ended_at.is_(None),
        )
        .order_by(Booking.id.asc())
        .with_for_update()
        .all()
    )
    finished_ids: list[int] = []
    for booking in bookings:
        session_ended_at = ensure_utc(booking.session_ended_at)
        fee_ended_at = max(ended_at_utc, session_ended_at)
        booking.idle_fee_ended_at = fee_ended_at
        if booking.idle_fee_started_at is not None:
            _update_idle_fee_amount(booking, through=fee_ended_at)
            create_in_app_notification(
                db,
                user_id=booking.user_id,
                notification_type="idle_fee_ended",
                title="Idle fee finalized",
                message=f"Your idle fee total is INR {booking.idle_fee_amount:.2f}.",
                payload={
                    "booking_id": booking.id,
                    "idle_fee_amount_inr": booking.idle_fee_amount,
                    "fee_ended_at": fee_ended_at.isoformat(),
                },
                dedupe_key=f"idle-fee-ended:{booking.id}",
            )
        finished_ids.append(booking.id)
    return finished_ids
