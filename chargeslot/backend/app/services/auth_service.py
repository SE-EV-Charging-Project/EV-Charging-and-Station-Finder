from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.schemas.user import UserRegisterRequest
from app.utils.security import hash_password


class AuthService:
    @staticmethod
    def register_user(db: Session, request: UserRegisterRequest, ip_address: str | None = None) -> User:
        """
        Registers a new user (CS19-001 / REQ-F1-01):
        - Assigns Driver role by default
        - Enforces unique email and phone
        - Creates audit log entry (CS19-014)
        """
        # Check duplicate email (CS19-008)
        existing_email = db.query(User).filter(User.email == request.email.lower()).first()
        if existing_email:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this email already exists."
            )

        # Check duplicate phone (CS19-008)
        existing_phone = db.query(User).filter(User.phone == request.phone).first()
        if existing_phone:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An account with this phone number already exists."
            )

        new_user = User(
            name=request.name,
            email=request.email.lower(),
            phone=request.phone,
            hashed_password=hash_password(request.password),
            role=UserRole.DRIVER,
            is_verified=False,
            is_active=True,
            failed_login_attempts=0
        )
        db.add(new_user)
        db.flush()  # populate new_user.id

        # Audit log creation (CS19-014)
        audit = AuditLog(
            user_id=new_user.id,
            action="USER_REGISTERED",
            resource="users",
            details=f"User {new_user.email} registered with default role {new_user.role.value}",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()
        db.refresh(new_user)
        return new_user
