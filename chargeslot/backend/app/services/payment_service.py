
import hashlib
import hmac
import secrets
from decimal import Decimal, ROUND_HALF_UP

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.user import User
from app.schemas.payment import (
    PaymentOrderRequest,
    PaymentOrderResponse,
    PaymentVerificationRequest,
    PaymentVerificationResponse,
)
from app.services.booking_service import BookingService


class PaymentService:

    @staticmethod
    def create_order(
        db: Session,
        user: User,
        data: PaymentOrderRequest,
    ) -> PaymentOrderResponse:

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is not configured.",
            )

        estimate = BookingService.estimate_charging_cost(
            db=db,
            user=user,
            vehicle_id=data.vehicle_id,
            station_id=data.station_id,
            target_soc=data.target_soc,
        )

        amount = int(
            (Decimal(str(estimate.estimated_cost)) * 100)
            .quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        )

        if amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="Payment amount must be greater than zero.",
            )

        receipt = f"cs_{secrets.token_hex(12)}"

        try:
            response = httpx.post(
                "https://api.razorpay.com/v1/orders",
                auth=(
                    settings.RAZORPAY_KEY_ID,
                    settings.RAZORPAY_KEY_SECRET,
                ),
                json={
                    "amount": amount,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": {
                        "user_id": str(user.id),
                        "vehicle_id": str(data.vehicle_id),
                        "station_id": str(data.station_id),
                        "payment_method": data.payment_method.value,
                    },
                },
                timeout=15.0,
            )
            response.raise_for_status()
            result = response.json()

        except httpx.HTTPStatusError:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway rejected the order request.",
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is currently unreachable.",
            )

        return PaymentOrderResponse(
            order_id=result["id"],
            amount=result["amount"],
            currency=result["currency"],
            key_id=settings.RAZORPAY_KEY_ID,
            payment_method=data.payment_method,
            message="Payment order created successfully.",
        )
    @staticmethod
    def verify_payment(
        data: PaymentVerificationRequest,
        user: User,
    ) -> PaymentVerificationResponse:

        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is not configured.",
            )

        message = f"{data.razorpay_order_id}|{data.razorpay_payment_id}"

        expected_signature = hmac.new(
            settings.RAZORPAY_KEY_SECRET.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            expected_signature,
            data.razorpay_signature,
        ):
            raise HTTPException(
                status_code=400,
                detail="Payment signature verification failed.",
            )

        auth = (
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )

        try:
            order_response = httpx.get(
                f"https://api.razorpay.com/v1/orders/{data.razorpay_order_id}",
                auth=auth,
                timeout=15.0,
            )
            order_response.raise_for_status()
            order = order_response.json()

            notes = order.get("notes") or {}

            if not isinstance(notes, dict) or notes.get("user_id") != str(user.id):
                raise HTTPException(
                    status_code=403,
                    detail="This payment order does not belong to your account.",
                )

            payment_response = httpx.get(
                f"https://api.razorpay.com/v1/payments/{data.razorpay_payment_id}",
                auth=auth,
                timeout=15.0,
            )
            payment_response.raise_for_status()
            payment = payment_response.json()

        except HTTPException:
            raise
        except httpx.HTTPStatusError:
            raise HTTPException(
                status_code=400,
                detail="Unable to verify the Razorpay order or payment.",
            )
        except httpx.RequestError:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is currently unreachable.",
            )

        if (
            order.get("id") != data.razorpay_order_id
            or payment.get("id") != data.razorpay_payment_id
            or payment.get("order_id") != data.razorpay_order_id
            or payment.get("status") != "captured"
            or not payment.get("captured")
            or order.get("status") != "paid"
            or payment.get("amount") != order.get("amount")
        ):
            raise HTTPException(
                status_code=400,
                detail="Payment has not been successfully captured.",
            )

        return PaymentVerificationResponse(
            verified=True,
            message="Payment successfully verified and captured.",
        )