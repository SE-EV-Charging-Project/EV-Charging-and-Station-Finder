import secrets
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.config import settings
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.models.verification import VerificationCode
from app.models.token import PasswordResetCode, RevokedToken
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    SendVerificationCodeRequest,
    VerifyCodeRequest,
    VerificationResponse,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
    LogoutRequest,
    MessageResponse,
)
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
    def send_verification_code(
        db: Session, request: SendVerificationCodeRequest, ip_address: str | None = None
    ) -> VerificationResponse:
        """
        Generates and issues a 6-digit OTP verification code (CS19-003 / REQ-F1-03).
        Valid for 10 minutes.
        """
        ident = request.identifier.strip().lower()
        user = db.query(User).filter(
            or_(User.email == ident, User.phone == request.identifier.strip())
        ).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email or phone number."
            )

        # Invalidate previously active unused codes
        db.query(VerificationCode).filter(
            VerificationCode.user_id == user.id,
            VerificationCode.is_used == False
        ).update({"is_used": True})

        # Generate cryptographic 6-digit code
        code_str = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(minutes=10)

        otp_record = VerificationCode(
            user_id=user.id,
            code=code_str,
            channel=request.channel,
            is_used=False,
            expires_at=expires
        )
        db.add(otp_record)

        audit = AuditLog(
            user_id=user.id,
            action="VERIFICATION_CODE_SENT",
            resource="users",
            details=f"Issued 6-digit {request.channel} code expiring in 10 minutes",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()

        return VerificationResponse(
            message=f"Verification code sent via {request.channel}.",
            is_verified=user.is_verified,
            dev_code=code_str
        )

    @staticmethod
    def verify_code(
        db: Session, request: VerifyCodeRequest, ip_address: str | None = None
    ) -> VerificationResponse:
        """
        Verifies the user's 6-digit OTP code and updates is_verified status (CS19-003 / REQ-F1-03).
        """
        ident = request.identifier.strip().lower()
        user = db.query(User).filter(
            or_(User.email == ident, User.phone == request.identifier.strip())
        ).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No account found with this email or phone number."
            )

        otp_record = db.query(VerificationCode).filter(
            VerificationCode.user_id == user.id,
            VerificationCode.code == request.code,
            VerificationCode.is_used == False
        ).order_by(VerificationCode.id.desc()).first()

        if not otp_record:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid verification code."
            )

        now = datetime.now(timezone.utc)
        expires_at_utc = (
            otp_record.expires_at if otp_record.expires_at.tzinfo
            else otp_record.expires_at.replace(tzinfo=timezone.utc)
        )
        if expires_at_utc < now:
            otp_record.is_used = True
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Verification code has expired. Please request a new code."
            )

        otp_record.is_used = True
        user.is_verified = True

        audit = AuditLog(
            user_id=user.id,
            action="USER_VERIFIED",
            resource="users",
            details=f"User {user.email} verified contact details via {otp_record.channel}",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()

        return VerificationResponse(
            message="Contact details successfully verified.",
            is_verified=True
        )

    @staticmethod
    def login_user(db: Session, request: UserLoginRequest, ip_address: str | None = None) -> TokenResponse:
        """
        Authenticates user and issues JWT tokens (CS19-004, CS19-005, CS19-009).
        - Accepts email or registered phone number
        - Generic error on invalid credentials (CS19-009)
        - Locks account for 15 minutes after 5 failed attempts (CS19-005)
        """
        ident = request.identifier.strip().lower()
        user = db.query(User).filter(
            or_(User.email == ident, User.phone == request.identifier.strip())
        ).first()

        now = datetime.now(timezone.utc)

        generic_err = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email/phone or password."
        )

        if not user:
            raise generic_err

        # Check if user account is locked (CS19-005)
        if user.locked_until:
            locked_until_utc = user.locked_until if user.locked_until.tzinfo else user.locked_until.replace(tzinfo=timezone.utc)
            if locked_until_utc > now:
                remaining_sec = (locked_until_utc - now).total_seconds()
                remaining_min = int(remaining_sec // 60) + 1
                raise HTTPException(
                    status_code=status.HTTP_423_LOCKED,
                    detail=f"Account is temporarily locked. Try again after {remaining_min} minute(s)."
                )
            else:
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
        Validates refresh token and issues a new access token (CS19-004, CS19-007).
        Rejects tokens that have been revoked via logout.
        """
        # Check revocation list (CS19-007)
        revoked = db.query(RevokedToken).filter(RevokedToken.token == refresh_token).first()
        if revoked:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token has been revoked. Please log in again."
            )

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

    @staticmethod
    def request_password_reset(
        db: Session, request: PasswordResetRequest, ip_address: str | None = None
    ) -> MessageResponse:
        """
        Generates a 15-minute single-use password reset code (CS19-006 / REQ-F1-06).
        """
        email_clean = request.email.lower().strip()
        user = db.query(User).filter(User.email == email_clean).first()

        # Generic response message to prevent email enumeration
        generic_msg = "If an account with this email exists, a password reset code has been sent."

        if not user:
            return MessageResponse(message=generic_msg)

        # Invalidate existing unused codes
        db.query(PasswordResetCode).filter(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.is_used == False
        ).update({"is_used": True})

        # Generate 6-digit code with 15-minute expiration
        code_str = f"{secrets.randbelow(1000000):06d}"
        expires = datetime.now(timezone.utc) + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)

        reset_record = PasswordResetCode(
            user_id=user.id,
            code=code_str,
            is_used=False,
            expires_at=expires
        )
        db.add(reset_record)

        audit = AuditLog(
            user_id=user.id,
            action="PASSWORD_RESET_REQUESTED",
            resource="users",
            details="Requested password reset code (expires in 15 min)",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()

        return MessageResponse(message=generic_msg, dev_code=code_str)

    @staticmethod
    def confirm_password_reset(
        db: Session, request: PasswordResetConfirmRequest, ip_address: str | None = None
    ) -> MessageResponse:
        """
        Validates single-use reset code and updates password satisfying policy (CS19-006 / REQ-F1-06).
        """
        email_clean = request.email.lower().strip()
        user = db.query(User).filter(User.email == email_clean).first()

        if not user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid password reset request."
            )

        reset_entry = db.query(PasswordResetCode).filter(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.code == request.code,
            PasswordResetCode.is_used == False
        ).order_by(PasswordResetCode.id.desc()).first()

        if not reset_entry:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or already used password reset code."
            )

        now = datetime.now(timezone.utc)
        expires_at_utc = (
            reset_entry.expires_at if reset_entry.expires_at.tzinfo
            else reset_entry.expires_at.replace(tzinfo=timezone.utc)
        )
        if expires_at_utc < now:
            reset_entry.is_used = True
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password reset code has expired. Please request a new code."
            )

        # Mark code as consumed
        reset_entry.is_used = True
        # Update user password
        user.hashed_password = hash_password(request.new_password)
        user.failed_login_attempts = 0
        user.locked_until = None

        audit = AuditLog(
            user_id=user.id,
            action="PASSWORD_RESET_COMPLETED",
            resource="users",
            details="Password successfully reset",
            ip_address=ip_address
        )
        db.add(audit)
        db.commit()

        return MessageResponse(message="Password has been successfully reset. You may now log in with your new password.")

    @staticmethod
    def logout_user(
        db: Session, request: LogoutRequest, ip_address: str | None = None
    ) -> MessageResponse:
        """
        Revokes refresh token upon logout (CS19-007 / REQ-F1-07).
        """
        try:
            payload = decode_token(request.refresh_token)
            user_id = int(payload.get("sub")) if payload.get("sub") else None
        except Exception:
            # Even if token is expired/invalid, we accept logout gracefully
            user_id = None

        # Check if already revoked
        existing = db.query(RevokedToken).filter(RevokedToken.token == request.refresh_token).first()
        if not existing:
            revoked = RevokedToken(
                token=request.refresh_token,
                user_id=user_id
            )
            db.add(revoked)

        if user_id:
            audit = AuditLog(
                user_id=user_id,
                action="USER_LOGOUT",
                resource="auth",
                details="User logged out; refresh token revoked",
                ip_address=ip_address
            )
            db.add(audit)

        db.commit()
        return MessageResponse(message="Successfully logged out. Refresh token revoked.")
