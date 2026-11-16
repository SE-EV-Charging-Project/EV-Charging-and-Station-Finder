from datetime import date, datetime, time, timedelta, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.payment_record import PaymentRecord, PaymentReconciliation
from app.models.user import User, UserRole
from app.schemas.billing import ReconciliationResponse

PAGE_SIZE = 100
MAX_GATEWAY_PAYMENTS = 10_000


def reconcile_daily(
    db: Session,
    user: User,
    reconciled_on: date | None = None,
) -> ReconciliationResponse:
    if user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Only administrators can reconcile payments.")
    if not settings.RAZORPAY_KEY_ID or not settings.RAZORPAY_KEY_SECRET:
        raise HTTPException(status_code=503, detail="Payment gateway is not configured.")

    day = reconciled_on or datetime.now(timezone.utc).date() - timedelta(days=1)
    start = datetime.combine(day, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    gateway_payments: list[dict] = []
    auth = (settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)

    try:
        for offset in range(0, MAX_GATEWAY_PAYMENTS, PAGE_SIZE):
            response = httpx.get(
                "https://api.razorpay.com/v1/payments",
                auth=auth,
                params={
                    "from": int(start.timestamp()),
                    "to": int(end.timestamp()) - 1,
                    "count": PAGE_SIZE,
                    "skip": offset,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise HTTPException(
                    status_code=502,
                    detail="Payment gateway returned an invalid reconciliation response.",
                )
            gateway_payments.extend(item for item in items if isinstance(item, dict))
            if len(items) < PAGE_SIZE:
                break
        else:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway reconciliation exceeded the supported daily volume.",
            )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway rejected the reconciliation request.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Payment gateway is currently unreachable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway returned an invalid reconciliation response.",
        ) from exc

    gateway_refunds: list[dict] = []
    try:
        for offset in range(0, MAX_GATEWAY_PAYMENTS, PAGE_SIZE):
            response = httpx.get(
                "https://api.razorpay.com/v1/refunds",
                auth=auth,
                params={
                    "from": int(start.timestamp()),
                    "to": int(end.timestamp()) - 1,
                    "count": PAGE_SIZE,
                    "skip": offset,
                },
                timeout=20.0,
            )
            response.raise_for_status()
            payload = response.json()
            items = payload.get("items") if isinstance(payload, dict) else None
            if not isinstance(items, list):
                raise HTTPException(
                    status_code=502,
                    detail="Payment gateway returned an invalid refund reconciliation response.",
                )
            gateway_refunds.extend(item for item in items if isinstance(item, dict))
            if len(items) < PAGE_SIZE:
                break
        else:
            raise HTTPException(
                status_code=502,
                detail="Payment gateway refund reconciliation exceeded the supported daily volume.",
            )
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway rejected the refund reconciliation request.",
        ) from exc
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=503,
            detail="Payment gateway is currently unreachable.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail="Payment gateway returned an invalid refund reconciliation response.",
        ) from exc

    internal = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.status == "captured",
            PaymentRecord.payment_type.in_(("reservation", "balance", "session")),
            PaymentRecord.updated_at >= start,
            PaymentRecord.updated_at < end,
        )
        .all()
    )
    internal_refunds = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.payment_type == "refund",
            PaymentRecord.status.in_(("pending", "refunded", "failed")),
            PaymentRecord.updated_at >= start,
            PaymentRecord.updated_at < end,
        )
        .all()
    )
    gateway_by_id = {
        payment.get("id"): payment
        for payment in gateway_payments
        if isinstance(payment.get("id"), str)
    }
    internal_by_id = {
        record.gateway_payment_id: record
        for record in internal
        if record.gateway_payment_id is not None
    }

    discrepancies: list[dict] = []
    for payment_id, record in internal_by_id.items():
        gateway_payment = gateway_by_id.get(payment_id)
        if gateway_payment is None:
            discrepancies.append(
                {"type": "missing_from_gateway", "payment_id": payment_id}
            )
            continue
        if (
            gateway_payment.get("amount") != record.amount_paise
            or gateway_payment.get("status") != "captured"
        ):
            discrepancies.append(
                {
                    "type": "payment_mismatch",
                    "payment_id": payment_id,
                    "internal_amount_paise": record.amount_paise,
                    "gateway_amount_paise": gateway_payment.get("amount"),
                    "gateway_status": gateway_payment.get("status"),
                }
            )
    for payment_id in gateway_by_id.keys() - internal_by_id.keys():
        gateway_payment = gateway_by_id[payment_id]
        if gateway_payment.get("status") == "captured":
            discrepancies.append(
                {
                    "type": "missing_from_internal_ledger",
                    "payment_id": payment_id,
                    "amount_paise": gateway_payment.get("amount"),
                }
            )

    gateway_refunds_by_id = {
        refund.get("id"): refund
        for refund in gateway_refunds
        if isinstance(refund.get("id"), str)
    }
    internal_refunds_by_id = {
        refund.gateway_reference: refund
        for refund in internal_refunds
        if refund.gateway_reference is not None
    }
    for refund_id, record in internal_refunds_by_id.items():
        gateway_refund = gateway_refunds_by_id.get(refund_id)
        if gateway_refund is None:
            discrepancies.append(
                {"type": "refund_missing_from_gateway", "refund_id": refund_id}
            )
        elif (
            gateway_refund.get("amount") != record.amount_paise
            or gateway_refund.get("payment_id")
            != (
                db.get(PaymentRecord, record.refund_of_id).gateway_payment_id
                if record.refund_of_id and db.get(PaymentRecord, record.refund_of_id)
                else None
            )
        ):
            discrepancies.append(
                {
                    "type": "refund_mismatch",
                    "refund_id": refund_id,
                    "internal_amount_paise": record.amount_paise,
                    "gateway_amount_paise": gateway_refund.get("amount"),
                }
            )
    for refund_id in gateway_refunds_by_id.keys() - internal_refunds_by_id.keys():
        gateway_refund = gateway_refunds_by_id[refund_id]
        discrepancies.append(
            {
                "type": "refund_missing_from_internal_ledger",
                "refund_id": refund_id,
                "amount_paise": gateway_refund.get("amount"),
            }
        )

    run = (
        db.query(PaymentReconciliation)
        .filter(PaymentReconciliation.reconciled_on == day.isoformat())
        .first()
    )
    if run is None:
        run = PaymentReconciliation(reconciled_on=day.isoformat())
        db.add(run)
    run.gateway_payment_count = len(gateway_payments)
    run.internal_payment_count = len(internal)
    run.discrepancies = discrepancies
    run.created_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(run)
    return ReconciliationResponse.model_validate(
        {
            "reconciled_on": run.reconciled_on,
            "gateway_payment_count": run.gateway_payment_count,
            "internal_payment_count": run.internal_payment_count,
            "discrepancies": run.discrepancies,
            "created_at": run.created_at,
        }
    )
