from datetime import datetime, timezone
from sqlalchemy import Integer, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class FavouriteStation(Base):
    """
    Driver favourite charging station link table (REQ-F2-14 / CS19-040).
    Associates a driver user account with saved EV charging stations.
    """

    __tablename__ = "favourite_stations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "station_id",
            name="uq_favourite_stations_user_station",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    station_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("stations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user = relationship("User", back_populates="favourite_stations")
    station = relationship("Station", back_populates="favourited_by")

