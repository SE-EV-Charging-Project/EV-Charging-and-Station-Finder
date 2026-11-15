
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.payment import (
    PaymentMethod,
    PaymentOrderRequest,
    PaymentOrderResponse,
    PaymentVerificationRequest,
    PaymentVerificationResponse,
)
from app.services.payment_service import PaymentService

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
    return PaymentService.create_order(
        db=db,
        user=current_user,
        data=payload,
    )


@router.post(
    "/verify",
    response_model=PaymentVerificationResponse,
)
def verify_payment(
    payload: PaymentVerificationRequest,
    current_user: User = Depends(get_current_user),
):
    return PaymentService.verify_payment(
        data=payload,
        user=current_user,
    )