from fastapi import APIRouter, Depends, status
from app.api.deps import (
    get_current_user,
    require_roles,
    require_admin,
    require_operator,
    require_driver,
)
from app.models.user import User, UserRole
from app.schemas.user import RbacCheckResponse

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
