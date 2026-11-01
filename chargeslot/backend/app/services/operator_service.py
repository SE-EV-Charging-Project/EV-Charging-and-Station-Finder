from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.operator_application import OperatorApplication, ApplicationStatus
from app.models.user import User, UserRole
from app.schemas.user import OperatorApplicationCreate
from app.services.audit_service import AuditService


class OperatorService:
    """
    Service handling Station Operator Onboarding (CS19-015 / REQ-F1-15, REQ-F1-14).
    Enforces driver application submissions, administrative review (approval/rejection),
    role promotion, and audit logging.
    """

    @staticmethod
    def apply_for_operator(
        db: Session,
        user: User,
        data: OperatorApplicationCreate,
        ip_address: str | None = None,
    ) -> OperatorApplication:
        # User cannot apply if already an operator or admin
        if user.role in [UserRole.OPERATOR, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User already holds the role of '{user.role.value}' and cannot apply for operator onboarding.",
            )

        # Check for existing pending application
        pending = (
            db.query(OperatorApplication)
            .filter(
                OperatorApplication.user_id == user.id,
                OperatorApplication.status == ApplicationStatus.PENDING,
            )
            .first()
        )
        if pending:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You already have an operator onboarding application under review.",
            )

        application = OperatorApplication(
            user_id=user.id,
            business_name=data.business_name.strip(),
            contact_email=data.contact_email.strip().lower(),
            contact_phone=data.contact_phone.strip(),
            business_address=data.business_address.strip() if data.business_address else None,
            tax_identifier=data.tax_identifier.strip() if data.tax_identifier else None,
            status=ApplicationStatus.PENDING,
        )
        db.add(application)
        db.flush()

        # Audit log creation (REQ-F1-14)
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="OPERATOR_APPLICATION_SUBMITTED",
            resource="operator_applications",
            details=f"User {user.email} (id={user.id}) submitted operator application #{application.id} for '{application.business_name}'",
            ip_address=ip_address,
            commit=False,
        )

        db.commit()
        db.refresh(application)
        return application

    @staticmethod
    def get_my_application(db: Session, user: User) -> OperatorApplication | None:
        """Returns the user's latest operator application."""
        return (
            db.query(OperatorApplication)
            .filter(OperatorApplication.user_id == user.id)
            .order_by(desc(OperatorApplication.created_at))
            .first()
        )

    @staticmethod
    def get_application_by_id(
        db: Session,
        application_id: int,
        current_user: User,
    ) -> OperatorApplication:
        app = (
            db.query(OperatorApplication)
            .filter(OperatorApplication.id == application_id)
            .first()
        )
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operator application with ID {application_id} not found.",
            )

        # Role scoping: regular users can only see their own application
        if current_user.role != UserRole.ADMIN and app.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to foreign operator application.",
            )

        return app

    @staticmethod
    def list_applications(
        db: Session,
        status_filter: ApplicationStatus | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        q = db.query(OperatorApplication)
        if status_filter is not None:
            q = q.filter(OperatorApplication.status == status_filter)

        total = q.count()
        apps = (
            q.order_by(desc(OperatorApplication.created_at))
            .offset(skip)
            .limit(limit)
            .all()
        )

        results: list[dict] = []
        for a in apps:
            results.append({
                "id": a.id,
                "user_id": a.user_id,
                "applicant_name": a.user.name if a.user else None,
                "applicant_email": a.user.email if a.user else None,
                "business_name": a.business_name,
                "contact_email": a.contact_email,
                "contact_phone": a.contact_phone,
                "business_address": a.business_address,
                "tax_identifier": a.tax_identifier,
                "status": a.status,
                "rejection_reason": a.rejection_reason,
                "reviewed_by_admin_id": a.reviewed_by_admin_id,
                "reviewed_at": a.reviewed_at,
                "created_at": a.created_at,
                "updated_at": a.updated_at,
            })
        return results, total

    @staticmethod
    def approve_application(
        db: Session,
        admin: User,
        application_id: int,
        ip_address: str | None = None,
    ) -> OperatorApplication:
        app = (
            db.query(OperatorApplication)
            .filter(OperatorApplication.id == application_id)
            .first()
        )
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operator application with ID {application_id} not found.",
            )

        if app.status != ApplicationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve application with status '{app.status.value}'. Only PENDING applications can be approved.",
            )

        applicant = db.query(User).filter(User.id == app.user_id).first()
        if not applicant:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Applicant user account no longer exists.",
            )

        now = datetime.now(timezone.utc)
        app.status = ApplicationStatus.APPROVED
        app.reviewed_by_admin_id = admin.id
        app.reviewed_at = now

        # Role promotion and organization assignment (REQ-F1-15)
        old_role = applicant.role
        applicant.role = UserRole.OPERATOR
        applicant.operator_organization = app.business_name

        # Audit logs for approval and role promotion (REQ-F1-14)
        AuditService.log_action(
            db=db,
            user_id=admin.id,
            action="OPERATOR_APPLICATION_APPROVED",
            resource="operator_applications",
            details=f"Admin {admin.email} approved operator application #{app.id} for user {applicant.email}. Role promoted from {old_role.value} to operator.",
            ip_address=ip_address,
            commit=False,
        )

        AuditService.log_action(
            db=db,
            user_id=admin.id,
            action="ROLE_CHANGED",
            resource="users",
            details=f"Admin {admin.email} promoted user {applicant.email} (id={applicant.id}) to {applicant.role.value} via operator onboarding #{app.id}",
            ip_address=ip_address,
            commit=False,
        )

        db.commit()
        db.refresh(app)
        return app

    @staticmethod
    def reject_application(
        db: Session,
        admin: User,
        application_id: int,
        reason: str,
        ip_address: str | None = None,
    ) -> OperatorApplication:
        app = (
            db.query(OperatorApplication)
            .filter(OperatorApplication.id == application_id)
            .first()
        )
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Operator application with ID {application_id} not found.",
            )

        clean_reason = reason.strip() if reason else ""
        if len(clean_reason) < 5:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rejection reason must be at least 5 characters long.",
            )

        if app.status != ApplicationStatus.PENDING:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot reject application with status '{app.status.value}'. Only PENDING applications can be rejected.",
            )

        applicant = db.query(User).filter(User.id == app.user_id).first()
        applicant_email = applicant.email if applicant else f"user#{app.user_id}"

        now = datetime.now(timezone.utc)
        app.status = ApplicationStatus.REJECTED
        app.rejection_reason = clean_reason
        app.reviewed_by_admin_id = admin.id
        app.reviewed_at = now

        # Audit log for rejection (REQ-F1-14)
        AuditService.log_action(
            db=db,
            user_id=admin.id,
            action="OPERATOR_APPLICATION_REJECTED",
            resource="operator_applications",
            details=f"Admin {admin.email} rejected operator application #{app.id} for {applicant_email}. Reason: {clean_reason}",
            ip_address=ip_address,
            commit=False,
        )

        db.commit()
        db.refresh(app)
        return app
