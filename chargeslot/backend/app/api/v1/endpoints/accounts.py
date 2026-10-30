from datetime import datetime
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
from app.models.operator_application import ApplicationStatus
from app.schemas.user import (
    RbacCheckResponse,
    AdminUserManagementPatchRequest,
    AdminUserListResponse,
    UserResponse,
    AuditLogListResponse,
    OperatorApplicationCreate,
    OperatorApplicationResponse,
    OperatorApplicationListResponse,
    OperatorApplicationRejectRequest,
)
from app.services.admin_service import AdminService
from app.services.audit_service import AuditService
from app.services.operator_service import OperatorService

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


# ==============================================================================
# Audit User Actions (CS19-014 / REQ-F1-14 / SW Architecture Page 5)
# ==============================================================================

@router.get(
    "/audit-user-actions",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="Query audit log entries",
    description="Proposed route GET /api/v1/accounts/audit-user-actions matching SW Architecture Page 5 (REQ-F1-14 / CS19-014)."
)
def get_audit_user_actions(
    user_id: int | None = Query(None, description="Filter by acting user ID"),
    action: str | None = Query(None, description="Filter by action name"),
    resource: str | None = Query(None, description="Filter by resource (e.g. users, operator_applications)"),
    start_date: datetime | None = Query(None, description="Filter from timestamp"),
    end_date: datetime | None = Query(None, description="Filter up to timestamp"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> AuditLogListResponse:
    skip = (page - 1) * page_size
    items, total = AuditService.list_logs(
        db=db,
        user_id=user_id,
        action=action,
        resource=resource,
        start_date=start_date,
        end_date=end_date,
        skip=skip,
        limit=page_size,
    )
    return AuditLogListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=items,
    )


# ==============================================================================
# Operator Onboarding (CS19-015 / REQ-F1-15 / SW Architecture Page 5)
# ==============================================================================

@router.post(
    "/operator-onboarding",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Apply for Station Operator status",
    description="Proposed route POST /api/v1/accounts/operator-onboarding allowing drivers to submit business details for operator onboarding (REQ-F1-15 / CS19-015)."
)
def apply_operator_onboarding(
    payload: OperatorApplicationCreate,
    req: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OperatorApplicationResponse:
    client_ip = req.client.host if req.client else None
    app = OperatorService.apply_for_operator(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )
    return OperatorApplicationResponse(
        id=app.id,
        user_id=app.user_id,
        applicant_name=current_user.name,
        applicant_email=current_user.email,
        business_name=app.business_name,
        contact_email=app.contact_email,
        contact_phone=app.contact_phone,
        business_address=app.business_address,
        tax_identifier=app.tax_identifier,
        status=app.status,
        rejection_reason=app.rejection_reason,
        reviewed_by_admin_id=app.reviewed_by_admin_id,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.get(
    "/operator-onboarding",
    status_code=status.HTTP_200_OK,
    summary="Get operator onboarding applications or current application status",
    description="Proposed route GET /api/v1/accounts/operator-onboarding matching SW Architecture Page 5 (REQ-F1-15 / CS19-015). For Admins, returns paginated applications list. For Drivers, returns their current application status."
)
def get_operator_onboarding(
    status_filter: ApplicationStatus | None = Query(None, alias="status", description="Filter by status (Admin only)"),
    page: int = Query(1, ge=1, description="Page number (Admin only)"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page (Admin only)"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.ADMIN:
        skip = (page - 1) * page_size
        items, total = OperatorService.list_applications(
            db=db,
            status_filter=status_filter,
            skip=skip,
            limit=page_size,
        )
        return OperatorApplicationListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )

    # For non-admin user (e.g. driver), return their active application
    my_app = OperatorService.get_my_application(db=db, user=current_user)
    if not my_app:
        return {"status": "none", "message": "No operator application found for this account."}

    return OperatorApplicationResponse(
        id=my_app.id,
        user_id=my_app.user_id,
        applicant_name=current_user.name,
        applicant_email=current_user.email,
        business_name=my_app.business_name,
        contact_email=my_app.contact_email,
        contact_phone=my_app.contact_phone,
        business_address=my_app.business_address,
        tax_identifier=my_app.tax_identifier,
        status=my_app.status,
        rejection_reason=my_app.rejection_reason,
        reviewed_by_admin_id=my_app.reviewed_by_admin_id,
        reviewed_at=my_app.reviewed_at,
        created_at=my_app.created_at,
        updated_at=my_app.updated_at,
    )


@router.get(
    "/operator-onboarding/{application_id}",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operator onboarding application details",
    description="Retrieves application details. Drivers can only view their own; Admins can view any (REQ-F1-15 / CS19-015)."
)
def get_operator_onboarding_details(
    application_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> OperatorApplicationResponse:
    app = OperatorService.get_application_by_id(
        db=db,
        application_id=application_id,
        current_user=current_user,
    )
    return OperatorApplicationResponse(
        id=app.id,
        user_id=app.user_id,
        applicant_name=app.user.name if app.user else None,
        applicant_email=app.user.email if app.user else None,
        business_name=app.business_name,
        contact_email=app.contact_email,
        contact_phone=app.contact_phone,
        business_address=app.business_address,
        tax_identifier=app.tax_identifier,
        status=app.status,
        rejection_reason=app.rejection_reason,
        reviewed_by_admin_id=app.reviewed_by_admin_id,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.post(
    "/operator-onboarding/{application_id}/approve",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin approve operator onboarding application",
    description="Approves application, promotes user to Station Operator, and logs to audit (REQ-F1-15, REQ-F1-14 / CS19-015)."
)
def approve_operator_onboarding(
    application_id: int,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OperatorApplicationResponse:
    client_ip = req.client.host if req.client else None
    app = OperatorService.approve_application(
        db=db,
        admin=current_admin,
        application_id=application_id,
        ip_address=client_ip,
    )
    return OperatorApplicationResponse(
        id=app.id,
        user_id=app.user_id,
        applicant_name=app.user.name if app.user else None,
        applicant_email=app.user.email if app.user else None,
        business_name=app.business_name,
        contact_email=app.contact_email,
        contact_phone=app.contact_phone,
        business_address=app.business_address,
        tax_identifier=app.tax_identifier,
        status=app.status,
        rejection_reason=app.rejection_reason,
        reviewed_by_admin_id=app.reviewed_by_admin_id,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


@router.post(
    "/operator-onboarding/{application_id}/reject",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Admin reject operator onboarding application",
    description="Rejects application with a required reason and logs to audit (REQ-F1-15, REQ-F1-14 / CS19-015)."
)
def reject_operator_onboarding(
    application_id: int,
    payload: OperatorApplicationRejectRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OperatorApplicationResponse:
    client_ip = req.client.host if req.client else None
    app = OperatorService.reject_application(
        db=db,
        admin=current_admin,
        application_id=application_id,
        reason=payload.reason,
        ip_address=client_ip,
    )
    return OperatorApplicationResponse(
        id=app.id,
        user_id=app.user_id,
        applicant_name=app.user.name if app.user else None,
        applicant_email=app.user.email if app.user else None,
        business_name=app.business_name,
        contact_email=app.contact_email,
        contact_phone=app.contact_phone,
        business_address=app.business_address,
        tax_identifier=app.tax_identifier,
        status=app.status,
        rejection_reason=app.rejection_reason,
        reviewed_by_admin_id=app.reviewed_by_admin_id,
        reviewed_at=app.reviewed_at,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )

