from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class InAppNotification(Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_in_app_notifications_dedupe_key"),
        Index("ix_in_app_notifications_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    notification_type: Mapped[str] = mapped_column(String(60), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
