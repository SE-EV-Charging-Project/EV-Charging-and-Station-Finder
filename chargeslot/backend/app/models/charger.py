import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base
from app.models.vehicle import ConnectorType


class CurrentType(str, enum.Enum):
    """
    Current electrical feed type: AC or DC (Appendix B.4).
    """
    AC = "AC"
    DC = "DC"


class ConnectorStatus(str, enum.Enum):
    """
    Connector status enum (SRS Appendix B.4):
    Available, Occupied, Reserved, Faulted, Offline.
    """
    AVAILABLE = "Available"
    OCCUPIED = "Occupied"
    RESERVED = "Reserved"
    FAULTED = "Faulted"
    OFFLINE = "Offline"


class Charger(Base):
    """
    Charger Model (REQ-F2-02 / Appendix B.4 / CS19-028).
    Represents an EV charger unit belonging to a station with a power rating,
    current type, and gateway hardware identifier.
    """
    __tablename__ = "chargers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    power_kw: Mapped[float] = mapped_column(Float, nullable=False)
    current_type: Mapped[CurrentType] = mapped_column(
        Enum(CurrentType, name="current_type_enum", native_enum=False),
        nullable=False,
    )
    gateway_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_out_of_service: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    out_of_service_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    expected_return_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    out_of_service_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

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

    station = relationship("Station", back_populates="chargers")
    connectors = relationship("Connector", back_populates="charger", cascade="all, delete-orphan")
    maintenance_windows = relationship("MaintenanceWindow", back_populates="charger", cascade="all, delete-orphan")


class Connector(Base):
    """
    Connector Model (REQ-F2-02 / Appendix B.4 / CS19-028).
    Represents an individual physical charging plug/port on a charger.
    """
    __tablename__ = "connectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    charger_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("chargers.id", ondelete="CASCADE"), nullable=False, index=True
    )

    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, name="connector_type_enum", native_enum=False),
        nullable=False,
    )
    status: Mapped[ConnectorStatus] = mapped_column(
        Enum(ConnectorStatus, name="connector_status_enum", native_enum=False),
        default=ConnectorStatus.AVAILABLE,
        nullable=False,
        index=True,
    )
    last_update: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
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

    charger = relationship("Charger", back_populates="connectors")
