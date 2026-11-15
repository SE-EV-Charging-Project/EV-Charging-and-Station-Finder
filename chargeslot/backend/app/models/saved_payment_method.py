from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class SavedPaymentMethod(Base):
    """Stores gateway token references, never raw payment credentials."""

    __tablename__ = "saved_payment_methods"
    __table_args__ = (
        UniqueConstraint(
            "gateway",
            "token_reference",
            name="uq_saved_payment_methods_gateway_token",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, index=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    gateway: Mapped[str] = mapped_column(
        String(30), nullable=False, default="razorpay"
    )
    token_reference: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    customer_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    method_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )
    card_network: Mapped[str | None] = mapped_column(
        String(50), nullable=True
    )
    last4: Mapped[str | None] = mapped_column(
        String(4), nullable=True
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", back_populates="saved_payment_methods")
