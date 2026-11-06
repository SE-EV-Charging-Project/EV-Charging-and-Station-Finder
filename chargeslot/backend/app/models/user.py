import enum
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, Integer, DateTime, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


class UserRole(str, enum.Enum):
    DRIVER = "driver"
    OPERATOR = "operator"
    ADMIN = "admin"


class ChargingMode(str, enum.Enum):
    FASTEST = "Fastest"
    CHEAPEST = "Cheapest"
    NEAREST = "Nearest"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role_enum", native_enum=False),
        default=UserRole.DRIVER,
        nullable=False
    )
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_organization: Mapped[str | None] = mapped_column(String(150), nullable=True)

    # Driver Preferences (REQ-F1-16 / Appendix B.1, B.2)
    default_charging_mode: Mapped[ChargingMode] = mapped_column(
        Enum(ChargingMode, name="charging_mode_enum", native_enum=False),
        default=ChargingMode.FASTEST,
        nullable=False
    )
    default_target_battery: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    low_battery_threshold: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    default_search_radius: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_sms: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_push: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False
    )

    audit_logs = relationship("AuditLog", back_populates="user", cascade="all, delete-orphan")
    verification_codes = relationship("VerificationCode", back_populates="user", cascade="all, delete-orphan")
    password_reset_codes = relationship("PasswordResetCode", back_populates="user", cascade="all, delete-orphan")
    revoked_tokens = relationship("RevokedToken", back_populates="user", cascade="all, delete-orphan")
    operator_applications = relationship(
        "OperatorApplication",
        foreign_keys="OperatorApplication.user_id",
        back_populates="user",
        cascade="all, delete-orphan"
    )
    vehicles = relationship("Vehicle", back_populates="user", cascade="all, delete-orphan")
    bookings = relationship("Booking", back_populates="user", cascade="all, delete-orphan")
    stations = relationship("Station", foreign_keys="Station.operator_id", back_populates="operator", cascade="all, delete-orphan")
