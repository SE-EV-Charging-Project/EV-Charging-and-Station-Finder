from datetime import datetime
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.operator_application import ApplicationStatus
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    AdminUserListResponse,
    UserResponse,
    AuditLogListResponse,
    OperatorApplicationResponse,
    OperatorApplicationListResponse,
    OperatorApplicationRejectRequest,
)
from app.services.admin_service import AdminService
from app.services.audit_service import AuditService
from app.services.operator_service import OperatorService

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


# ==============================================================================
# Audit Logs Endpoints (CS19-014 / REQ-F1-14)
# ==============================================================================

@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    status_code=status.HTTP_200_OK,
    summary="List and filter system audit logs",
    description="Allows administrators to query the immutable audit log with filters by actor, action, resource, or date range (CS19-014 / REQ-F1-14)."
)
def list_audit_logs(
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
# Operator Applications Endpoints (CS19-015 / REQ-F1-15)
# ==============================================================================

@router.get(
    "/operator-applications",
    response_model=OperatorApplicationListResponse,
    status_code=status.HTTP_200_OK,
    summary="List station operator onboarding applications",
    description="Allows administrators to review pending, approved, and rejected operator applications (CS19-015 / REQ-F1-15)."
)
def list_operator_applications(
    status_filter: ApplicationStatus | None = Query(None, alias="status", description="Filter by application status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OperatorApplicationListResponse:
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


@router.get(
    "/operator-applications/{application_id}",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Get operator application details",
    description="Retrieves full business and contact details for an operator onboarding application (CS19-015 / REQ-F1-15)."
)
def get_operator_application(
    application_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OperatorApplicationResponse:
    app = OperatorService.get_application_by_id(
        db=db,
        application_id=application_id,
        current_user=current_admin,
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
    "/operator-applications/{application_id}/approve",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve operator onboarding application",
    description="Approves a pending application, promotes the applicant to Station Operator, and logs the decision (CS19-015 / REQ-F1-15, REQ-F1-14)."
)
def approve_operator_application(
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
    "/operator-applications/{application_id}/reject",
    response_model=OperatorApplicationResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject operator onboarding application",
    description="Rejects a pending application with a recorded reason and writes to audit logs (CS19-015 / REQ-F1-15, REQ-F1-14)."
)
def reject_operator_application(
    application_id: int,
    request_data: OperatorApplicationRejectRequest,
    req: Request,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> OperatorApplicationResponse:
    client_ip = req.client.host if req.client else None
    app = OperatorService.reject_application(
        db=db,
        admin=current_admin,
        application_id=application_id,
        reason=request_data.reason,
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
