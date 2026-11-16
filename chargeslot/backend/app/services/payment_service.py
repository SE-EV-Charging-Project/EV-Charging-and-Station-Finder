
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.payment_record import PaymentRecord
from app.models.user import User, UserRole
from app.models.saved_payment_method import SavedPaymentMethod
from app.schemas.payment import (
    BookingPaymentOrderRequest,
    PaymentOrderRequest,
    PaymentOrderResponse,
    PaymentVerificationRequest,
    PaymentVerificationResponse,
    RefundResponse,
    SavedPaymentMethodCreate,
    SavedPaymentMethodResponse,
)
from app.services.booking_service import BookingService
from app.services.billing_service import (
    add_business_days,
    snapshot_booking_tariff,
    update_payment_due,
)
from app.booking.state import transition_booking_status


def _to_paise(amount_inr: Decimal | float | int) -> int:
    return int(
        (Decimal(str(amount_inr)) * 100).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


class PaymentService:

    @staticmethod
    def create_order(
        db: Session,
        user: User,
        data: PaymentOrderRequest,
    ) -> PaymentOrderResponse:
        PaymentService._require_driver(user)
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

        idempotency_key = PaymentService._idempotency_key(data.idempotency_key)
        return PaymentService._create_gateway_order(
            db=db,
            user=user,
            amount_paise=amount,
            payment_method=data.payment_method,
            payment_type="session",
            booking_id=None,
            idempotency_key=idempotency_key,
            notes={
                "vehicle_id": str(data.vehicle_id),
                "station_id": str(data.station_id),
                "target_soc": str(data.target_soc),
            },
        )

    @staticmethod
    def create_booking_order(
        db: Session,
        user: User,
        booking_id: int,
        data: BookingPaymentOrderRequest,
        *,
        payment_type: str,
    ) -> PaymentOrderResponse:
        PaymentService._require_driver(user)
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is not configured.",
            )

        booking = (
            db.query(Booking)
            .filter(Booking.id == booking_id, Booking.user_id == user.id)
            .with_for_update()
            .first()
        )
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found.")

        if payment_type == "reservation":
            if booking.status != BookingStatus.HELD:
                raise HTTPException(
                    status_code=409,
                    detail="A reservation fee can only be paid for a held booking.",
                )
            if booking.hold_expires_at is None or _as_utc(
                booking.hold_expires_at
            ) <= datetime.now(timezone.utc):
                raise HTTPException(status_code=409, detail="The booking hold has expired.")
            amount_paise = _to_paise(settings.RESERVATION_FEE_INR)
        elif payment_type == "balance":
            if booking.status != BookingStatus.COMPLETED:
                raise HTTPException(
                    status_code=409,
                    detail="Only completed charging sessions can be settled.",
                )
            amount_paise = PaymentService._outstanding_balance_paise(db, booking)
            if amount_paise <= 0:
                raise HTTPException(status_code=409, detail="No payment balance is due.")
        else:
            raise ValueError(f"Unsupported booking payment type: {payment_type}")

        idempotency_key = PaymentService._idempotency_key(data.idempotency_key)
        pending_order = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.booking_id == booking.id,
                PaymentRecord.payment_type == payment_type,
                PaymentRecord.status == "pending",
            )
            .first()
        )
        if pending_order and pending_order.idempotency_key != idempotency_key:
            raise HTTPException(
                status_code=409,
                detail="A payment order for this booking is already pending.",
            )
        return PaymentService._create_gateway_order(
            db=db,
            user=user,
            amount_paise=amount_paise,
            payment_method=data.payment_method,
            payment_type=payment_type,
            booking_id=booking.id,
            idempotency_key=idempotency_key,
            notes={"booking_id": str(booking.id)},
        )

    @staticmethod
    def _create_gateway_order(
        *,
        db: Session,
        user: User,
        amount_paise: int,
        payment_method,
        payment_type: str,
        booking_id: int | None,
        idempotency_key: str,
        notes: dict[str, str],
    ) -> PaymentOrderResponse:
        if amount_paise <= 0:
            raise HTTPException(status_code=400, detail="Payment amount must be greater than zero.")

        if db is not None:
            existing = (
                db.query(PaymentRecord)
                .filter(
                    PaymentRecord.user_id == user.id,
                    PaymentRecord.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing is not None:
                if (
                    existing.amount_paise != amount_paise
                    or existing.payment_type != payment_type
                    or existing.booking_id != booking_id
                    or (existing.details or {}).get("payment_method")
                    != payment_method.value
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was already used for a different payment.",
                    )
                if existing.gateway_reference is None:
                    raise HTTPException(
                        status_code=409,
                        detail="Payment order creation for this key is already in progress.",
                    )
                return PaymentOrderResponse(
                    order_id=existing.gateway_reference,
                    amount=existing.amount_paise,
                    currency=existing.currency,
                    key_id=settings.RAZORPAY_KEY_ID,
                    payment_method=payment_method,
                    message="Existing payment order returned for the idempotency key.",
                    idempotency_key=idempotency_key,
                )

        receipt = "cs_" + hashlib.sha256(
            f"{user.id}:{idempotency_key}".encode("utf-8")
        ).hexdigest()[:32]
        order_notes = {
            "user_id": str(user.id),
            "payment_type": payment_type,
            **notes,
        }

        try:
            response = httpx.post(
                "https://api.razorpay.com/v1/orders",
                auth=(
                    settings.RAZORPAY_KEY_ID,
                    settings.RAZORPAY_KEY_SECRET,
                ),
                json={
                    "amount": amount_paise,
                    "currency": "INR",
                    "receipt": receipt,
                    "notes": order_notes,
                },
                headers={"X-Idempotency-Key": idempotency_key},
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
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an invalid order response.",
            ) from exc

        if (
            not isinstance(result, dict)
            or not isinstance(result.get("id"), str)
            or result.get("amount") != amount_paise
            or result.get("currency") != "INR"
        ):
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an inconsistent order response.",
            )

        if db is not None:
            record = PaymentRecord(
                user_id=user.id,
                booking_id=booking_id,
                amount_paise=amount_paise,
                payment_type=payment_type,
                gateway_reference=result["id"],
                idempotency_key=idempotency_key,
                status="pending",
                details={"payment_method": payment_method.value},
            )
            try:
                db.add(record)
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = (
                    db.query(PaymentRecord)
                    .filter(
                        PaymentRecord.user_id == user.id,
                        PaymentRecord.idempotency_key == idempotency_key,
                    )
                    .first()
                )
                if existing is None or existing.gateway_reference is None:
                    raise HTTPException(
                        status_code=409,
                        detail="A payment order with this idempotency key already exists.",
                    )
                result["id"] = existing.gateway_reference

        return PaymentOrderResponse(
            order_id=result["id"],
            amount=result["amount"],
            currency=result["currency"],
            key_id=settings.RAZORPAY_KEY_ID,
            payment_method=payment_method,
            message="Payment order created successfully.",
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _idempotency_key(key: str | None) -> str:
        cleaned = key.strip() if key else ""
        if cleaned:
            return cleaned
        return secrets.token_urlsafe(32)

    @staticmethod
    def _outstanding_balance_paise(db: Session, booking: Booking) -> int:
        from sqlalchemy import func

        captured = (
            db.query(func.coalesce(func.sum(PaymentRecord.amount_paise), 0))
            .filter(
                PaymentRecord.booking_id == booking.id,
                PaymentRecord.status == "captured",
                PaymentRecord.payment_type.in_(("balance", "session")),
            )
            .scalar()
        )
        total = _to_paise(booking.final_bill_amount or 0)
        return max(0, total - int(captured or 0))

    @staticmethod
    def verify_payment(
        data: PaymentVerificationRequest,
        user: User,
        db: Session | None = None,
    ) -> PaymentVerificationResponse:
        PaymentService._require_driver(user)

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

        order, payment = PaymentService._fetch_verified_payment(
            data.razorpay_order_id,
            data.razorpay_payment_id,
            expected_user_id=user.id,
        )

        record_id = None
        if db is not None:
            record = (
                db.query(PaymentRecord)
                .filter(
                    PaymentRecord.user_id == user.id,
                    PaymentRecord.gateway_reference == data.razorpay_order_id,
                )
                .with_for_update()
                .first()
            )
            if record is None:
                raise HTTPException(
                    status_code=404,
                    detail="Payment order is not registered to this account.",
                )
            if record.amount_paise != payment.get("amount"):
                raise HTTPException(
                    status_code=400,
                    detail="Captured payment amount does not match the recorded order.",
                )
            if record.status == "captured":
                if record.gateway_payment_id != data.razorpay_payment_id:
                    raise HTTPException(
                        status_code=409,
                        detail="The payment order has already been captured by another payment.",
                    )
                return PaymentVerificationResponse(
                    verified=True,
                    message="Payment was already verified.",
                    payment_record_id=record.id,
                )

            record.status = "captured"
            record.gateway_payment_id = data.razorpay_payment_id
            record.updated_at = datetime.now(timezone.utc)
            if record.booking_id is not None:
                booking = (
                    db.query(Booking)
                    .filter(Booking.id == record.booking_id, Booking.user_id == user.id)
                    .with_for_update()
                    .first()
                )
                if booking is None:
                    raise HTTPException(status_code=404, detail="Payment booking not found.")
                if record.payment_type == "reservation":
                    hold_expired = (
                        booking.hold_expires_at is None
                        or _as_utc(booking.hold_expires_at) <= datetime.now(timezone.utc)
                    )
                    if booking.status != BookingStatus.HELD or hold_expired:
                        booking.status = BookingStatus.CANCELLED
                        booking.cancellation_fee_amount = 0.0
                        db.query(BookingSlotClaim).filter(
                            BookingSlotClaim.booking_id == booking.id
                        ).delete(synchronize_session=False)
                        db.commit()
                        refund = PaymentService.refund_booking(
                            db,
                            user,
                            booking.id,
                            f"late-reservation:{record.id}",
                        )
                        return PaymentVerificationResponse(
                            verified=True,
                            message=(
                                "The booking hold expired; the captured reservation fee "
                                f"was submitted for refund ({refund.status})."
                            ),
                            payment_record_id=record.id,
                        )
                    booking.reservation_fee_paid_amount += record.amount_paise / 100
                    snapshot_booking_tariff(db, booking)
                    transition_booking_status(booking, BookingStatus.CONFIRMED)
                    booking.hold_expires_at = None
                elif record.payment_type == "balance":
                    db.flush()
                    update_payment_due(db, booking)
            db.commit()
            record_id = record.id

        return PaymentVerificationResponse(
            verified=True,
            message="Payment successfully verified and captured.",
            payment_record_id=record_id,
        )

    @staticmethod
    def _fetch_verified_payment(
        order_id: str,
        payment_id: str,
        *,
        expected_user_id: int | None = None,
    ) -> tuple[dict, dict]:
        auth = (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        try:
            order_response = httpx.get(
                f"https://api.razorpay.com/v1/orders/{order_id}",
                auth=auth,
                timeout=15.0,
            )
            order_response.raise_for_status()
            order = order_response.json()
            notes = order.get("notes") or {}
            if expected_user_id is not None and (
                not isinstance(notes, dict)
                or notes.get("user_id") != str(expected_user_id)
            ):
                raise HTTPException(
                    status_code=403,
                    detail="This payment order does not belong to your account.",
                )
            payment_response = httpx.get(
                f"https://api.razorpay.com/v1/payments/{payment_id}",
                auth=auth,
                timeout=15.0,
            )
            payment_response.raise_for_status()
            payment = payment_response.json()
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=400,
                detail="Unable to verify the Razorpay order or payment.",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is currently unreachable.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an invalid verification response.",
            ) from exc

        if (
            not isinstance(order, dict)
            or not isinstance(payment, dict)
            or order.get("id") != order_id
            or payment.get("id") != payment_id
            or payment.get("order_id") != order_id
            or payment.get("status") != "captured"
            or not payment.get("captured")
            or order.get("status") != "paid"
            or payment.get("amount") != order.get("amount")
        ):
            raise HTTPException(
                status_code=400,
                detail="Payment has not been successfully captured.",
            )
        return order, payment

    @staticmethod
    def refund_booking(
        db: Session,
        user: User,
        booking_id: int,
        idempotency_key: str,
    ) -> RefundResponse:
        PaymentService._require_driver(user)
        key = PaymentService._idempotency_key(idempotency_key)
        previous = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.user_id == user.id,
                PaymentRecord.idempotency_key == key,
            )
            .first()
        )
        if previous is not None:
            if previous.payment_type != "refund_request":
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was already used for a different operation.",
                )
            return RefundResponse(
                refund_record_id=previous.id,
                amount_paise=previous.amount_paise,
                status=previous.status,
                refund_due_at=previous.refund_due_at,
            )
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is not configured.",
            )

        booking = (
            db.query(Booking)
            .filter(Booking.id == booking_id, Booking.user_id == user.id)
            .with_for_update()
            .first()
        )
        if booking is None:
            raise HTTPException(status_code=404, detail="Booking not found.")
        if booking.status != BookingStatus.CANCELLED:
            raise HTTPException(
                status_code=409,
                detail="A refund can only be requested for a cancelled booking.",
            )

        captured = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.booking_id == booking.id,
                PaymentRecord.user_id == user.id,
                PaymentRecord.payment_type.in_(("reservation", "balance", "session")),
                PaymentRecord.status == "captured",
                PaymentRecord.gateway_payment_id.isnot(None),
            )
            .order_by(PaymentRecord.created_at.asc(), PaymentRecord.id.asc())
            .all()
        )
        already_refunded = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.booking_id == booking.id,
                PaymentRecord.payment_type == "refund",
                PaymentRecord.status.in_(("pending", "refunded")),
            )
            .with_entities(PaymentRecord.amount_paise)
            .all()
        )
        remaining_refund = max(
            0,
            sum(record.amount_paise for record in captured)
            - _to_paise(booking.cancellation_fee_amount or 0)
            - sum(amount for (amount,) in already_refunded),
        )
        if not captured:
            raise HTTPException(
                status_code=409,
                detail="No refundable captured payment remains for this booking.",
            )

        now = datetime.now(timezone.utc)
        if remaining_refund <= 0:
            return RefundResponse(
                refund_record_id=None,
                amount_paise=0,
                status="no_refund_due",
                refund_due_at=now,
            )
        refund_due_at = add_business_days(now, 5)
        parent = PaymentRecord(
            user_id=user.id,
            booking_id=booking.id,
            amount_paise=remaining_refund,
            payment_type="refund_request",
            idempotency_key=key,
            status="pending",
            refund_due_at=refund_due_at,
            details={"requested_at": now.isoformat()},
        )
        db.add(parent)
        db.commit()
        db.refresh(parent)

        remaining = remaining_refund
        child_ids: list[int] = []
        for original in captured:
            if remaining <= 0:
                break
            previously_refunded = (
                db.query(PaymentRecord)
                .filter(
                    PaymentRecord.refund_of_id == original.id,
                    PaymentRecord.payment_type == "refund",
                    PaymentRecord.status.in_(("pending", "refunded")),
                )
                .with_entities(PaymentRecord.amount_paise)
                .all()
            )
            amount = min(
                remaining,
                max(
                    0,
                    original.amount_paise
                    - sum(value for (value,) in previously_refunded),
                ),
            )
            if amount <= 0:
                continue

            failed_attempts = (
                db.query(PaymentRecord)
                .filter(
                    PaymentRecord.refund_of_id == original.id,
                    PaymentRecord.payment_type == "refund",
                    PaymentRecord.status == "failed",
                )
                .count()
            )
            child_key = "ref_" + hashlib.sha256(
                f"booking:{booking.id}:payment:{original.id}:attempt:{failed_attempts}".encode(
                    "utf-8"
                )
            ).hexdigest()
            try:
                response = httpx.post(
                    f"https://api.razorpay.com/v1/payments/"
                    f"{original.gateway_payment_id}/refund",
                    auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                    json={"amount": amount},
                    headers={"X-Idempotency-Key": child_key},
                    timeout=15.0,
                )
                response.raise_for_status()
                result = response.json()
            except httpx.HTTPStatusError as exc:
                parent.status = "failed"
                db.commit()
                raise HTTPException(
                    status_code=502,
                    detail="Payment gateway rejected the refund request.",
                ) from exc
            except httpx.RequestError as exc:
                parent.status = "failed"
                db.commit()
                raise HTTPException(
                    status_code=503,
                    detail="Payment gateway is currently unreachable.",
                ) from exc
            except ValueError as exc:
                parent.status = "failed"
                db.commit()
                raise HTTPException(
                    status_code=502,
                    detail="Payment gateway returned an invalid refund response.",
                ) from exc

            if (
                not isinstance(result, dict)
                or not isinstance(result.get("id"), str)
                or result.get("amount") != amount
            ):
                parent.status = "failed"
                db.commit()
                raise HTTPException(
                    status_code=502,
                    detail="Payment gateway returned an inconsistent refund response.",
                )

            existing_refund = (
                db.query(PaymentRecord)
                .filter(PaymentRecord.gateway_reference == result["id"])
                .first()
            )
            if existing_refund is not None:
                if (
                    existing_refund.refund_of_id != original.id
                    or existing_refund.amount_paise != amount
                ):
                    parent.status = "failed"
                    db.commit()
                    raise HTTPException(
                        status_code=409,
                        detail="Gateway refund reference conflicts with the payment ledger.",
                    )
                child_ids.append(existing_refund.id)
                remaining -= amount
                continue

            refund = PaymentRecord(
                user_id=user.id,
                booking_id=booking.id,
                refund_of_id=original.id,
                amount_paise=amount,
                payment_type="refund",
                gateway_reference=result["id"],
                idempotency_key=child_key,
                status=(
                    "refunded"
                    if result.get("status") == "processed"
                    else "pending"
                ),
                refund_due_at=refund_due_at,
            )
            db.add(refund)
            db.flush()
            child_ids.append(refund.id)
            remaining -= amount

        parent.details = {
            **(parent.details or {}),
            "refund_record_ids": child_ids,
        }
        parent.status = (
            "refunded"
            if all(
                db.get(PaymentRecord, record_id).status == "refunded"
                for record_id in child_ids
            )
            else "pending"
        )
        db.commit()
        db.refresh(parent)
        return RefundResponse(
            refund_record_id=parent.id,
            amount_paise=parent.amount_paise,
            status=parent.status,
            refund_due_at=refund_due_at,
        )

    @staticmethod
    def process_webhook(
        db: Session,
        body: bytes,
        signature: str | None,
    ) -> dict[str, str]:
        secret = settings.RAZORPAY_WEBHOOK_SECRET
        if not secret:
            raise HTTPException(
                status_code=503,
                detail="Payment webhook verification is not configured.",
            )
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is not configured.",
            )
        if not signature:
            raise HTTPException(status_code=401, detail="Payment webhook signature required.")
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            raise HTTPException(status_code=401, detail="Invalid payment webhook signature.")
        try:
            event = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(status_code=400, detail="Invalid webhook payload.") from exc
        if not isinstance(event, dict):
            raise HTTPException(status_code=400, detail="Invalid webhook payload.")

        event_name = event.get("event")
        payload = event.get("payload") or {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid webhook payload.")
        if event_name in {"refund.processed", "refund.failed"}:
            return PaymentService._process_refund_webhook(db, event_name, payload)

        payment_payload = payload.get("payment") or {}
        entity = payment_payload.get("entity") if isinstance(payment_payload, dict) else None
        if event_name not in {"payment.captured", "payment.failed"} or not isinstance(
            entity, dict
        ):
            return {"status": "ignored"}
        payment_id = entity.get("id")
        order_id = entity.get("order_id")
        if not isinstance(payment_id, str) or not isinstance(order_id, str):
            raise HTTPException(status_code=400, detail="Webhook payment reference is missing.")

        record = (
            db.query(PaymentRecord)
            .filter(PaymentRecord.gateway_reference == order_id)
            .with_for_update()
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Payment order is not registered.")
        expected_record_status = (
            "captured" if event_name == "payment.captured" else "failed"
        )
        if record.status == expected_record_status:
            return {"status": "already_processed"}

        payment, order = PaymentService._fetch_gateway_payment_event(
            order_id,
            payment_id,
            expected_status=entity.get("status"),
            expected_user_id=record.user_id,
        )
        if record.amount_paise != payment.get("amount"):
            raise HTTPException(status_code=400, detail="Webhook payment amount mismatch.")

        record.gateway_payment_id = payment_id
        record.updated_at = datetime.now(timezone.utc)
        if event_name == "payment.captured":
            if (
                order.get("status") != "paid"
                or payment.get("status") != "captured"
                or not payment.get("captured")
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Gateway has not confirmed the payment capture.",
                )
            record.status = "captured"
            if record.booking_id is not None:
                booking = (
                    db.query(Booking)
                    .filter(Booking.id == record.booking_id, Booking.user_id == record.user_id)
                    .with_for_update()
                    .first()
                )
                if booking is None:
                    raise HTTPException(status_code=404, detail="Payment booking not found.")
                if record.payment_type == "reservation":
                    if booking.status != BookingStatus.HELD:
                        raise HTTPException(
                            status_code=409,
                            detail="The booking is no longer awaiting a reservation fee.",
                        )
                    booking.reservation_fee_paid_amount += record.amount_paise / 100
                    snapshot_booking_tariff(db, booking)
                    transition_booking_status(booking, BookingStatus.CONFIRMED)
                    booking.hold_expires_at = None
                elif record.payment_type == "balance":
                    db.flush()
                    update_payment_due(db, booking)
        else:
            if payment.get("status") != "failed":
                raise HTTPException(
                    status_code=400,
                    detail="Gateway has not confirmed the payment failure.",
                )
            record.status = "failed"
            if record.booking_id is not None:
                booking = db.query(Booking).filter(Booking.id == record.booking_id).first()
                if booking is not None and record.payment_type == "balance":
                    booking.payment_due = True
        db.commit()
        return {"status": record.status}

    @staticmethod
    def _process_refund_webhook(
        db: Session,
        event_name: str,
        payload: dict,
    ) -> dict[str, str]:
        refund_entity = (payload.get("refund") or {}).get("entity")
        if not isinstance(refund_entity, dict):
            raise HTTPException(status_code=400, detail="Webhook refund data is missing.")
        refund_id = refund_entity.get("id")
        if not isinstance(refund_id, str):
            raise HTTPException(status_code=400, detail="Webhook refund reference is missing.")
        record = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.gateway_reference == refund_id,
                PaymentRecord.payment_type == "refund",
            )
            .with_for_update()
            .first()
        )
        if record is None:
            raise HTTPException(status_code=404, detail="Refund is not registered.")
        if record.status in {"refunded", "failed"}:
            return {"status": "already_processed"}

        refund = PaymentService._fetch_gateway_refund(refund_id)
        original = db.get(PaymentRecord, record.refund_of_id) if record.refund_of_id else None
        expected_status = "processed" if event_name == "refund.processed" else "failed"
        if (
            refund.get("id") != refund_id
            or refund.get("amount") != record.amount_paise
            or refund.get("status") != expected_status
            or original is None
            or refund.get("payment_id") != original.gateway_payment_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Webhook refund does not match the gateway's refund record.",
            )
        record.status = "refunded" if expected_status == "processed" else "failed"
        record.updated_at = datetime.now(timezone.utc)
        parents = (
            db.query(PaymentRecord)
            .filter(
                PaymentRecord.user_id == record.user_id,
                PaymentRecord.booking_id == record.booking_id,
                PaymentRecord.payment_type == "refund_request",
            )
            .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
            .all()
        )
        parent = next(
            (
                candidate
                for candidate in parents
                if record.id
                in (candidate.details or {}).get("refund_record_ids", [])
            ),
            None,
        )
        if parent is not None:
            child_ids = (parent.details or {}).get("refund_record_ids", [])
            children = [
                db.get(PaymentRecord, child_id)
                for child_id in child_ids
            ]
            parent.status = (
                "refunded"
                if children and all(child and child.status == "refunded" for child in children)
                else "failed"
                if expected_status == "failed"
                else "pending"
            )
        db.commit()
        return {"status": record.status}

    @staticmethod
    def _fetch_gateway_refund(refund_id: str) -> dict:
        if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
            raise HTTPException(status_code=503, detail="Payment gateway is not configured.")
        try:
            response = httpx.get(
                f"https://api.razorpay.com/v1/refunds/{refund_id}",
                auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
                timeout=15.0,
            )
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail="Unable to verify the payment refund with the gateway.",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is currently unreachable.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an invalid refund response.",
            ) from exc
        if not isinstance(result, dict):
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an invalid refund response.",
            )
        return result

    @staticmethod
    def _fetch_gateway_payment_event(
        order_id: str,
        payment_id: str,
        *,
        expected_status: str | None,
        expected_user_id: int,
    ) -> tuple[dict, dict]:
        auth = (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        try:
            order_response = httpx.get(
                f"https://api.razorpay.com/v1/orders/{order_id}",
                auth=auth,
                timeout=15.0,
            )
            order_response.raise_for_status()
            order = order_response.json()
            payment_response = httpx.get(
                f"https://api.razorpay.com/v1/payments/{payment_id}",
                auth=auth,
                timeout=15.0,
            )
            payment_response.raise_for_status()
            payment = payment_response.json()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(
                status_code=502,
                detail="Unable to verify the payment webhook with the gateway.",
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail="Payment gateway is currently unreachable.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway returned an invalid webhook verification response.",
            ) from exc
        if (
            not isinstance(order, dict)
            or not isinstance(payment, dict)
            or order.get("id") != order_id
            or payment.get("id") != payment_id
            or payment.get("order_id") != order_id
            or payment.get("status") != expected_status
            or not isinstance(order.get("notes"), dict)
            or order["notes"].get("user_id") != str(expected_user_id)
        ):
            raise HTTPException(
                status_code=400,
                detail="Payment webhook does not match the gateway's payment record.",
            )
        return payment, order

    @staticmethod
    def _require_driver(user: User) -> None:
        if user.role != UserRole.DRIVER:
            raise HTTPException(
                status_code=403,
                detail="Only drivers can manage saved payment methods.",
            )

    @staticmethod
    def save_payment_method(
        db: Session,
        user: User,
        data: SavedPaymentMethodCreate,
    ) -> SavedPaymentMethodResponse:
        PaymentService._require_driver(user)

        existing = (
            db.query(SavedPaymentMethod)
            .filter(
                SavedPaymentMethod.user_id == user.id,
                SavedPaymentMethod.gateway == "razorpay",
                SavedPaymentMethod.token_reference == data.token_reference,
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=409,
                detail="This payment method is already saved.",
            )

        has_saved_methods = (
            db.query(SavedPaymentMethod)
            .filter(SavedPaymentMethod.user_id == user.id)
            .first()
        )

        saved_method = SavedPaymentMethod(
            user_id=user.id,
            gateway="razorpay",
            token_reference=data.token_reference,
            customer_reference=data.customer_reference,
            method_type=data.method_type,
            card_network=data.card_network,
            last4=data.last4,
            is_default=not bool(has_saved_methods),
        )

        try:
            db.add(saved_method)
            db.commit()
            db.refresh(saved_method)
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="This payment token is already registered.",
            )

        return SavedPaymentMethodResponse(
            id=saved_method.id,
            method_type=saved_method.method_type,
            card_network=saved_method.card_network,
            last4=saved_method.last4,
            is_default=saved_method.is_default,
            created_at=saved_method.created_at,
        )

    @staticmethod
    def list_saved_payment_methods(
        db: Session,
        user: User,
    ) -> list[SavedPaymentMethodResponse]:
        PaymentService._require_driver(user)

        methods = (
            db.query(SavedPaymentMethod)
            .filter(SavedPaymentMethod.user_id == user.id)
            .order_by(SavedPaymentMethod.created_at.desc())
            .all()
        )

        return [
            SavedPaymentMethodResponse(
                id=method.id,
                method_type=method.method_type,
                card_network=method.card_network,
                last4=method.last4,
                is_default=method.is_default,
                created_at=method.created_at,
            )
            for method in methods
        ]

    @staticmethod
    def delete_saved_payment_method(
        db: Session,
        user: User,
        payment_method_id: int,
    ) -> None:
        PaymentService._require_driver(user)

        saved_method = (
            db.query(SavedPaymentMethod)
            .filter(
                SavedPaymentMethod.id == payment_method_id,
                SavedPaymentMethod.user_id == user.id,
            )
            .first()
        )

        if not saved_method:
            raise HTTPException(
                status_code=404,
                detail="Saved payment method not found.",
            )

        was_default = saved_method.is_default
        db.delete(saved_method)
        db.flush()

        if was_default:
            replacement = (
                db.query(SavedPaymentMethod)
                .filter(SavedPaymentMethod.user_id == user.id)
                .order_by(SavedPaymentMethod.created_at.desc())
                .first()
            )
            if replacement:
                replacement.is_default = True

        db.commit()