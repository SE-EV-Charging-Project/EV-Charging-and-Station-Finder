from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    AdminUserListResponse,
    UserResponse,
)
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin User Management"])


@router.get(
    "/users",
    response_model=AdminUserListResponse,
    status_code=status.HTTP_200_OK,
    summary="List and search user accounts",
    description="Allows administrators to search, filter by role/status, and paginate through all registered user accounts (CS19-013 / REQ-F1-13)."
)
def list_users(
    q: str | None = Query(None, description="Search term for name, email, or phone"),
    role: UserRole | None = Query(None, description="Filter by user role"),
    is_active: bool | None = Query(None, description="Filter by account active status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AdminUserListResponse:
    skip = (page - 1) * page_size
    items, total = AdminService.list_users(
        db=db,
        query=q,
        role=role,
        is_active=is_active,
        skip=skip,
        limit=page_size,
    )
    return AdminUserListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


@router.post(
    "/users",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user account as admin",
    description="Allows administrators to provision new accounts with any role and initial status (CS19-013 / REQ-F1-13)."
)
def create_user(
    request_data: AdminCreateUserRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    client_ip = req.client.host if req.client else None
    return AdminService.create_user(
        db=db,
        admin=current_admin,
        request=request_data,
        ip_address=client_ip,
    )


@router.get(
    "/users/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user account details",
    description="Retrieves full profile details for a given user ID (CS19-013 / REQ-F1-13)."
)
def get_user_details(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    return AdminService.get_user_by_id(db=db, user_id=user_id)


@router.patch(
    "/users/{user_id}",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Update user account, status, or role",
    description="Allows an administrator to modify user status, activate/deactivate, or change user role with audit logging (CS19-013 / REQ-F1-13, REQ-F1-14)."
)
def update_user(
    user_id: int,
    request_data: AdminUpdateUserRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    client_ip = req.client.host if req.client else None
    return AdminService.update_user(
        db=db,
        admin=current_admin,
        user_id=user_id,
        request=request_data,
        ip_address=client_ip,
    )


@router.post(
    "/users/{user_id}/deactivate",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Deactivate a user account",
    description="Deactivates a user account, preventing future logins or protected access (CS19-013 / REQ-F1-13, REQ-F1-14)."
)
def deactivate_user(
    user_id: int,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    client_ip = req.client.host if req.client else None
    return AdminService.update_user(
        db=db,
        admin=current_admin,
        user_id=user_id,
        request=AdminUpdateUserRequest(is_active=False),
        ip_address=client_ip,
    )


@router.post(
    "/users/{user_id}/reactivate",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate a user account",
    description="Reactivates a deactivated user account (CS19-013 / REQ-F1-13, REQ-F1-14)."
)
def reactivate_user(
    user_id: int,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    client_ip = req.client.host if req.client else None
    return AdminService.update_user(
        db=db,
        admin=current_admin,
        user_id=user_id,
        request=AdminUpdateUserRequest(is_active=True),
        ip_address=client_ip,
    )
