
from enum import Enum
from pydantic import BaseModel, Field


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
