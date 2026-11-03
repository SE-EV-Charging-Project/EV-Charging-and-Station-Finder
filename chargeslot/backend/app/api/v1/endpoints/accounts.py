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
from app.core.permissions import enforce_operator_scope
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
    OperatorDataScopeResponse,
    VerifyOperatorAccessRequest,
    VerifyOperatorAccessResponse,
    ProfilePreferencesResponse,
    ProfilePreferencesUpdateRequest,
    ProfileValidationCheckRequest,
    ProfileValidationCheckResponse,
    ProfileValidationRulesResponse,
    DriverDataScopeResponse,
)
from app.schemas.vehicle import (
    VehicleCreateRequest,
    VehicleUpdateRequest,
    VehicleResponse,
    VehicleListResponse,
    VehicleDeleteResponse,
    VehicleValidationRulesResponse,
    VehicleValidationCheckRequest,
    VehicleValidationCheckResponse,
    VehicleSummaryCardResponse,
    VehicleSummaryCardListResponse,
    SetDefaultVehicleRequest,
    VehicleLimitAndDefaultResponse,
    SetDefaultVehicleResponse,
    EVPresetModelResponse,
    EVPresetListResponse,
    ApplyPresetRequest,
    ApplyPresetResponse,
    ProtectBookedVehicleRequest,
    ProtectBookedVehicleResponse,
)
from app.services.admin_service import AdminService
from app.services.audit_service import AuditService
from app.services.operator_service import OperatorService
from app.services.profile_service import ProfileService
from app.services.vehicle_service import VehicleService

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


# ==============================================================================
# Operator Data Scope (CS19-012 / REQ-F1-12 / SW Architecture Page 5)
# ==============================================================================

@router.get(
    "/operator-data-scope",
    response_model=OperatorDataScopeResponse,
    status_code=status.HTTP_200_OK,
    summary="Operator data scope profile",
    description="Proposed route GET /api/v1/accounts/operator-data-scope matching SW Architecture Page 5 (REQ-F1-12 / CS19-012). Restricted to Station Operators and Admins."
)
def get_operator_data_scope(
    current_user: User = Depends(require_operator),
) -> OperatorDataScopeResponse:
    is_admin = current_user.role == UserRole.ADMIN
    return OperatorDataScopeResponse(
        operator_id=current_user.id,
        operator_name=current_user.name,
        operator_email=current_user.email,
        operator_organization=current_user.operator_organization,
        role=current_user.role.value if isinstance(current_user.role, UserRole) else str(current_user.role),
        scope_type="GLOBAL" if is_admin else "OWNED_RESOURCES_ONLY",
        allowed_resources=["stations", "chargers", "tariffs", "reports"],
        message="Global operator management scope granted." if is_admin else "Scoped strictly to owned stations, chargers, tariffs, and reports (REQ-F1-12)."
    )


@router.post(
    "/operator-data-scope/verify-access",
    response_model=VerifyOperatorAccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify operator access to a resource",
    description="Checks whether the authenticated operator is authorized to access a given station, charger, tariff, or report (REQ-F1-12 / CS19-012)."
)
def verify_operator_access(
    payload: VerifyOperatorAccessRequest,
    current_user: User = Depends(require_operator),
) -> VerifyOperatorAccessResponse:
    enforce_operator_scope(current_user=current_user, resource_operator_id=payload.resource_operator_id)
    return VerifyOperatorAccessResponse(
        has_access=True,
        operator_id=current_user.id,
        resource_operator_id=payload.resource_operator_id,
        resource_type=payload.resource_type,
        message="Access authorized: Operator owns this resource (or holds Administrator global scope)."
    )


# ==============================================================================
# Driver Profile & Preferences (CS19-016 / CS19-017 / REQ-F1-16 / REQ-F1-17 / SW Architecture Page 5)
# ==============================================================================

@router.get(
    "/profile",
    response_model=ProfilePreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get user profile and preferences",
    description="Fetch profile information and charging preferences for the currently authenticated user (CS19-016 / REQ-F1-16)."
)
def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfilePreferencesResponse:
    return ProfileService.get_profile(db=db, user=current_user)


