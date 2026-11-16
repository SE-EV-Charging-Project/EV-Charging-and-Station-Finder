from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class StationTariff(Base):
    """An immutable, effective-dated station tariff."""

    __tablename__ = "station_tariffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    station_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    price_per_kwh: Mapped[float] = mapped_column(Float, nullable=False)
    idle_fee_per_minute: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    tax_rate_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    peak_periods: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    station = relationship("Station", back_populates="tariffs")
