from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    require_roles,
    require_admin,
    require_operator,
    require_driver,
)
from app.db.session import get_db
from app.models.user import User, UserRole
from app.schemas.user import (
    RbacCheckResponse,
    AdminUserManagementPatchRequest,
    AdminUserListResponse,
    UserResponse,
)
from app.services.admin_service import AdminService

router = APIRouter(prefix="/accounts", tags=["Accounts & RBAC"])


@router.get(
    "/server-side-rbac",
    response_model=RbacCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Server-side RBAC verification endpoint",
    description="Validates that the caller is authenticated and enforces server-side role-based access control (CS19-011 / REQ-F1-11)."
)
def verify_server_side_rbac(
    current_user: User = Depends(get_current_user)
) -> RbacCheckResponse:
    return RbacCheckResponse(
        status="authorized",
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        message="Authenticated and authorized under server-side RBAC."
    )


@router.get(
    "/server-side-rbac/admin",
    response_model=RbacCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin-only RBAC endpoint",
    description="Restricted to Administrator role only (CS19-011 / REQ-F1-11)."
)
def admin_rbac_check(
    current_user: User = Depends(require_admin)
) -> RbacCheckResponse:
    return RbacCheckResponse(
        status="authorized",
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        message="Administrator access granted under server-side RBAC."
    )


@router.get(
    "/server-side-rbac/operator",
    response_model=RbacCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Operator-only RBAC endpoint",
    description="Restricted to Station Operator or Administrator role (CS19-011 / REQ-F1-11)."
)
def operator_rbac_check(
    current_user: User = Depends(require_operator)
) -> RbacCheckResponse:
    return RbacCheckResponse(
        status="authorized",
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        message="Station Operator access granted under server-side RBAC."
    )


@router.get(
    "/server-side-rbac/driver",
    response_model=RbacCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Driver RBAC endpoint",
    description="Restricted to Driver or Administrator role (CS19-011 / REQ-F1-11)."
)
def driver_rbac_check(
    current_user: User = Depends(require_driver)
) -> RbacCheckResponse:
    return RbacCheckResponse(
        status="authorized",
        user_id=current_user.id,
        email=current_user.email,
        role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        message="Driver access granted under server-side RBAC."
    )


@router.patch(
    "/admin-user-management",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin user management (activate/deactivate, role change)",
    description="Allows an Administrator to activate/deactivate an account or change user role per SW Architecture Page 5 (CS19-013 / REQ-F1-13, REQ-F1-14)."
)
def patch_admin_user_management(
    request_data: AdminUserManagementPatchRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> User:
    client_ip = req.client.host if req.client else None
    return AdminService.patch_user_management(
        db=db,
        admin=current_admin,
        request=request_data,
        ip_address=client_ip,
    )


@router.get(
    "/admin-user-management",
    response_model=AdminUserListResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin user list and search",
    description="Allows an Administrator to search and list user accounts per SW Architecture Page 5 (CS19-013 / REQ-F1-13)."
)
def get_admin_user_management_list(
    q: str | None = Query(None, description="Search term for name, email, or phone"),
    role: UserRole | None = Query(None, description="Filter by user role"),
    is_active: bool | None = Query(None, description="Filter by active status"),
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
