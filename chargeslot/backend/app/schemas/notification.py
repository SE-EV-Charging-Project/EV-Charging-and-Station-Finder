from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class InAppNotificationItem(BaseModel):
    id: int
    notification_type: str
    title: str
    message: str
    payload: dict[str, Any]
    created_at: datetime
    read_at: datetime | None


class InAppNotificationListResponse(BaseModel):
    notifications: list[InAppNotificationItem] = Field(default_factory=list)
    unread_count: int


class InAppNotificationReadResponse(BaseModel):
    id: int
    read_at: datetime
