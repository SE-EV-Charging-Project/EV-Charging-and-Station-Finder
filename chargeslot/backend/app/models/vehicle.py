import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class ConnectorType(str, enum.Enum):
    CCS2 = "CCS2"
    CHADEMO = "CHAdeMO"
    TYPE_2 = "Type 2"
    GBT = "GB/T"


class Vehicle(Base):
    """
    EV Vehicle model (REQ-F1-18 / Appendix B.3 / CS19-018).
    Represents an electric vehicle owned by a driver, specifying charging specifications
    and battery capacity for route and slot calculation.
    """
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    make: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str] = mapped_column(String(40), nullable=False)
    battery_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    connector_type: Mapped[ConnectorType] = mapped_column(
        Enum(ConnectorType, name="connector_type_enum", native_enum=False),
        nullable=False
    )
    max_ac_kw: Mapped[float] = mapped_column(Float, nullable=False)
    max_dc_kw: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    consumption_kwh_100km: Mapped[float] = mapped_column(Float, nullable=False)
    registration_no: Mapped[str | None] = mapped_column(String(15), nullable=True, index=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

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

    user = relationship("User", back_populates="vehicles")
