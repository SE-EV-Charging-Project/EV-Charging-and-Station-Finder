from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class ChargingSessionReading(Base):
    """Meter telemetry received for a booked charging session (REQ-F3-29)."""

    __tablename__ = "charging_session_readings"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_charging_session_readings_idempotency_key",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    booking_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chargers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    energy_meter_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
