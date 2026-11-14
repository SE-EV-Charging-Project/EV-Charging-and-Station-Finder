import enum
from datetime import datetime, timezone
from sqlalchemy import (
    String,
    Integer,
    Float,
    DateTime,
    ForeignKey,
    Enum,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class BookingStatus(str, enum.Enum):
    """
    Booking status values as defined in SRS Appendix B.5.
    """
    HELD = "Held"
    CONFIRMED = "Confirmed"
    ACTIVE = "Active"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"
    NO_SHOW = "No-Show"
    EXPIRED = "Expired"
    REASSIGNED = "Reassigned"


class Booking(Base):
    """
    Booking model (SRS §5.3 / Appendix B.5 / REQ-F1-25).
    Tracks reservations for charging slots linked to a user and vehicle.
    """
    __tablename__ = "bookings"
    __table_args__ = (
        UniqueConstraint(
            "stop_event_idempotency_key",
            name="uq_bookings_stop_event_idempotency_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True, index=True)

    station_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    charger_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    connector_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("connectors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    slot_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    start_soc: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    target_soc: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    est_energy_kwh: Mapped[float | None] = mapped_column(Float, nullable=True)
    est_duration_min: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    booking_type: Mapped[str] = mapped_column(String(10), default="manual", nullable=False)

    status: Mapped[BookingStatus] = mapped_column(
        Enum(BookingStatus, name="booking_status_enum", native_enum=False),
        default=BookingStatus.CONFIRMED,
        nullable=False,
        index=True,
    )

    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    hold_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancellation_fee_amount: Mapped[float] = mapped_column(
        Float,
        default=0.0,
        nullable=False,
    )
    session_ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    meter_stop_wh: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stop_event_idempotency_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", back_populates="bookings")
    vehicle = relationship("Vehicle", back_populates="bookings")
    connector = relationship("Connector", foreign_keys=[connector_id])
    review = relationship("StationReview", back_populates="booking", uselist=False, cascade="all, delete-orphan")
