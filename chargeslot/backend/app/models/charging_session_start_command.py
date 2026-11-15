import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SessionStartCommandStatus(str, enum.Enum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    STARTED = "Started"
    FAILED = "Failed"


class ChargingSessionStartCommand(Base):
    """Durable OCPP RemoteStartTransaction request awaiting gateway delivery."""

    __tablename__ = "charging_session_start_commands"
    __table_args__ = (
        UniqueConstraint(
            "idempotency_key",
            name="uq_charging_session_start_commands_idempotency_key",
        ),
        UniqueConstraint(
            "start_event_idempotency_key",
            name="uq_charging_session_start_commands_start_event_key",
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
    requested_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    start_event_idempotency_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True
    )
    status: Mapped[SessionStartCommandStatus] = mapped_column(
        Enum(
            SessionStartCommandStatus,
            name="session_start_command_status_enum",
            native_enum=False,
        ),
        default=SessionStartCommandStatus.PENDING,
        nullable=False,
        index=True,
    )
    transaction_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
