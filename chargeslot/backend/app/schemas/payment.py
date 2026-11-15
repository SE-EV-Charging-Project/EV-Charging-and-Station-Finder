
from datetime import datetime
from enum import Enum
from typing import Literal

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator



class PaymentMethod(str, Enum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"


class PaymentOrderRequest(BaseModel):
    vehicle_id: int = Field(gt=0)
    station_id: int = Field(gt=0)
    target_soc: int = Field(ge=1, le=100)
    payment_method: PaymentMethod
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class PaymentOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    payment_method: PaymentMethod
    message: str
    idempotency_key: str | None = None


class BookingPaymentOrderRequest(BaseModel):
    payment_method: PaymentMethod
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


class PaymentVerificationResponse(BaseModel):
    verified: bool
    message: str
    payment_record_id: int | None = None


class RefundRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=120)


class RefundResponse(BaseModel):
    refund_record_id: int | None
    amount_paise: int
    status: str
    refund_due_at: datetime


class PaymentHistoryItem(BaseModel):
    id: int
    booking_id: int | None
    amount_paise: int
    currency: str
    payment_type: str
    gateway_reference: str | None
    gateway_payment_id: str | None
    status: str
    created_at: datetime
    invoice_url: str | None = None

class SavedPaymentMethodCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_reference: str = Field(min_length=1, max_length=255)
    customer_reference: str | None = Field(default=None, max_length=255)
    method_type: Literal["card"]
    card_network: str | None = Field(default=None, max_length=50)
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    customer_consent: Literal[True]

    @field_validator("token_reference")
    @classmethod
    def reject_card_data(cls, value: str) -> str:
        token = value.strip()
        if not token:
            raise ValueError("A gateway token is required.")
        if re.fullmatch(r"[\d\s-]+", token):
            digits = re.sub(r"\D", "", token)
            if 12 <= len(digits) <= 19 or 3 <= len(digits) <= 6:
                raise ValueError("Card numbers, CVVs, and PINs cannot be stored.")
        return token


class SavedPaymentMethodResponse(BaseModel):
    id: int
    method_type: str
    card_network: str | None
    last4: str | None
    is_default: bool
    created_at: datetime
