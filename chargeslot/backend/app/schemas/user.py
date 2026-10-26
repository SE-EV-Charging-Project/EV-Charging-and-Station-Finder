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
