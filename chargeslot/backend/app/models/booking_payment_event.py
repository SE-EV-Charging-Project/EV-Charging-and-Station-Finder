import enum
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BookingPaymentEventStatus(str, enum.Enum):
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    REFUND_DUE = "RefundDue"


class BookingPaymentEvent(Base):
    """Provider-verified reservation payment event; this ledger does not move funds."""

    __tablename__ = "booking_payment_events"
    __table_args__ = (
        UniqueConstraint(
            "provider_event_id",
            name="uq_booking_payment_events_provider_event_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider_event_id: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    amount_inr: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[BookingPaymentEventStatus] = mapped_column(
        Enum(
            BookingPaymentEventStatus,
            name="booking_payment_event_status_enum",
            native_enum=False,
        ),
        nullable=False,
    )
    refund_due: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
