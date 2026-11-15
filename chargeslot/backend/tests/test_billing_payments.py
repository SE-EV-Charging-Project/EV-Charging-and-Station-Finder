import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, ConnectorType, CurrentType
from app.models.charging_session_reading import ChargingSessionReading
from app.models.payment_record import PaymentRecord
from app.models.station import Station, StationStatus
from app.models.station_tariff import StationTariff
from app.models.user import User, UserRole
from app.schemas.billing import PeakPeriod, StationTariffUpdate
from app.schemas.payment import BookingPaymentOrderRequest, PaymentVerificationRequest
from app.services.billing_service import (
    calculate_final_bill,
    ensure_no_payment_due,
    snapshot_booking_tariff,
    update_payment_due,
)
from app.services.invoice_service import generate_invoice
from app.services.payment_service import PaymentService
from app.services.reconciliation_service import reconcile_daily
from app.services.tariff_service import TariffService
from app.utils.security import create_access_token


def _user(db, user_id: int, role: UserRole = UserRole.DRIVER) -> User:
    user = User(
        name=f"Billing User {user_id}",
        email=f"billing-{user_id}@example.test",
        phone=f"811000{user_id:05d}",
        hashed_password="test-hash",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _station(db, operator: User, *, price: float = 10.0) -> Station:
    station = Station(
        operator_id=operator.id,
        name="Billing Station",
        address="1 Billing Road",
        latitude=12.97,
        longitude=77.59,
        contact_phone="9876543210",
        price_per_kwh=price,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db.add(station)
    db.commit()
    db.refresh(station)
    return station


def _booking(
    db,
    user: User,
    station: Station,
    *,
    status: BookingStatus = BookingStatus.HELD,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> Booking:
    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=user.id,
        station_id=station.id,
        status=status,
        start_time=start_time or now + timedelta(hours=1),
        end_time=end_time or now + timedelta(hours=2),
        hold_expires_at=now + timedelta(minutes=5) if status == BookingStatus.HELD else None,
    )
    db.add(booking)
    db.commit()
    db.refresh(booking)
    return booking


def _gateway_response(payload: dict) -> Mock:
    response = Mock()
    response.json.return_value = payload
    return response


def test_tariff_schema_rejects_invalid_values_and_effective_dates():
    with pytest.raises(ValidationError):
        StationTariffUpdate(price_per_kwh=-1)
    with pytest.raises(ValidationError):
        StationTariffUpdate(price_per_kwh=10, tax_rate_percent=101)
    with pytest.raises(ValidationError):
        StationTariffUpdate(
            price_per_kwh=10,
            peak_periods=[{"start": "12:00", "end": "12:00"}],
        )
    with pytest.raises(ValidationError):
        StationTariffUpdate(price_per_kwh=10, effective_from=datetime.now(timezone.utc))
    with pytest.raises(ValidationError):
        PeakPeriod(start="18:00", end="18:00", multiplier=1.5)


def test_tariff_update_is_operator_scoped_and_versioned(db_session):
    operator = _user(db_session, 1, UserRole.OPERATOR)
    other_operator = _user(db_session, 2, UserRole.OPERATOR)
    station = _station(db_session, operator)
    update = StationTariffUpdate(
        price_per_kwh=12.5,
        idle_fee_per_minute=2,
        tax_rate_percent=5,
        peak_periods=[{"start": "18:00", "end": "22:00", "multiplier": 1.5}],
    )

    tariff = TariffService.update_tariff(db_session, operator, station.id, update)
    assert tariff.price_per_kwh == 12.5
    assert tariff.idle_fee_per_minute == 2
    assert tariff.tax_rate_percent == 5
    assert db_session.get(Station, station.id).price_per_kwh == 12.5

    with pytest.raises(HTTPException) as exc:
        TariffService.update_tariff(db_session, other_operator, station.id, update)
    assert exc.value.status_code == 403


def test_booking_tariff_snapshot_and_final_bill_use_actual_energy(db_session):
    operator = _user(db_session, 3, UserRole.OPERATOR)
    driver = _user(db_session, 4)
    station = _station(db_session, operator)
    now = datetime.now(timezone.utc)
    tariff = StationTariff(
        station_id=station.id,
        created_by_user_id=operator.id,
        price_per_kwh=10,
        idle_fee_per_minute=2,
        tax_rate_percent=10,
        peak_periods=[
            {"start": "00:00:00", "end": "23:59:59", "multiplier": 1.5}
        ],
        effective_from=now - timedelta(hours=3),
    )
    db_session.add(tariff)
    charger = Charger(
        station_id=station.id,
        name="Billing Charger",
        power_kw=50,
        current_type=CurrentType.DC,
        gateway_id="billing-gateway",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()
    connector = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add(connector)
    db_session.flush()
    booking = _booking(
        db_session,
        driver,
        station,
        status=BookingStatus.ACTIVE,
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(minutes=4),
    )
    booking.charger_id = charger.id
    booking.connector_id = connector.id
    booking.session_transaction_id = 99
    booking.reservation_fee_paid_amount = 10
    booking.status = BookingStatus.COMPLETED
    db_session.add(
        ChargingSessionReading(
            booking_id=booking.id,
            charger_id=charger.id,
            connector_id=connector.id,
            transaction_id=99,
            power_kw=20,
            energy_meter_kwh=10,
            observed_at=now - timedelta(hours=2),
        )
    )
    snapshot_booking_tariff(db_session, booking, confirmed_at=now - timedelta(hours=2))
    db_session.flush()

    bill = calculate_final_bill(
        db_session,
        booking,
        ended_at=now,
        meter_stop_wh=12_000,
    )
    assert booking.tariff_price_per_kwh == 10
    assert booking.energy_delivered_kwh == pytest.approx(2)
    assert booking.energy_cost_amount == pytest.approx(30)
    assert booking.idle_fee_amount == pytest.approx(8)
    assert booking.tax_amount == pytest.approx(3.8)
    assert bill == pytest.approx(31.8)
    assert update_payment_due(db_session, booking) is True
    db_session.flush()
    with pytest.raises(HTTPException) as exc:
        ensure_no_payment_due(db_session, driver)
    assert exc.value.status_code == 402


def test_reservation_order_is_idempotent_and_confirms_tariff_snapshot(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")
    operator = _user(db_session, 5, UserRole.OPERATOR)
    driver = _user(db_session, 6)
    station = _station(db_session, operator)
    tariff = StationTariff(
        station_id=station.id,
        created_by_user_id=operator.id,
        price_per_kwh=14,
        idle_fee_per_minute=0.5,
        tax_rate_percent=5,
        peak_periods=[],
        effective_from=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(tariff)
    booking = _booking(db_session, driver, station)
    response = _gateway_response(
        {"id": "order_reservation", "amount": 5000, "currency": "INR"}
    )
    post = Mock(return_value=response)
    monkeypatch.setattr("app.services.payment_service.httpx.post", post)
    request = BookingPaymentOrderRequest(
        payment_method="upi",
        idempotency_key="reservation-6",
    )

    first = PaymentService.create_booking_order(
        db_session, driver, booking.id, request, payment_type="reservation"
    )
    second = PaymentService.create_booking_order(
        db_session, driver, booking.id, request, payment_type="reservation"
    )
    assert first.order_id == second.order_id == "order_reservation"
    assert post.call_count == 1

    signature = hmac.new(
        b"test_secret",
        b"order_reservation|pay_reservation",
        hashlib.sha256,
    ).hexdigest()
    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        Mock(
            side_effect=[
                _gateway_response(
                    {
                        "id": "order_reservation",
                        "status": "paid",
                        "amount": 5000,
                        "notes": {"user_id": str(driver.id)},
                    }
                ),
                _gateway_response(
                    {
                        "id": "pay_reservation",
                        "order_id": "order_reservation",
                        "status": "captured",
                        "captured": True,
                        "amount": 5000,
                    }
                ),
            ]
        ),
    )
    verified = PaymentService.verify_payment(
        PaymentVerificationRequest(
            razorpay_order_id="order_reservation",
            razorpay_payment_id="pay_reservation",
            razorpay_signature=signature,
        ),
        driver,
        db_session,
    )
    db_session.refresh(booking)
    assert verified.verified is True
    assert booking.status == BookingStatus.CONFIRMED
    assert booking.reservation_fee_paid_amount == 50
    assert booking.tariff_price_per_kwh == 14
    assert db_session.query(PaymentRecord).filter_by(status="captured").count() == 1


def test_refund_uses_gateway_idempotency_and_five_business_day_deadline(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")
    operator = _user(db_session, 7, UserRole.OPERATOR)
    driver = _user(db_session, 8)
    station = _station(db_session, operator)
    booking = _booking(db_session, driver, station, status=BookingStatus.CANCELLED)
    booking.cancellation_fee_amount = 5
    db_session.add(
        PaymentRecord(
            user_id=driver.id,
            booking_id=booking.id,
            amount_paise=5000,
            payment_type="reservation",
            gateway_reference="order_refund",
            gateway_payment_id="pay_refund",
            idempotency_key="reservation-refund-test",
            status="captured",
        )
    )
    db_session.commit()
    post = Mock(
        return_value=_gateway_response(
            {"id": "rfnd_test", "amount": 4500, "status": "processed"}
        )
    )
    monkeypatch.setattr("app.services.payment_service.httpx.post", post)

    result = PaymentService.refund_booking(
        db_session, driver, booking.id, "cancel-refund-test"
    )
    replay = PaymentService.refund_booking(
        db_session, driver, booking.id, "cancel-refund-test"
    )
    assert result.amount_paise == 4500
    assert result.status == "refunded"
    assert replay.refund_record_id == result.refund_record_id
    assert post.call_count == 1
    assert post.call_args.kwargs["headers"]["X-Idempotency-Key"].startswith("ref_")


def test_failed_refund_webhook_updates_its_request_and_allows_safe_retry(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")
    operator = _user(db_session, 10, UserRole.OPERATOR)
    driver = _user(db_session, 11)
    station = _station(db_session, operator)
    booking = _booking(db_session, driver, station, status=BookingStatus.CANCELLED)
    payment = PaymentRecord(
        user_id=driver.id,
        booking_id=booking.id,
        amount_paise=5000,
        payment_type="reservation",
        gateway_reference="order_failed_refund",
        gateway_payment_id="pay_failed_refund",
        idempotency_key="reservation-failed-refund",
        status="captured",
    )
    db_session.add(payment)
    db_session.flush()
    refund_request = PaymentRecord(
        user_id=driver.id,
        booking_id=booking.id,
        amount_paise=5000,
        payment_type="refund_request",
        idempotency_key="failed-refund-request",
        status="pending",
        details={"refund_record_ids": []},
    )
    db_session.add(refund_request)
    db_session.flush()
    failed_refund = PaymentRecord(
        user_id=driver.id,
        booking_id=booking.id,
        refund_of_id=payment.id,
        amount_paise=5000,
        payment_type="refund",
        gateway_reference="rfnd_failed",
        idempotency_key="refund-attempt-0",
        status="pending",
    )
    db_session.add(failed_refund)
    db_session.flush()
    refund_request.details = {"refund_record_ids": [failed_refund.id]}
    db_session.commit()

    body = json.dumps(
        {
            "event": "refund.failed",
            "payload": {
                "refund": {"entity": {"id": "rfnd_failed", "status": "failed"}}
            },
        }
    ).encode()
    signature = hmac.new(b"webhook_secret", body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        Mock(
            return_value=_gateway_response(
                {
                    "id": "rfnd_failed",
                    "payment_id": "pay_failed_refund",
                    "amount": 5000,
                    "status": "failed",
                }
            )
        ),
    )
    result = PaymentService.process_webhook(db_session, body, signature)
    db_session.refresh(refund_request)
    assert result["status"] == "failed"
    assert refund_request.status == "failed"

    post = Mock(
        return_value=_gateway_response(
            {"id": "rfnd_retry", "amount": 5000, "status": "processed"}
        )
    )
    monkeypatch.setattr("app.services.payment_service.httpx.post", post)
    retry = PaymentService.refund_booking(
        db_session, driver, booking.id, "refund-retry-request"
    )
    assert retry.status == "refunded"
    expected_key = "ref_" + hashlib.sha256(
        f"booking:{booking.id}:payment:{payment.id}:attempt:1".encode()
    ).hexdigest()
    assert post.call_args.kwargs["headers"]["X-Idempotency-Key"] == expected_key


def test_payment_webhook_verifies_signature_and_gateway_state(db_session, monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "webhook_secret")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")
    driver = _user(db_session, 9)
    db_session.add(
        PaymentRecord(
            user_id=driver.id,
            amount_paise=2500,
            payment_type="session",
            gateway_reference="order_webhook",
            idempotency_key="webhook-order",
            status="pending",
        )
    )
    db_session.commit()
    body = json.dumps(
        {
            "event": "payment.captured",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_webhook",
                        "order_id": "order_webhook",
                        "status": "captured",
                    }
                }
            },
        }
    ).encode()
    signature = hmac.new(b"webhook_secret", body, hashlib.sha256).hexdigest()
    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        Mock(
            side_effect=[
                _gateway_response(
                    {
                        "id": "order_webhook",
                        "status": "paid",
                        "notes": {"user_id": str(driver.id)},
                    }
                ),
                _gateway_response(
                    {
                        "id": "pay_webhook",
                        "order_id": "order_webhook",
                        "status": "captured",
                        "captured": True,
                        "amount": 2500,
                    }
                ),
            ]
        ),
    )

    result = PaymentService.process_webhook(db_session, body, signature)
    record = db_session.query(PaymentRecord).filter_by(gateway_reference="order_webhook").one()
    assert result["status"] == "captured"
    assert record.gateway_payment_id == "pay_webhook"
    assert record.status == "captured"


def test_payment_webhook_rejects_plain_http(client):
    response = client.post("/api/v1/payments/webhook", content=b"{}")
    assert response.status_code == 400


def test_payment_history_is_newest_first_and_user_scoped(
    db_session, client
):
    driver = _user(db_session, 14)
    other_driver = _user(db_session, 15)
    old_record = PaymentRecord(
        user_id=driver.id,
        amount_paise=1000,
        payment_type="session",
        idempotency_key="history-old",
        status="captured",
        created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )
    new_record = PaymentRecord(
        user_id=driver.id,
        amount_paise=2000,
        payment_type="session",
        idempotency_key="history-new",
        status="failed",
        created_at=datetime(2026, 11, 2, tzinfo=timezone.utc),
    )
    db_session.add_all(
        [
            old_record,
            new_record,
            PaymentRecord(
                user_id=other_driver.id,
                amount_paise=3000,
                payment_type="session",
                idempotency_key="history-private",
                status="captured",
            ),
        ]
    )
    db_session.commit()
    token = create_access_token({"sub": str(driver.id), "email": driver.email})

    response = client.get(
        "/api/v1/payments/history",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    records = response.json()
    assert [record["amount_paise"] for record in records] == [2000, 1000]
    assert all(record["id"] != 3 for record in records)


def test_daily_reconciliation_persists_missing_gateway_discrepancy(
    db_session, monkeypatch
):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")
    admin = _user(db_session, 10, UserRole.ADMIN)
    db_session.add(
        PaymentRecord(
            user_id=admin.id,
            amount_paise=1000,
            payment_type="session",
            gateway_reference="order_internal",
            gateway_payment_id="pay_internal",
            idempotency_key="internal-only",
            status="captured",
            updated_at=datetime(2026, 11, 14, 12, tzinfo=timezone.utc),
        )
    )
    db_session.commit()
    monkeypatch.setattr(
        "app.services.reconciliation_service.httpx.get",
        Mock(return_value=_gateway_response({"items": []})),
    )

    result = reconcile_daily(db_session, admin, datetime(2026, 11, 14).date())
    assert result.internal_payment_count == 1
    assert result.gateway_payment_count == 0
    assert result.discrepancies == [
        {"type": "missing_from_gateway", "payment_id": "pay_internal"}
    ]
    assert db_session.query(PaymentRecord).filter_by(status="captured").count() == 1


def test_invoice_requires_paid_completed_booking_and_returns_pdf(db_session):
    operator = _user(db_session, 11, UserRole.OPERATOR)
    driver = _user(db_session, 12)
    other_driver = _user(db_session, 13)
    station = _station(db_session, operator)
    booking = _booking(db_session, driver, station, status=BookingStatus.COMPLETED)
    booking.session_ended_at = datetime.now(timezone.utc)
    booking.energy_delivered_kwh = 2.5
    booking.energy_cost_amount = 25
    booking.tax_amount = 1.25
    booking.final_bill_amount = 26.25
    db_session.add(
        PaymentRecord(
            user_id=driver.id,
            booking_id=booking.id,
            amount_paise=2625,
            payment_type="balance",
            gateway_reference="order_invoice",
            gateway_payment_id="pay_invoice",
            idempotency_key="invoice-payment",
            status="captured",
        )
    )
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        generate_invoice(db_session, other_driver, booking.id)
    assert exc.value.status_code == 404
    pdf = generate_invoice(db_session, driver, booking.id)
    assert pdf.startswith(b"%PDF-1.4")
    assert b"ChargeSlot - Tax Invoice" in pdf
    assert b"INR 26.25" in pdf

    booking.payment_due = True
    db_session.commit()
    with pytest.raises(HTTPException) as unpaid:
        generate_invoice(db_session, driver, booking.id)
    assert unpaid.value.status_code == 409
