from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.in_app_notification import InAppNotification
from app.models.user import User
from app.schemas.notification import (
    InAppNotificationItem,
    InAppNotificationListResponse,
    InAppNotificationReadResponse,
)


def create_in_app_notification(
    db: Session,
    *,
    user_id: int,
    notification_type: str,
    title: str,
    message: str,
    payload: dict[str, Any],
    dedupe_key: str,
) -> InAppNotification:
    existing = (
        db.query(InAppNotification)
        .filter(InAppNotification.dedupe_key == dedupe_key)
        .first()
    )
    if existing is not None:
        return existing
    notification = InAppNotification(
        user_id=user_id,
        notification_type=notification_type,
        title=title,
        message=message,
        payload=payload,
        dedupe_key=dedupe_key,
    )
    db.add(notification)
    db.flush()
    return notification


def list_in_app_notifications(
    db: Session,
    *,
    user: User,
    unread_only: bool,
    limit: int,
) -> InAppNotificationListResponse:
    query = db.query(InAppNotification).filter(
        InAppNotification.user_id == user.id
    )
    if unread_only:
        query = query.filter(InAppNotification.read_at.is_(None))
    notifications = (
        query.order_by(
            InAppNotification.created_at.desc(),
            InAppNotification.id.desc(),
        )
        .limit(limit)
        .all()
    )
    unread_count = (
        db.query(InAppNotification)
        .filter(
            InAppNotification.user_id == user.id,
            InAppNotification.read_at.is_(None),
        )
        .count()
    )
    return InAppNotificationListResponse(
        notifications=[
            InAppNotificationItem(
                id=item.id,
                notification_type=item.notification_type,
                title=item.title,
                message=item.message,
                payload=item.payload,
                created_at=item.created_at,
                read_at=item.read_at,
            )
            for item in notifications
        ],
        unread_count=unread_count,
    )


def mark_in_app_notification_read(
    db: Session,
    *,
    user: User,
    notification_id: int,
) -> InAppNotificationReadResponse:
    notification = (
        db.query(InAppNotification)
        .filter(
            InAppNotification.id == notification_id,
            InAppNotification.user_id == user.id,
        )
        .with_for_update()
        .first()
    )
    if notification is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notification not found.",
        )
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return InAppNotificationReadResponse(
        id=notification.id,
        read_at=notification.read_at,
    )
