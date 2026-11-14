import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class SessionStopCommandStatus(str, enum.Enum):
    PENDING = "Pending"
    ACCEPTED = "Accepted"
    REJECTED = "Rejected"
    COMPLETED = "Completed"


class SessionStopCommandTrigger(str, enum.Enum):
    DRIVER = "driver"
    TARGET_ENERGY = "target_energy"


class ChargingSessionCommand(Base):
    """Durable OCPP RemoteStopTransaction request awaiting gateway delivery."""

    __tablename__ = "charging_session_commands"

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
    transaction_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    trigger: Mapped[SessionStopCommandTrigger] = mapped_column(
        Enum(
            SessionStopCommandTrigger,
            name="session_stop_command_trigger_enum",
            native_enum=False,
        ),
        nullable=False,
    )
    status: Mapped[SessionStopCommandStatus] = mapped_column(
        Enum(
            SessionStopCommandStatus,
            name="session_stop_command_status_enum",
            native_enum=False,
        ),
        default=SessionStopCommandStatus.PENDING,
        nullable=False,
        index=True,
    )
    requested_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    responded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
