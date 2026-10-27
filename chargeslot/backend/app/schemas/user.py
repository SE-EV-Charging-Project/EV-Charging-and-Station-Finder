import re
from datetime import datetime
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from app.models.user import UserRole
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
