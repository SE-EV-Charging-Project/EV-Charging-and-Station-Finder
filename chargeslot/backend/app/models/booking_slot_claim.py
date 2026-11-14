from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class BookingSlotClaim(Base):
    """Atomic 15-minute charger interval claim for an active booking."""

    __tablename__ = "booking_slot_claims"
    __table_args__ = (
        UniqueConstraint(
            "charger_id",
            "slot_start_time",
            name="uq_booking_slot_claim_charger_start",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    charger_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("chargers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    slot_start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    booking_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("bookings.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
