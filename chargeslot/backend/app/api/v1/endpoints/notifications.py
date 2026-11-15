from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notification import (
    InAppNotificationListResponse,
    InAppNotificationReadResponse,
)
from app.services.notification_service import (
    list_in_app_notifications,
    mark_in_app_notification_read,
)

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get(
    "",
    response_model=InAppNotificationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List the current user's in-app notifications",
)
def get_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InAppNotificationListResponse:
    return list_in_app_notifications(
        db,
        user=current_user,
        unread_only=unread_only,
        limit=limit,
    )


@router.patch(
    "/{notification_id}/read",
    response_model=InAppNotificationReadResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark one of the current user's notifications as read",
)
def patch_notification_read(
    notification_id: int = Path(..., gt=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> InAppNotificationReadResponse:
    return mark_in_app_notification_read(
        db,
        user=current_user,
        notification_id=notification_id,
    )
