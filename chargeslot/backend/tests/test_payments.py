
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
)
from app.services.payment_service import PaymentService


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
