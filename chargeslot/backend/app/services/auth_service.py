from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.schemas.user import UserRegisterRequest, UserLoginRequest, TokenResponse
from app.utils.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)


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
        db.flush()

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

    @staticmethod
    def login_user(db: Session, request: UserLoginRequest, ip_address: str | None = None) -> TokenResponse:
        """
        Authenticates user and issues JWT tokens (CS19-004, CS19-005, CS19-009).
        - Accepts email or registered phone number
        - Generic error on invalid credentials (CS19-009)
        - Locks account for 15 minutes after 5 failed attempts (CS19-005)
        """
        ident = request.identifier.strip().lower()
        # Find user by email or phone
        user = db.query(User).filter(
            or_(User.email == ident, User.phone == request.identifier.strip())
        ).first()

        now = datetime.now(timezone.utc)

        # Generic error message to prevent enumeration (CS19-009)
        generic_err = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/phone or password."
        )

        if not user:
            raise generic_err

        # Check if user account is locked (CS19-005)
        if user.locked_until:
            # Ensure locked_until has timezone info for comparison
            locked_until_utc = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
            if locked_until_utc > now:
                remaining_sec = (locked_until_utc - now).total_seconds()
                remaining_min = int(remaining_sec // 60) + 1
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Account is temporarily locked. Try again after {remaining_min} minute(s)."
                )
            else:
                # Lockout period has elapsed, reset
                user.locked_until = None
                user.failed_login_attempts = 0

        # Verify password
        if not verify_password(request.password, user.hashed_password):
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.LOGIN_MAX_FAILED_ATTEMPTS:
                user.locked_until = now + timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)
                audit = AuditLog(
                    user_id=user.id,
                    action="USER_LOCKOUT",
                    resource="users",
                    details=f"Account locked for 15 min after {user.failed_login_attempts} failed attempts",
                    ip_address=ip_address
                )
                db.add(audit)
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail="Account is temporarily locked for 15 minutes due to 5 consecutive failed login attempts."
                )
            db.commit()
            raise generic_err

        # On successful credentials:
        user.failed_login_attempts = 0
        user.locked_until = None

        audit = AuditLog(
            user_id=user.id,
            action="USER_LOGIN_SUCCESS",
            resource="users",
            details=f"User {user.email} logged in successfully",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()

        # Generate tokens
        access_token = create_access_token({
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value
        })
        refresh_token = create_refresh_token({
            "sub": str(user.id),
            "email": user.email
        })

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )

    @staticmethod
    def refresh_access_token(db: Session, refresh_token: str) -> TokenResponse:
        """
        Validates refresh token and issues a new access token (CS19-004).
        """
        try:
            payload = decode_token(refresh_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired refresh token."
            )

        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Provided token is not a refresh token."
            )

        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token subject."
            )

        user = db.query(User).filter(User.id == int(user_id)).first()
        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found or account is deactivated."
            )

        new_access_token = create_access_token({
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value
        })
        new_refresh_token = create_refresh_token({
            "sub": str(user.id),
            "email": user.email
        })

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
        )
