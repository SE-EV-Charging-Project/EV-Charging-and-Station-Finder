import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, DateTime, ForeignKey, Enum, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class StationStatus(str, enum.Enum):
    """
    Approval and operational lifecycle status for stations
    (SRS REQ-F2-01, REQ-F2-03, Appendix B.4).
    """
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    INACTIVE = "inactive"


class Station(Base):
    """
    Station Model (REQ-F2-01 / Appendix B.4 / CS19-027).
    Represents an EV charging station managed by a Station Operator, containing
    location, amenities, operating hours, and contact details.
    """
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    operator_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    address: Mapped[str] = mapped_column(String(200), nullable=False)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)

    amenities: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    operating_hours: Mapped[str] = mapped_column(String(100), default="24 hours", nullable=False)
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    contact_email: Mapped[str | None] = mapped_column(String(120), nullable=True)
    price_per_kwh: Mapped[float | None] = mapped_column(Float, nullable=True, default=None)

    status: Mapped[StationStatus] = mapped_column(
        Enum(StationStatus, name="station_status_enum", native_enum=False),
        default=StationStatus.PENDING,
        nullable=False,
        index=True,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)

    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    reviewed_by_admin_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    operator = relationship("User", foreign_keys=[operator_id], back_populates="stations")
    reviewer = relationship("User", foreign_keys=[reviewed_by_admin_id])
    chargers = relationship("Charger", back_populates="station", cascade="all, delete-orphan")
    maintenance_windows = relationship("MaintenanceWindow", back_populates="station", cascade="all, delete-orphan")
    favourited_by = relationship("FavouriteStation", back_populates="station", cascade="all, delete-orphan")
