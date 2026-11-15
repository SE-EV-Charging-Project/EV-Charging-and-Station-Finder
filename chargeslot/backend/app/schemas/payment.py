
from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field



class PaymentMethod(str, Enum):
    UPI = "upi"
    CARD = "card"
    NETBANKING = "netbanking"


class PaymentOrderRequest(BaseModel):
    vehicle_id: int = Field(gt=0)
    station_id: int = Field(gt=0)
    target_soc: int = Field(ge=1, le=100)
    payment_method: PaymentMethod


class PaymentOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    key_id: str
    payment_method: PaymentMethod
    message: str


class PaymentVerificationRequest(BaseModel):
    razorpay_order_id: str = Field(min_length=1)
    razorpay_payment_id: str = Field(min_length=1)
    razorpay_signature: str = Field(min_length=1)


class PaymentVerificationResponse(BaseModel):
    verified: bool
    message: str

class SavedPaymentMethodCreate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token_reference: str = Field(min_length=1, max_length=255)
    customer_reference: str | None = Field(default=None, max_length=255)
    method_type: Literal["card"]
    card_network: str | None = Field(default=None, max_length=50)
    last4: str | None = Field(default=None, pattern=r"^\d{4}$")
    customer_consent: Literal[True]


class SavedPaymentMethodResponse(BaseModel):
    id: int
    method_type: str
    card_network: str | None
    last4: str | None
    is_default: bool
    created_at: datetime
