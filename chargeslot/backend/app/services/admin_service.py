from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.schemas.user import (
    AdminCreateUserRequest,
    AdminUpdateUserRequest,
    AdminUserManagementPatchRequest,
)
from app.utils.security import hash_password


class AdminService:
    """
    Service handling Administrator User Management operations (CS19-013 / REQ-F1-13, REQ-F1-14).
    Enforces that only administrators can manage, search, activate/deactivate accounts,
    and change roles with required audit logs.
    """

    @staticmethod
    def list_users(
        db: Session,
        query: str | None = None,
        role: UserRole | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[User], int]:
        q = db.query(User)

        if query:
            clean_q = f"%{query.strip()}%"
            q = q.filter(
                or_(
                    User.name.ilike(clean_q),
                    User.email.ilike(clean_q),
                    User.phone.like(clean_q),
                )
            )

        if role is not None:
            q = q.filter(User.role == role)

        if is_active is not None:
            q = q.filter(User.is_active == is_active)

        total = q.count()
        items = q.order_by(User.id.asc()).offset(skip).limit(limit).all()
        return items, total

    @staticmethod
    def get_user_by_id(db: Session, user_id: int) -> User:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"User with ID {user_id} not found."
            )
        return user

    @staticmethod
    def create_user(
        db: Session,
        admin: User,
        request: AdminCreateUserRequest,
        ip_address: str | None = None,
    ) -> User:
        # Check duplicate email
        email_clean = request.email.strip().lower()
        if db.query(User).filter(User.email == email_clean).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email address already exists."
            )

        # Check duplicate phone
        phone_clean = request.phone.strip()
        if db.query(User).filter(User.phone == phone_clean).first():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this phone number already exists."
            )

        hashed = hash_password(request.password)
        new_user = User(
            name=request.name.strip(),
            email=email_clean,
            phone=phone_clean,
            hashed_password=hashed,
            role=request.role,
            is_verified=request.is_verified,
            is_active=True,
            operator_organization=request.operator_organization.strip() if request.operator_organization else None,
        )
        db.add(new_user)
        db.flush()

        # Audit log creation (REQ-F1-14)
        audit = AuditLog(
            user_id=admin.id,
            action="ADMIN_CREATE_USER",
            resource="users",
            details=f"Admin {admin.email} created user {new_user.email} with role {new_user.role.value}",
            ip_address=ip_address,
        )
        db.add(audit)
        db.commit()
        db.refresh(new_user)
        return new_user

    @staticmethod
    def update_user(
        db: Session,
        admin: User,
        user_id: int,
        request: AdminUpdateUserRequest,
        ip_address: str | None = None,
    ) -> User:
        user = AdminService.get_user_by_id(db, user_id)

        # Safety rule: admin cannot deactivate or demote themselves
        if user.id == admin.id:
            if request.is_active is False:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Administrators cannot deactivate their own account."
                )
            if request.role is not None and request.role != UserRole.ADMIN:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Administrators cannot demote their own admin role."
                )

        changes: list[str] = []

        if request.name is not None:
            user.name = request.name.strip()
            changes.append("name")

        if request.is_verified is not None:
            user.is_verified = request.is_verified
            changes.append("is_verified")

        if request.operator_organization is not None:
            user.operator_organization = request.operator_organization.strip()
            changes.append("operator_organization")

        # Audit role change (REQ-F1-14)
        if request.role is not None and request.role != user.role:
            old_role = user.role
            user.role = request.role
            audit_role = AuditLog(
                user_id=admin.id,
                action="ROLE_CHANGED",
                resource="users",
                details=f"Admin {admin.email} changed role of user {user.email} (id={user.id}) from {old_role.value} to {user.role.value}",
                ip_address=ip_address,
            )
            db.add(audit_role)

        # Audit activation / deactivation (REQ-F1-14)
        if request.is_active is not None and request.is_active != user.is_active:
            user.is_active = request.is_active
            action_name = "ACCOUNT_REACTIVATED" if user.is_active else "ACCOUNT_DEACTIVATED"
            audit_active = AuditLog(
                user_id=admin.id,
                action=action_name,
                resource="users",
                details=f"Admin {admin.email} set active status of user {user.email} (id={user.id}) to {user.is_active}",
                ip_address=ip_address,
            )
            db.add(audit_active)

        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def patch_user_management(
        db: Session,
        admin: User,
        request: AdminUserManagementPatchRequest,
        ip_address: str | None = None,
    ) -> User:
        """
        Handler matching proposed route:
        PATCH /api/v1/accounts/admin-user-management (REQ-F1-13 / SW Architecture Page 5)
        """
        update_req = AdminUpdateUserRequest(
            role=request.role,
            is_active=request.is_active,
            is_verified=request.is_verified,
        )
        return AdminService.update_user(
            db=db,
            admin=admin,
            user_id=request.user_id,
            request=update_req,
            ip_address=ip_address,
        )
