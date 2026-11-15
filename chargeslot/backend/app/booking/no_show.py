import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.booking.payments import MIN_RESERVATION_FEE_INR
from app.db.session import SessionLocal
from app.booking.state import transition_booking_status
from app.models.booking import Booking, BookingStatus
from app.models.booking_slot_claim import BookingSlotClaim
from app.booking.lifecycle_notifications import (
    sweep_booking_reminders_and_idle_fees,
)
from app.services.notification_service import create_in_app_notification

NO_SHOW_GRACE_PERIOD = timedelta(minutes=15)
NO_SHOW_SWEEP_INTERVAL_SECONDS = 60

logger = logging.getLogger(__name__)


def sweep_no_show_bookings(
    db: Session,
    *,
    now: datetime | None = None,
) -> list[int]:
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    now_utc = now_utc.astimezone(timezone.utc)
    deadline = now_utc - NO_SHOW_GRACE_PERIOD
    bookings = (
        db.query(Booking)
        .filter(
            Booking.status.in_(
                [BookingStatus.CONFIRMED, BookingStatus.REASSIGNED]
            ),
            Booking.checked_in_at.is_(None),
            Booking.start_time <= deadline,
        )
        .order_by(Booking.id.asc())
        .with_for_update()
        .all()
    )
    processed_ids: list[int] = []
    for booking in bookings:
        if (
            booking.status
            not in (BookingStatus.CONFIRMED, BookingStatus.REASSIGNED)
            or booking.checked_in_at is not None
        ):
            continue
        transition_booking_status(booking, BookingStatus.NO_SHOW)
        booking.cancellation_fee_amount = round(
            max(MIN_RESERVATION_FEE_INR, booking.reservation_fee_amount),
            2,
        )
        db.query(BookingSlotClaim).filter(
            BookingSlotClaim.booking_id == booking.id
        ).delete(synchronize_session=False)
        create_in_app_notification(
            db,
            user_id=booking.user_id,
            notification_type="booking_no_show",
            title="Booking marked as no-show",
            message=(
                "Your booking was marked as a no-show because check-in was not "
                "recorded within 15 minutes of the start time. The no-show fee "
                f"due is INR {booking.cancellation_fee_amount:.2f}."
            ),
            payload={
                "booking_id": booking.id,
                "fee_due_inr": booking.cancellation_fee_amount,
            },
            dedupe_key=f"booking-no-show:{booking.id}",
        )
        processed_ids.append(booking.id)
    if processed_ids:
        db.commit()
    return processed_ids


async def run_no_show_sweeper() -> None:
    while True:
        await asyncio.sleep(NO_SHOW_SWEEP_INTERVAL_SECONDS)
        db = SessionLocal()
        try:
            processed_ids = sweep_no_show_bookings(db)
            if processed_ids:
                logger.info("Marked bookings as no-show: %s", processed_ids)
            reminder_ids, idle_fee_ids = sweep_booking_reminders_and_idle_fees(db)
            if reminder_ids or idle_fee_ids:
                logger.info(
                    "Processed booking reminders %s and idle fees %s.",
                    reminder_ids,
                    idle_fee_ids,
                )
        except SQLAlchemyError:
            db.rollback()
            logger.exception("No-show booking sweep failed.")
        finally:
            db.close()
