from datetime import date, datetime, timezone
import secrets
from pydantic import BaseModel
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.station import Station
from app.models.user import User, UserRole

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.db.session import get_db
from app.models.booking import Booking, BookingStatus
from app.models.payment_record import PaymentRecord
from app.models.user import User
from app.schemas.payment import (
    BookingPaymentOrderRequest,
    PaymentMethod,
    PaymentHistoryItem,
    PaymentOrderRequest,
    PaymentOrderResponse,
    RefundRequest,
    RefundResponse,
    PaymentVerificationRequest,
    PaymentVerificationResponse,
    SavedPaymentMethodCreate,
    SavedPaymentMethodResponse,
)
from app.schemas.billing import ReconciliationResponse
from app.services.payment_service import PaymentService
from app.services.reconciliation_service import reconcile_daily

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.get("/methods")
def get_payment_methods():
    return {
        "methods": [
            {"id": method.value, "name": name}
            for method, name in [
                (PaymentMethod.UPI, "UPI"),
                (PaymentMethod.CARD, "Debit/Credit Card"),
                (PaymentMethod.NETBANKING, "Net Banking"),
            ]
        ]
    }


@router.post("/orders", response_model=PaymentOrderResponse)
def create_payment_order(
    payload: PaymentOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return PaymentService.create_order(db=db, user=current_user, data=payload)


@router.post("/verify", response_model=PaymentVerificationResponse)
def verify_payment(
    payload: PaymentVerificationRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return PaymentService.verify_payment(data=payload, user=current_user, db=db)


@router.post(
    "/bookings/{booking_id}/reservation/order",
    response_model=PaymentOrderResponse,
)
def create_reservation_fee_order(
    booking_id: int,
    payload: BookingPaymentOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderResponse:
    return PaymentService.create_booking_order(
        db, current_user, booking_id, payload, payment_type="reservation"
    )


@router.post(
    "/bookings/{booking_id}/balance/order",
    response_model=PaymentOrderResponse,
)
def create_balance_order(
    booking_id: int,
    payload: BookingPaymentOrderRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> PaymentOrderResponse:
    return PaymentService.create_booking_order(
        db, current_user, booking_id, payload, payment_type="balance"
    )


@router.post(
    "/bookings/{booking_id}/refund",
    response_model=RefundResponse,
)
def refund_booking(
    booking_id: int,
    payload: RefundRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> RefundResponse:
    return PaymentService.refund_booking(
        db, current_user, booking_id, payload.idempotency_key
    )


@router.get("/history", response_model=list[PaymentHistoryItem])
def payment_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[PaymentHistoryItem]:
    PaymentService._require_driver(current_user)
    records = (
        db.query(PaymentRecord)
        .filter(PaymentRecord.user_id == current_user.id)
        .order_by(PaymentRecord.created_at.desc(), PaymentRecord.id.desc())
        .all()
    )
    bookings = {
        booking.id: booking
        for booking in db.query(Booking)
        .filter(
            Booking.id.in_(
                [record.booking_id for record in records if record.booking_id is not None]
                or [-1]
            )
        )
        .all()
    }
    return [
        PaymentHistoryItem(
            id=record.id,
            booking_id=record.booking_id,
            amount_paise=record.amount_paise,
            currency=record.currency,
            payment_type=record.payment_type,
            gateway_reference=record.gateway_reference,
            gateway_payment_id=record.gateway_payment_id,
            status=record.status,
            created_at=record.created_at,
            invoice_url=(
                f"/api/v1/billing/bookings/{record.booking_id}/invoice"
                if record.booking_id in bookings
                and bookings[record.booking_id].status == BookingStatus.COMPLETED
                and not bookings[record.booking_id].payment_due
                and record.status == "captured"
                else None
            ),
        )
        for record in records
    ]


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def payment_webhook(
    request: Request,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if request.url.scheme.lower() != "https":
        raise HTTPException(
            status_code=400,
            detail="Payment webhooks must be received over HTTPS.",
        )
    return PaymentService.process_webhook(
        db,
        await request.body(),
        x_razorpay_signature,
    )


@router.post(
    "/reconciliation/daily",
    response_model=ReconciliationResponse,
)
def run_daily_reconciliation(
    reconciled_on: date | None = None,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> ReconciliationResponse:
    return reconcile_daily(db, current_user, reconciled_on)


@router.post(
    "/saved-methods",
    response_model=SavedPaymentMethodResponse,
    status_code=status.HTTP_201_CREATED,
)
def save_payment_method(
    payload: SavedPaymentMethodCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return PaymentService.save_payment_method(
        db=db, user=current_user, data=payload
    )


@router.get(
    "/saved-methods",
    response_model=list[SavedPaymentMethodResponse],
)
def list_saved_payment_methods(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return PaymentService.list_saved_payment_methods(db=db, user=current_user)


@router.delete(
    "/saved-methods/{payment_method_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_saved_payment_method(
    payment_method_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    PaymentService.delete_saved_payment_method(
        db=db, user=current_user, payment_method_id=payment_method_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------
# Interactive Demo / Localhost Gateway Endpoints
# --------------------------------------------------------------------------
class DemoPaymentPreviewResponse(BaseModel):
    booking_id: int
    station_name: str
    price_per_kwh: float
    est_energy_kwh: float
    energy_cost: float
    tax_amount: float
    total_amount: float


class DemoPaymentRequest(BaseModel):
    booking_id: int
    payment_method: str = "upi"
    energy_kwh: float | None = None


class DemoPaymentResponse(BaseModel):
    booking_id: int
    payment_id: int
    transaction_id: str
    amount_inr: float
    payment_method: str
    status: str
    message: str
    invoice_url: str


@router.get("/demo/preview/{booking_id}", response_model=DemoPaymentPreviewResponse)
def demo_preview_payment(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoPaymentPreviewResponse:
    PaymentService._require_driver(current_user)
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if current_user.role == UserRole.DRIVER and booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this booking.")

    station = db.query(Station).filter(Station.id == booking.station_id).first() if booking.station_id else None
    price_per_kwh = float(station.price_per_kwh if station and station.price_per_kwh else 15.0)
    station_name = station.name if station else "ChargeSlot Hub"

    energy_kwh = float(booking.est_energy_kwh or 22.5)
    energy_cost = round(energy_kwh * price_per_kwh, 2)
    tax_rate = 0.05
    tax_amount = round(energy_cost * tax_rate, 2)
    total_amount = round(energy_cost + tax_amount, 2)

    return DemoPaymentPreviewResponse(
        booking_id=booking.id,
        station_name=station_name,
        price_per_kwh=price_per_kwh,
        est_energy_kwh=energy_kwh,
        energy_cost=energy_cost,
        tax_amount=tax_amount,
        total_amount=total_amount,
    )


@router.post("/demo/complete-and-pay", response_model=DemoPaymentResponse)
def demo_complete_and_pay(
    payload: DemoPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DemoPaymentResponse:
    PaymentService._require_driver(current_user)
    booking = db.query(Booking).filter(Booking.id == payload.booking_id).first()
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if current_user.role == UserRole.DRIVER and booking.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this booking.")

    station = db.query(Station).filter(Station.id == booking.station_id).first() if booking.station_id else None
    price_per_kwh = float(station.price_per_kwh if station and station.price_per_kwh else 15.0)

    energy_kwh = float(payload.energy_kwh or booking.est_energy_kwh or 22.5)
    energy_cost = round(energy_kwh * price_per_kwh, 2)
    tax_rate = 0.05  # 5% GST
    tax_amount = round(energy_cost * tax_rate, 2)
    idle_fee = 0.0
    total_amount = round(energy_cost + tax_amount + idle_fee, 2)

    now = datetime.now(timezone.utc)
    booking.status = BookingStatus.COMPLETED
    booking.session_ended_at = now
    booking.energy_delivered_kwh = energy_kwh
    booking.energy_cost_amount = energy_cost
    booking.tax_amount = tax_amount
    booking.idle_fee_amount = idle_fee
    booking.final_bill_amount = total_amount
    booking.payment_due = False
    if booking.reservation_fee_paid_amount is None:
        booking.reservation_fee_paid_amount = 0.0

    # Delete slot claim so charger is free
    db.query(BookingSlotClaim).filter(BookingSlotClaim.booking_id == booking.id).delete(synchronize_session=False)

    # Record captured payment
    txn_id = f"CS-PAY-{now.strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"
    payment_record = PaymentRecord(
        user_id=current_user.id,
        booking_id=booking.id,
        amount_paise=int(round(total_amount * 100)),
        currency="INR",
        payment_type="session",
        gateway_reference=f"order_{secrets.token_hex(8)}",
        gateway_payment_id=txn_id,
        idempotency_key=f"demo-pay-{booking.id}-{secrets.token_hex(4)}",
        status="captured",
        details={
            "payment_method": payload.payment_method,
            "demo": True,
            "simulated_at": now.isoformat(),
        },
    )
    db.add(payment_record)
    db.commit()
    db.refresh(payment_record)

    return DemoPaymentResponse(
        booking_id=booking.id,
        payment_id=payment_record.id,
        transaction_id=txn_id,
        amount_inr=total_amount,
        payment_method=payload.payment_method,
        status="captured",
        message="Payment processed and session marked COMPLETED. Tax invoice is now available for download.",
        invoice_url=f"/api/v1/billing/bookings/{booking.id}/invoice",
    )

