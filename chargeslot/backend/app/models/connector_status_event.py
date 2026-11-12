from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.charger import ConnectorStatus


class ConnectorStatusEvent(Base):
    """
    Telemetry record of status updates ingested from the charge point gateway (OCPP 1.6J)
    for a charger connector (REQ-F2-17 / CS19-043).
    """

    __tablename__ = "connector_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    connector_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chargers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    gateway_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    previous_status: Mapped[ConnectorStatus | None] = mapped_column(
        Enum(ConnectorStatus, name="connector_status_enum", native_enum=False),
        nullable=True,
    )
    new_status: Mapped[ConnectorStatus] = mapped_column(
        Enum(ConnectorStatus, name="connector_status_enum", native_enum=False),
        nullable=False,
        index=True,
    )
    raw_status: Mapped[str] = mapped_column(String(50), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(
        String(120), nullable=True, unique=True, index=True
    )

    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    connector = relationship("Connector")
    charger = relationship("Charger")

