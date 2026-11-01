import re
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models.user import UserRole
from app.models.operator_application import ApplicationStatus
from app.utils.security import validate_password_policy


class UserRegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Full name of user")
    email: EmailStr = Field(..., description="Unique email address")
    phone: str = Field(..., description="Unique contact phone number with optional country code")
    password: str = Field(..., min_length=8, description="Account password satisfying policy")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 2:
            raise ValueError("Name must be at least 2 characters long.")
        return trimmed

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", v)
        if not re.match(r"^\+?[0-9]{10,15}$", cleaned):
            raise ValueError("Phone number must contain 10 to 15 digits, optionally preceded by '+'.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        is_valid, msg = validate_password_policy(v)
        if not is_valid:
            raise ValueError(msg)
        return v


class UserLoginRequest(BaseModel):
    identifier: str = Field(..., description="User email address or registered mobile number")
    password: str = Field(..., description="User password")

    @field_validator("identifier")
    @classmethod
    def clean_identifier(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed:
            raise ValueError("Identifier cannot be empty.")
        return trimmed


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # in seconds


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class SendVerificationCodeRequest(BaseModel):
    identifier: str = Field(..., description="Email address or phone number to send verification code to")
    channel: str = Field("email", description="Verification channel: 'email' or 'phone'")

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v: str) -> str:
        channel_lower = v.strip().lower()
        if channel_lower not in ["email", "phone"]:
            raise ValueError("Channel must be 'email' or 'phone'.")
        return channel_lower


class VerifyCodeRequest(BaseModel):
    identifier: str = Field(..., description="Registered email address or phone number")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit verification code")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed.isdigit() or len(trimmed) != 6:
            raise ValueError("Verification code must be exactly 6 digits.")
        return trimmed


class VerificationResponse(BaseModel):
    message: str
    is_verified: bool
    dev_code: str | None = None


class PasswordResetRequest(BaseModel):
    email: EmailStr = Field(..., description="Registered email address for password reset")


class PasswordResetConfirmRequest(BaseModel):
    email: EmailStr = Field(..., description="Registered email address")
    code: str = Field(..., min_length=6, max_length=6, description="6-digit password reset code")
    new_password: str = Field(..., min_length=8, description="New account password satisfying policy")

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        trimmed = v.strip()
        if not trimmed.isdigit() or len(trimmed) != 6:
            raise ValueError("Reset code must be exactly 6 digits.")
        return trimmed

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, v: str) -> str:
        is_valid, msg = validate_password_policy(v)
        if not is_valid:
            raise ValueError(msg)
        return v


class LogoutRequest(BaseModel):
    refresh_token: str = Field(..., description="Refresh token to be invalidated")


class MessageResponse(BaseModel):
    message: str
    dev_code: str | None = None


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str
    phone: str
    role: UserRole
    is_verified: bool
    is_active: bool
    created_at: datetime


class RbacCheckResponse(BaseModel):
    status: str = "authorized"
    user_id: int
    email: str
    role: str
    message: str


class AdminCreateUserRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=100, description="Full name of user")
    email: EmailStr = Field(..., description="Unique email address")
    phone: str = Field(..., description="Unique contact phone number")
    password: str = Field(..., min_length=8, description="Initial account password")
    role: UserRole = Field(default=UserRole.DRIVER, description="Assigned user role")
    is_verified: bool = Field(default=False, description="Email/phone verification state")
    operator_organization: str | None = Field(default=None, max_length=150, description="Organization name if operator")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 2:
            raise ValueError("Name must be at least 2 characters long.")
        return trimmed

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", v)
        if not re.match(r"^\+?[0-9]{10,15}$", cleaned):
            raise ValueError("Phone number must contain 10 to 15 digits, optionally preceded by '+'.")
        return cleaned

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        is_valid, msg = validate_password_policy(v)
        if not is_valid:
            raise ValueError(msg)
        return v


class AdminUpdateUserRequest(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    role: UserRole | None = Field(default=None, description="New role for the user")
    is_active: bool | None = Field(default=None, description="Activate or deactivate account")
    is_verified: bool | None = Field(default=None, description="Set verification state")
    operator_organization: str | None = Field(default=None, max_length=150)


class AdminUserManagementPatchRequest(BaseModel):
    user_id: int = Field(..., description="Target user ID to manage")
    role: UserRole | None = Field(default=None, description="Updated role")
    is_active: bool | None = Field(default=None, description="Updated active status")
    is_verified: bool | None = Field(default=None, description="Updated verification status")


class AdminUserListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[UserResponse]


# ==============================================================================
# Audit Log Schemas (CS19-014 / REQ-F1-14)
# ==============================================================================

class AuditLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None
    user_email: str | None = None
    action: str
    resource: str | None
    details: str | None
    ip_address: str | None
    timestamp: datetime


class AuditLogListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[AuditLogResponse]


# ==============================================================================
# Operator Onboarding Schemas (CS19-015 / REQ-F1-15)
# ==============================================================================

class OperatorApplicationCreate(BaseModel):
    business_name: str = Field(..., min_length=2, max_length=200, description="Registered business or legal operator name")
    contact_email: EmailStr = Field(..., description="Business contact email")
    contact_phone: str = Field(..., description="Business contact phone number")
    business_address: str | None = Field(default=None, max_length=500, description="Business or headquarters address")
    tax_identifier: str | None = Field(default=None, max_length=100, description="Business tax ID / GSTIN / CIN")

    @field_validator("business_name")
    @classmethod
    def validate_business_name(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 2:
            raise ValueError("Business name must be at least 2 characters long.")
        return trimmed

    @field_validator("contact_phone")
    @classmethod
    def validate_contact_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-()]", "", v)
        if not re.match(r"^\+?[0-9]{10,15}$", cleaned):
            raise ValueError("Contact phone number must contain 10 to 15 digits, optionally preceded by '+'.")
        return cleaned


class OperatorApplicationRejectRequest(BaseModel):
    reason: str = Field(..., min_length=5, max_length=1000, description="Reason for rejecting the operator application")

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: str) -> str:
        trimmed = v.strip()
        if len(trimmed) < 5:
            raise ValueError("Rejection reason must be at least 5 characters long.")
        return trimmed


class OperatorApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    applicant_name: str | None = None
    applicant_email: str | None = None
    business_name: str
    contact_email: str
    contact_phone: str
    business_address: str | None = None
    tax_identifier: str | None = None
    status: ApplicationStatus
    rejection_reason: str | None = None
    reviewed_by_admin_id: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class OperatorApplicationListResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[OperatorApplicationResponse]



