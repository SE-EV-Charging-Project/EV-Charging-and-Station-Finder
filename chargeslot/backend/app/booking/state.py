from datetime import datetime, timezone

from fastapi import HTTPException, status

from app.models.booking import Booking, BookingStatus


_ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.HELD: {
        BookingStatus.CONFIRMED,
        BookingStatus.CANCELLED,
        BookingStatus.EXPIRED,
    },
    BookingStatus.CONFIRMED: {
        BookingStatus.ACTIVE,
        BookingStatus.CANCELLED,
        BookingStatus.NO_SHOW,
        BookingStatus.REASSIGNED,
    },
    BookingStatus.ACTIVE: {BookingStatus.COMPLETED},
    BookingStatus.COMPLETED: set(),
    BookingStatus.CANCELLED: set(),
    BookingStatus.NO_SHOW: set(),
    BookingStatus.EXPIRED: set(),
    BookingStatus.REASSIGNED: {
        BookingStatus.ACTIVE,
        BookingStatus.CANCELLED,
        BookingStatus.NO_SHOW,
    },
}


def transition_booking_status(
    booking: Booking,
    target_status: BookingStatus,
) -> bool:
    """Apply one valid booking lifecycle transition; return False for an idempotent no-op."""
    current_status = booking.status
    if current_status == target_status:
        return False
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Booking cannot transition from {current_status.value} "
                f"to {target_status.value}."
            ),
        )

    booking.status = target_status
    if target_status == BookingStatus.CONFIRMED:
        booking.confirmed_at = datetime.now(timezone.utc)
    return True
