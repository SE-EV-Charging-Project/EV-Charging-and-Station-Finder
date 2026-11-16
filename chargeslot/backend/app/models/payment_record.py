from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class PaymentRecord(Base):
    """Auditable gateway payment and refund ledger; monetary values are in paise."""

    __tablename__ = "payment_records"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_payment_records_user_idempotency_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    booking_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True, index=True
    )
    refund_of_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("payment_records.id", ondelete="SET NULL"), nullable=True
    )
    amount_paise: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")
    payment_type: Mapped[str] = mapped_column(String(30), nullable=False)
    gateway: Mapped[str] = mapped_column(String(30), nullable=False, default="razorpay")
    gateway_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    gateway_payment_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True, index=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    refund_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class PaymentReconciliation(Base):
    """Persisted daily comparison between the gateway and internal payment ledger."""

    __tablename__ = "payment_reconciliations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    reconciled_on: Mapped[str] = mapped_column(String(10), nullable=False, unique=True)
    gateway_payment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    internal_payment_count: Mapped[int] = mapped_column(Integer, nullable=False)
    discrepancies: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