@router.get(
    "/edit-profile-and-preferences",
    response_model=ProfilePreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get profile and preferences (architecture alias)",
    description="Matching SW Architecture Page 5: Retrieve driver profile and preferences before editing."
)
def get_profile_and_preferences(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfilePreferencesResponse:
    return ProfileService.get_profile(db=db, user=current_user)


@router.patch(
    "/edit-profile-and-preferences",
    response_model=ProfilePreferencesResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit driver profile and preferences",
    description="Matching SW Architecture Page 5: Update driver profile information and charging preferences (CS19-016 / REQ-F1-16)."
)
def edit_profile_and_preferences(
    payload: ProfilePreferencesUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfilePreferencesResponse:
    client_ip = request.client.host if request.client else None
    return ProfileService.edit_profile(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.get(
    "/profile-validation",
    response_model=ProfileValidationRulesResponse,
    status_code=status.HTTP_200_OK,
    summary="Get profile validation rules",
    description="Matching SW Architecture Page 5: Validate profile inputs and return validation rules metadata (CS19-017 / REQ-F1-17)."
)
def get_profile_validation_rules() -> ProfileValidationRulesResponse:
    return ProfileService.get_validation_rules()


@router.post(
    "/profile-validation",
    response_model=ProfileValidationCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Inline profile validation check",
    description="Validates draft profile inputs and returns inline field-level validation feedback (CS19-017 / REQ-F1-17)."
)
def check_profile_validation(
    payload: ProfileValidationCheckRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProfileValidationCheckResponse:
    return ProfileService.validate_profile_inputs(
        db=db,
        payload=payload,
        current_user_id=current_user.id,
    )


# ==============================================================================
# Vehicle Management (CS19-018 / REQ-F1-18 / REQ-F1-21 / SW Architecture Page 5)
# ==============================================================================

@router.post(
    "/vehicle-crud",
    response_model=VehicleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add vehicle (architecture route)",
    description="Matching SW Architecture Page 5: Add a new electric vehicle for the authenticated driver (REQ-F1-18 / CS19-018)."
)
def add_vehicle_crud(
    payload: VehicleCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.add_vehicle(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.get(
    "/vehicle-crud",
    response_model=VehicleListResponse,
    status_code=status.HTTP_200_OK,
    summary="List driver vehicles (architecture route)",
    description="Matching SW Architecture Page 5: List all vehicles registered to the authenticated driver."
)
def list_vehicles_crud(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleListResponse:
    return VehicleService.list_vehicles(db=db, user=current_user)


@router.patch(
    "/vehicle-crud/{vehicle_id}",
    response_model=VehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit vehicle (architecture route)",
    description="Matching SW Architecture Page 5: Edit vehicle specifications (REQ-F1-21 / CS19-021)."
)
def update_vehicle_crud(
    vehicle_id: int,
    payload: VehicleUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.update_vehicle(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.delete(
    "/vehicle-crud",
    response_model=VehicleDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vehicle via query parameter (architecture route)",
    description="Matching SW Architecture Page 5: Remove a vehicle from driver's profile (REQ-F1-21 / CS19-021)."
)
def remove_vehicle_crud_query(
    vehicle_id: int = Query(..., description="ID of the vehicle to remove"),
    request: Request = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleDeleteResponse:
    client_ip = request.client.host if request and request.client else None
    return VehicleService.remove_vehicle(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
        ip_address=client_ip,
    )


@router.delete(
    "/vehicle-crud/{vehicle_id}",
    response_model=VehicleDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove vehicle (architecture route)",
    description="Matching SW Architecture Page 5: Remove a vehicle from driver's profile (REQ-F1-21 / CS19-021)."
)
def remove_vehicle_crud(
    vehicle_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleDeleteResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.remove_vehicle(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
        ip_address=client_ip,
    )


@router.get(
    "/vehicle-limit-and-default",
    response_model=VehicleLimitAndDefaultResponse,
    status_code=status.HTTP_200_OK,
    summary="Vehicle limit and default (architecture route)",
    description="Matching SW Architecture Page 5: Retrieve 5-vehicle limit status and single default vehicle (REQ-F1-22 / CS19-022)."
)
def get_vehicle_limit_and_default_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleLimitAndDefaultResponse:
    return VehicleService.get_limit_and_default(db=db, user=current_user)


@router.patch(
    "/vehicle-limit-and-default",
    response_model=SetDefaultVehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Set default vehicle (architecture route)",
    description="Matching SW Architecture Page 5: Set primary default vehicle, guaranteeing exactly one default (REQ-F1-22 / CS19-022)."
)
def set_default_vehicle_account(
    payload: SetDefaultVehicleRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetDefaultVehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.set_default_vehicle(
        db=db,
        vehicle_id=payload.vehicle_id,
        user=current_user,
        ip_address=client_ip,
    )


@router.post(
    "/vehicle-limit-and-default",
    response_model=SetDefaultVehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Set default vehicle alias (architecture route)",
    description="Matching SW Architecture Page 5 POST alias: Set primary default vehicle (REQ-F1-22 / CS19-022)."
)
def set_default_vehicle_account_post(
    payload: SetDefaultVehicleRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SetDefaultVehicleResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.set_default_vehicle(
        db=db,
        vehicle_id=payload.vehicle_id,
        user=current_user,
        ip_address=client_ip,
    )




@router.get(
    "/preset-ev-models",
    response_model=EVPresetListResponse,
    status_code=status.HTTP_200_OK,
    summary="List preset EV models (architecture route)",
    description="Matching SW Architecture Page 5: List common EV models for pre-filling specification fields (REQ-F1-23 / CS19-023)."
)
def list_preset_ev_models_account(
    make: str | None = None,
    connector_type: str | None = None,
) -> EVPresetListResponse:
    return VehicleService.list_presets(make=make, connector_type=connector_type)


@router.post(
    "/preset-ev-models",
    response_model=ApplyPresetResponse,
    status_code=status.HTTP_200_OK,
    summary="Apply preset EV models (architecture route)",
    description="Matching SW Architecture Page 5: Select preset EV model to pre-fill specs and optionally save vehicle (REQ-F1-23 / CS19-023)."
)
def apply_preset_ev_model_account(
    payload: ApplyPresetRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApplyPresetResponse:
    client_ip = request.client.host if request.client else None
    return VehicleService.apply_preset(
        db=db,
        user=current_user,
        data=payload,
        ip_address=client_ip,
    )


@router.get(
    "/vehicle-value-validation",
    response_model=VehicleValidationRulesResponse,
    status_code=status.HTTP_200_OK,
    summary="Vehicle value validation rules (architecture route)",
    description="Matching SW Architecture Page 5: Retrieve validation rules for vehicle values (REQ-F1-19 / REQ-F1-24)."
)
def get_vehicle_value_validation_rules() -> VehicleValidationRulesResponse:
    return VehicleService.get_validation_rules()


@router.post(
    "/vehicle-value-validation",
    response_model=VehicleValidationCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Validate vehicle values inline (architecture route)",
    description="Matching SW Architecture Page 5: Perform inline validation on vehicle input values (REQ-F1-19 / REQ-F1-24)."
)
def check_vehicle_value_validation(
    payload: VehicleValidationCheckRequest,
    current_user: User = Depends(get_current_user),
) -> VehicleValidationCheckResponse:
    return VehicleService.validate_vehicle_inputs(payload=payload)


@router.get(
    "/vehicle-summary-card",
    response_model=VehicleSummaryCardListResponse,
    status_code=status.HTTP_200_OK,
    summary="List driver vehicle summary cards",
    description="Matching SW Architecture: List summary cards with compatibility badges for all vehicles (REQ-F1-20 / CS19-020)."
)
def list_vehicle_summary_cards_account(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleSummaryCardListResponse:
    return VehicleService.list_vehicle_summaries(db=db, user=current_user)


@router.get(
    "/vehicle-summary-card/{vehicle_id}",
    response_model=VehicleSummaryCardResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle summary card",
    description="Matching SW Architecture: Fetch vehicle summary card with compatibility icons by vehicle ID (REQ-F1-20 / CS19-020)."
)
def get_vehicle_summary_card_account(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> VehicleSummaryCardResponse:
    return VehicleService.get_vehicle_summary(db=db, vehicle_id=vehicle_id, user=current_user)


# ==============================================================================
# Protect Booked Vehicle Endpoints (CS19-025 / REQ-F1-25)
# ==============================================================================

@router.post(
    "/protect-booked-vehicle",
    response_model=ProtectBookedVehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Protect booked vehicle (architecture route)",
    description="Matching SW Architecture Page 5: Check whether a vehicle is linked to active/upcoming bookings before deletion (REQ-F1-25 / CS19-025)."
)
def protect_booked_vehicle_account(
    payload: ProtectBookedVehicleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProtectBookedVehicleResponse:
    return VehicleService.get_booking_protection_status(
        db=db,
        vehicle_id=payload.vehicle_id,
        user=current_user,
    )


@router.get(
    "/protect-booked-vehicle/{vehicle_id}",
    response_model=ProtectBookedVehicleResponse,
    status_code=status.HTTP_200_OK,
    summary="Get vehicle booking protection status (architecture route)",
    description="Matching SW Architecture Page 5 GET alias: Inspect whether a vehicle is linked to active/upcoming bookings (REQ-F1-25 / CS19-025)."
)
def get_protect_booked_vehicle_account(
    vehicle_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ProtectBookedVehicleResponse:
    return VehicleService.get_booking_protection_status(
        db=db,
        vehicle_id=vehicle_id,
        user=current_user,
    )


# ==============================================================================
# Driver Sees Own Data Only Endpoints (CS19-026 / REQ-F1-26)
# ==============================================================================

@router.get(
    "/driver-sees-own-data-only",
    response_model=DriverDataScopeResponse,
    status_code=status.HTTP_200_OK,
    summary="Driver sees own data only (architecture route)",
    description="Matching SW Architecture Page 5: Verify driver tenancy isolation; access to other drivers' data is denied (REQ-F1-26 / CS19-026)."
)
def driver_sees_own_data_only(
    target_user_id: int | None = Query(None, description="Optional target user ID to verify tenancy barrier"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DriverDataScopeResponse:
    return VehicleService.get_driver_data_scope(
        db=db,
        user=current_user,
        target_user_id=target_user_id,
    )





