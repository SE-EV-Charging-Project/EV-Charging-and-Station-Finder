
import hashlib
import hmac
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.core.config import settings
from app.schemas.payment import (
    PaymentMethod,
    PaymentOrderRequest,
    PaymentVerificationRequest,
    SavedPaymentMethodCreate,
)
from app.services.payment_service import PaymentService
from app.models.user import User, UserRole


def test_payment_methods_validation():
    request = PaymentOrderRequest(
        vehicle_id=1,
        station_id=1,
        target_soc=80,
        payment_method="upi",
    )
    assert request.payment_method == PaymentMethod.UPI

    with pytest.raises(ValidationError):
        PaymentOrderRequest(
            vehicle_id=1,
            station_id=1,
            target_soc=80,
            payment_method="cash",
        )


def test_payment_order_uses_server_calculated_amount(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")

    monkeypatch.setattr(
        "app.services.payment_service.BookingService.estimate_charging_cost",
        lambda **kwargs: SimpleNamespace(estimated_cost=100.50),
    )

    gateway_response = Mock()
    gateway_response.json.return_value = {
        "id": "order_test123",
        "amount": 10050,
        "currency": "INR",
    }

    post = Mock(return_value=gateway_response)
    monkeypatch.setattr("app.services.payment_service.httpx.post", post)

    result = PaymentService.create_order(
        db=None,
        user=SimpleNamespace(id=1),
        data=PaymentOrderRequest(
            vehicle_id=1,
            station_id=1,
            target_soc=80,
            payment_method="upi",
        ),
    )

    assert result.order_id == "order_test123"
    assert result.amount == 10050
    assert result.payment_method == PaymentMethod.UPI

    sent_order = post.call_args.kwargs["json"]
    assert sent_order["amount"] == 10050
    assert sent_order["currency"] == "INR"



def test_payment_signature_verification(monkeypatch):
    secret = "test_secret"
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", secret)

    order_id = "order_test123"
    payment_id = "pay_test123"

    signature = hmac.new(
        secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    order_response = Mock()
    order_response.json.return_value = {
        "id": order_id,
        "status": "paid",
        "amount": 10050,
        "notes": {"user_id": "1"},
    }

    payment_response = Mock()
    payment_response.json.return_value = {
        "id": payment_id,
        "order_id": order_id,
        "status": "captured",
        "captured": True,
        "amount": 10050,
    }

    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        Mock(side_effect=[order_response, payment_response]),
    )

    result = PaymentService.verify_payment(
        PaymentVerificationRequest(
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature,
        ),
        user=SimpleNamespace(id=1),
    )

    assert result.verified is True



def test_invalid_payment_signature_rejected(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", "test_secret")

    with pytest.raises(HTTPException) as exc:
        PaymentService.verify_payment(
            data=PaymentVerificationRequest(
                razorpay_order_id="order_test123",
                razorpay_payment_id="pay_test123",
                razorpay_signature="invalid",
            ),
            user=SimpleNamespace(id=1),
        )

    assert exc.value.status_code == 400


def test_payment_order_rejects_another_user(monkeypatch):
    secret = "test_secret"
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", secret)

    order_id = "order_test123"
    payment_id = "pay_test123"

    signature = hmac.new(
        secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    order_response = Mock()
    order_response.json.return_value = {
        "id": order_id,
        "status": "paid",
        "amount": 10050,
        "notes": {"user_id": "2"},
    }

    get_mock = Mock(return_value=order_response)
    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        get_mock,
    )

    with pytest.raises(HTTPException) as exc:
        PaymentService.verify_payment(
            PaymentVerificationRequest(
                razorpay_order_id=order_id,
                razorpay_payment_id=payment_id,
                razorpay_signature=signature,
            ),
            user=SimpleNamespace(id=1),
        )

    assert exc.value.status_code == 403
    assert get_mock.call_count == 1


def test_order_rejected_when_gateway_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", None)
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", None)

    with pytest.raises(HTTPException) as exc:
        PaymentService.create_order(
            db=None,
            user=SimpleNamespace(id=1),
            data=PaymentOrderRequest(
                vehicle_id=1,
                station_id=1,
                target_soc=80,
                payment_method="upi",
            ),
        )

    assert exc.value.status_code == 503

def test_uncaptured_payment_rejected(monkeypatch):
    secret = "test_secret"
    monkeypatch.setattr(settings, "RAZORPAY_KEY_ID", "test_key")
    monkeypatch.setattr(settings, "RAZORPAY_KEY_SECRET", secret)

    order_id = "order_test123"
    payment_id = "pay_test123"

    signature = hmac.new(
        secret.encode(),
        f"{order_id}|{payment_id}".encode(),
        hashlib.sha256,
    ).hexdigest()

    order_response = Mock()
    order_response.json.return_value = {
        "id": order_id,
        "status": "paid",
        "amount": 10050,
        "notes": {"user_id": "1"},
    }

    payment_response = Mock()
    payment_response.json.return_value = {
        "id": payment_id,
        "order_id": order_id,
        "status": "authorized",
        "captured": False,
        "amount": 10050,
    }

    monkeypatch.setattr(
        "app.services.payment_service.httpx.get",
        Mock(side_effect=[order_response, payment_response]),
    )

    with pytest.raises(HTTPException) as exc:
        PaymentService.verify_payment(
            data=PaymentVerificationRequest(
                razorpay_order_id=order_id,
                razorpay_payment_id=payment_id,
                razorpay_signature=signature,
            ),
            user=SimpleNamespace(id=1),
        )

    assert exc.value.status_code == 400

def create_test_user(db, user_id, role=UserRole.DRIVER):
    user = User(
        name=f"Test User {user_id}",
        email=f"payment-test-{user_id}@example.com",
        phone=f"90000000{user_id:02d}",
        hashed_password="test-hash",
        role=role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def valid_saved_method(**overrides):
    data = {
        "token_reference": "token_test_123",
        "customer_reference": "customer_test_123",
        "method_type": "card",
        "card_network": "Visa",
        "last4": "4242",
        "customer_consent": True,
    }
    data.update(overrides)
    return SavedPaymentMethodCreate(**data)


def test_saved_payment_method_schema_rejects_invalid_data():
    with pytest.raises(ValidationError):
        valid_saved_method(last4="12A4")

    with pytest.raises(ValidationError):
        valid_saved_method(customer_consent=False)

    with pytest.raises(ValidationError):
        valid_saved_method(method_type="upi")

    with pytest.raises(ValidationError):
        valid_saved_method(card_number="4111111111111111")

    with pytest.raises(ValidationError):
        valid_saved_method(cvv="123")


def test_saved_payment_method_crud_and_default_promotion(db_session):
    user = create_test_user(db_session, 10)

    first = PaymentService.save_payment_method(
        db_session,
        user,
        valid_saved_method(),
    )
    assert first.is_default is True
    assert first.last4 == "4242"

    second = PaymentService.save_payment_method(
        db_session,
        user,
        valid_saved_method(
            token_reference="token_test_456",
            last4="1111",
        ),
    )
    assert second.is_default is False

    methods = PaymentService.list_saved_payment_methods(db_session, user)
    assert len(methods) == 2
    assert all(not hasattr(method, "token_reference") for method in methods)

    PaymentService.delete_saved_payment_method(
        db_session,
        user,
        first.id,
    )

    remaining = PaymentService.list_saved_payment_methods(db_session, user)
    assert len(remaining) == 1
    assert remaining[0].id == second.id
    assert remaining[0].is_default is True


def test_saved_payment_method_duplicate_token_rejected(db_session):
    user = create_test_user(db_session, 11)

    PaymentService.save_payment_method(
        db_session,
        user,
        valid_saved_method(),
    )

    with pytest.raises(HTTPException) as exc:
        PaymentService.save_payment_method(
            db_session,
            user,
            valid_saved_method(),
        )

    assert exc.value.status_code == 409


def test_saved_payment_methods_restricted_to_drivers(db_session):
    operator = create_test_user(db_session, 12, UserRole.OPERATOR)

    with pytest.raises(HTTPException) as exc:
        PaymentService.save_payment_method(
            db_session,
            operator,
            valid_saved_method(),
        )

    assert exc.value.status_code == 403


def test_user_cannot_delete_another_users_saved_method(db_session):
    owner = create_test_user(db_session, 13)
    another_user = create_test_user(db_session, 14)

    saved = PaymentService.save_payment_method(
        db_session,
        owner,
        valid_saved_method(),
    )

    with pytest.raises(HTTPException) as exc:
        PaymentService.delete_saved_payment_method(
            db_session,
            another_user,
            saved.id,
        )

    assert exc.value.status_code == 404

    # The original owner's method must still exist.
    methods = PaymentService.list_saved_payment_methods(db_session, owner)
    assert len(methods) == 1
    assert methods[0].id == saved.id
