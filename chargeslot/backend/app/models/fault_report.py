import enum
from datetime import datetime, timezone
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class FaultReportStatus(str, enum.Enum):
    FORWARDED = "forwarded"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class FaultSeverity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FaultType(str, enum.Enum):
    HARDWARE_FAULT = "hardware_fault"
    CONNECTOR_DAMAGE = "connector_damage"
    POWER_FAILURE = "power_failure"
    CABLE_DAMAGE = "cable_damage"
    SCREEN_ISSUE = "screen_issue"
    OFFLINE = "offline"
    OTHER = "other"


class FaultyChargerReport(Base):
    """
    Faulty charger report submitted by a driver and forwarded to the station operator
    (REQ-F2-16 / CS19-042).
    """

    __tablename__ = "faulty_charger_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    reporter_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    operator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    station_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    charger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chargers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    connector_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("connectors.id", ondelete="SET NULL"), nullable=True, index=True
    )

    fault_type: Mapped[FaultType] = mapped_column(
        Enum(FaultType, name="fault_type_enum", native_enum=False),
        default=FaultType.HARDWARE_FAULT,
        nullable=False,
    )
    severity: Mapped[FaultSeverity] = mapped_column(
        Enum(FaultSeverity, name="fault_severity_enum", native_enum=False),
        default=FaultSeverity.MEDIUM,
        nullable=False,
    )
    description: Mapped[str] = mapped_column(String(1000), nullable=False)

    status: Mapped[FaultReportStatus] = mapped_column(
        Enum(FaultReportStatus, name="fault_report_status_enum", native_enum=False),
        default=FaultReportStatus.FORWARDED,
        nullable=False,
        index=True,
    )
    forwarded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    forwarded_channels: Mapped[str] = mapped_column(String(100), default="in_app", nullable=False)
    forwarded_to_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    forwarded_to_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    operator_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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

    reporter = relationship("User", foreign_keys=[reporter_user_id])
    operator = relationship("User", foreign_keys=[operator_id])
    station = relationship("Station")
    charger = relationship("Charger")
    connector = relationship("Connector")

