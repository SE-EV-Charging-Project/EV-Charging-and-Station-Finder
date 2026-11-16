from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.booking.battery import compute_charging_cost
from app.booking.qr import make_checkin_qr_payload
from app.booking.state import transition_booking_status
from app.models.booking import Booking, BookingStatus
from app.models.booking_payment_event import (
    BookingPaymentEvent,
    BookingPaymentEventStatus,
)
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.station import Station
from app.schemas.booking import (
    PaymentConfirmationResponse,
    PaymentConfirmationWebhookRequest,
)
from app.stations.slots import ensure_utc
from app.services.billing_service import snapshot_booking_tariff

RESERVATION_FEE_RATE = 0.10
MIN_RESERVATION_FEE_INR = 1.0


def calculate_reservation_fee(energy_required_kwh: float, price_per_kwh: float) -> float:
    estimated_cost = compute_charging_cost(energy_required_kwh, price_per_kwh)
    return max(
        MIN_RESERVATION_FEE_INR,
        round(estimated_cost * RESERVATION_FEE_RATE, 2),
    )


def _payment_response(
    booking: Booking,
    event: BookingPaymentEvent,
    message: str,
) -> PaymentConfirmationResponse:
    confirmed = booking.confirmed_at is not None
    return PaymentConfirmationResponse(
        booking_id=booking.id,
        booking_status=booking.status.value,
        payment_status=event.status.value,
        reservation_fee_amount=booking.reservation_fee_amount,
        booking_reference=f"CS-{booking.id:08d}" if confirmed else None,
        qr_code_payload=(
            make_checkin_qr_payload(booking.id, booking.user_id) if confirmed else None
        ),
        refund_due_amount=event.amount_inr if event.refund_due else 0.0,
        message=message,
    )


def record_payment_confirmation(
    db: Session,
    *,
    booking_id: int,
    payload: PaymentConfirmationWebhookRequest,
) -> PaymentConfirmationResponse:
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id)
        .with_for_update()
        .first()
    )
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with ID {booking_id} not found.",
        )

    provider_event_id = payload.provider_event_id.strip()
    if not provider_event_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provider event ID must not be blank.",
        )
    amount_inr = round(payload.amount_inr, 2)
    provider_reference = (
        payload.provider_reference.strip()
        if payload.provider_reference and payload.provider_reference.strip()
        else None
    )
    event_status = BookingPaymentEventStatus(payload.status)
    existing = (
        db.query(BookingPaymentEvent)
        .filter(BookingPaymentEvent.provider_event_id == provider_event_id)
        .first()
    )
    if existing is not None:
        if (
            existing.booking_id != booking.id
            or existing.amount_inr != amount_inr
            or existing.status != event_status
            or existing.provider_reference != provider_reference
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Payment provider event ID was already used with different data.",
            )
        return _payment_response(
            booking,
            existing,
            "Duplicate payment event ignored (idempotent replay).",
        )

    event = BookingPaymentEvent(
        booking_id=booking.id,
        provider_event_id=provider_event_id,
        provider_reference=provider_reference,
        amount_inr=amount_inr,
        status=event_status,
    )
    db.add(event)
    db.flush()

    message = "Payment failure recorded; booking remains unconfirmed."
    if event_status == BookingPaymentEventStatus.SUCCEEDED:
        amount_matches = (
            Decimal(str(event.amount_inr)).quantize(Decimal("0.01"))
            == Decimal(str(booking.reservation_fee_amount)).quantize(Decimal("0.01"))
        )
        hold_is_valid = (
            booking.status == BookingStatus.HELD
            and booking.hold_expires_at is not None
            and ensure_utc(booking.hold_expires_at) > datetime.now(timezone.utc)
        )
        if amount_matches and hold_is_valid:
            transition_booking_status(booking, BookingStatus.CONFIRMED)
            snapshot_booking_tariff(db, booking)
            message = "Reservation payment verified; booking confirmed."
        else:
            event.refund_due = True
            if (
                booking.status == BookingStatus.HELD
                and booking.hold_expires_at is not None
                and ensure_utc(booking.hold_expires_at) <= datetime.now(timezone.utc)
            ):
                transition_booking_status(booking, BookingStatus.EXPIRED)
                db.query(BookingSlotClaim).filter(
                    BookingSlotClaim.booking_id == booking.id
                ).delete(synchronize_session=False)
            message = (
                "Payment was recorded but could not confirm the booking; "
                "the amount is marked due for refund."
            )
    elif (
        booking.status == BookingStatus.HELD
        and booking.hold_expires_at is not None
        and ensure_utc(booking.hold_expires_at) <= datetime.now(timezone.utc)
    ):
        transition_booking_status(booking, BookingStatus.EXPIRED)
        db.query(BookingSlotClaim).filter(
            BookingSlotClaim.booking_id == booking.id
        ).delete(synchronize_session=False)

    db.commit()
    db.refresh(booking)
    db.refresh(event)
    return _payment_response(booking, event, message)
