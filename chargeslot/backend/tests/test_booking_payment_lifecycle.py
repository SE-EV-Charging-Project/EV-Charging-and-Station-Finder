from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.booking.payments import record_payment_confirmation
from app.booking.state import transition_booking_status
from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.booking_payment_event import BookingPaymentEvent
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.schemas.booking import PaymentConfirmationWebhookRequest


def _create_held_booking(db_session, *, hold_expires_at=None):
    user = User(
        name="Payment Test Driver",
        email="payment-driver@example.com",
        phone="9000000000",
        hashed_password="not-used",
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.flush()

    db_session.add(
        Station(
            id=1,
            operator_id=user.id,
            name="Payment Test Station",
            address="1 Payment Road",
            latitude=12.97,
            longitude=77.59,
            contact_phone="9000000001",
            price_per_kwh=10.0,
            status=StationStatus.APPROVED,
            is_active=True,
        )
    )
    db_session.flush()

    booking = Booking(
        user_id=user.id,
        station_id=1,
        charger_id=1,
        start_soc=20,
        target_soc=80,
        est_energy_kwh=20.0,
        est_duration_min=60,
        booking_type="manual",
        status=BookingStatus.HELD,
        reservation_fee_amount=20.0,
        start_time=datetime.now(timezone.utc) + timedelta(hours=1),
        end_time=datetime.now(timezone.utc) + timedelta(hours=2),
        hold_expires_at=hold_expires_at
        or datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db_session.add(booking)
    db_session.flush()
    return booking


def _success_event(event_id="provider-event-1", amount=20.0):
    return PaymentConfirmationWebhookRequest(
        provider_event_id=event_id,
        provider_reference="provider-reference-1",
        amount_inr=amount,
        status="Succeeded",
    )


def test_successful_payment_confirms_booking_and_keeps_slot_claim(db_session):
    booking = _create_held_booking(db_session)
    claim = BookingSlotClaim(
        charger_id=1,
        vehicle_id=None,
        booking_id=booking.id,
        slot_start_time=booking.start_time,
    )
    db_session.add(claim)
    db_session.commit()

    response = record_payment_confirmation(
        db_session,
        booking_id=booking.id,
        payload=_success_event(),
    )

    db_session.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.confirmed_at is not None
    assert response.booking_reference == f"CS-{booking.id:08d}"
    assert response.qr_code_payload is not None
    assert db_session.query(BookingSlotClaim).filter_by(booking_id=booking.id).count() == 1


def test_payment_event_replay_is_idempotent(db_session):
    booking = _create_held_booking(db_session)
    db_session.commit()
    payload = PaymentConfirmationWebhookRequest(
        provider_event_id="provider-event-1",
        provider_reference=" provider-reference-1 ",
        amount_inr=20.004,
        status="Succeeded",
    )

    first = record_payment_confirmation(
        db_session,
        booking_id=booking.id,
        payload=payload,
    )
    replay = record_payment_confirmation(
        db_session,
        booking_id=booking.id,
        payload=payload,
    )

    assert first.booking_status == BookingStatus.CONFIRMED.value
    assert replay.booking_status == BookingStatus.CONFIRMED.value
    assert "idempotent replay" in replay.message
    assert db_session.query(BookingPaymentEvent).count() == 1


def test_mismatched_payment_is_recorded_for_refund_without_confirmation(db_session):
    booking = _create_held_booking(db_session)
    db_session.commit()

    response = record_payment_confirmation(
        db_session,
        booking_id=booking.id,
        payload=_success_event(amount=25.0),
    )

    db_session.refresh(booking)
    event = db_session.query(BookingPaymentEvent).one()
    assert booking.status == BookingStatus.HELD
    assert booking.confirmed_at is None
    assert event.refund_due is True
    assert response.refund_due_amount == 25.0


def test_expired_hold_is_expired_when_payment_arrives(db_session):
    booking = _create_held_booking(
        db_session,
        hold_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    claim = BookingSlotClaim(
        charger_id=1,
        vehicle_id=None,
        booking_id=booking.id,
        slot_start_time=booking.start_time,
    )
    db_session.add(claim)
    db_session.commit()

    response = record_payment_confirmation(
        db_session,
        booking_id=booking.id,
        payload=_success_event(),
    )

    db_session.refresh(booking)
    assert booking.status == BookingStatus.EXPIRED
    assert response.refund_due_amount == 20.0
    assert db_session.query(BookingSlotClaim).filter_by(booking_id=booking.id).count() == 0


def test_invalid_booking_state_transition_returns_conflict(db_session):
    booking = _create_held_booking(db_session)

    with pytest.raises(HTTPException) as exc_info:
        transition_booking_status(booking, BookingStatus.COMPLETED)

    assert exc_info.value.status_code == 409
    assert booking.status == BookingStatus.HELD


def test_payment_webhook_requires_shared_secret(client, db_session, monkeypatch):
    booking = _create_held_booking(db_session)
    db_session.commit()
    monkeypatch.setattr(settings, "PAYMENT_WEBHOOK_SECRET", "test-secret")
    payload = {
        "provider_event_id": "provider-event-1",
        "amount_inr": 20.0,
        "status": "Succeeded",
    }

    unauthorized = client.post(
        f"/api/v1/bookings/{booking.id}/payment-confirmation",
        json=payload,
    )
    authorized = client.post(
        f"/api/v1/bookings/{booking.id}/payment-confirmation",
        headers={"X-Payment-Webhook-Secret": "test-secret"},
        json=payload,
    )

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["booking_status"] == BookingStatus.CONFIRMED.value
