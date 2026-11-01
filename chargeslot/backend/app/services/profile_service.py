import re
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, ChargingMode
from app.schemas.user import (
    ProfilePreferencesResponse,
    ProfilePreferencesUpdateRequest,
    ProfileValidationCheckRequest,
    ProfileValidationCheckResponse,
    ProfileValidationRulesResponse,
)
from app.services.audit_service import AuditService


class ProfileService:
    """
    Service handling Driver Profile and Preferences Management and Validation
    (CS19-016 / CS19-017 / REQ-F1-16 / REQ-F1-17 / SW Architecture Page 5).
    """

    @staticmethod
    def get_profile(db: Session, user: User) -> ProfilePreferencesResponse:
        """
        Fetch profile information and charging preferences for the user.
        """
        return ProfilePreferencesResponse.model_validate(user)

    @staticmethod
    def edit_profile(
        db: Session,
        user: User,
        data: ProfilePreferencesUpdateRequest,
        ip_address: str | None = None,
    ) -> ProfilePreferencesResponse:
        """
        Update user profile information and charging preferences.
        Enforces validation and uniqueness constraints, and writes an audit log.
        """
        changes: list[str] = []

        if data.name is not None:
            trimmed_name = data.name.strip()
            if len(trimmed_name) < 2:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Name must be at least 2 characters long and cannot be blank.",
                )
            if user.name != trimmed_name:
                changes.append(f"name: '{user.name}' -> '{trimmed_name}'")
                user.name = trimmed_name

        if data.phone is not None:
            cleaned_phone = re.sub(r"[\s\-()]", "", data.phone)
            if not re.match(r"^\+?[0-9]{10,15}$", cleaned_phone):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Phone number must contain 10 to 15 digits, optionally preceded by '+'.",
                )
            # Check for phone uniqueness among other users
            existing = db.query(User).filter(User.phone == cleaned_phone, User.id != user.id).first()
            if existing:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Phone number is already registered to another account.",
                )
            if user.phone != cleaned_phone:
                changes.append(f"phone: '{user.phone}' -> '{cleaned_phone}'")
                user.phone = cleaned_phone

        if data.default_charging_mode is not None:
            if user.default_charging_mode != data.default_charging_mode:
                changes.append(
                    f"charging_mode: '{user.default_charging_mode.value}' -> '{data.default_charging_mode.value}'"
                )
                user.default_charging_mode = data.default_charging_mode

        if data.default_target_battery is not None:
            if data.default_target_battery < 50 or data.default_target_battery > 100:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Target battery percentage must be between 50% and 100%.",
                )
            if user.default_target_battery != data.default_target_battery:
                changes.append(
                    f"target_battery: {user.default_target_battery}% -> {data.default_target_battery}%"
                )
                user.default_target_battery = data.default_target_battery

        if data.low_battery_threshold is not None:
            if data.low_battery_threshold < 10 or data.low_battery_threshold > 30:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Low battery threshold must be between 10% and 30%.",
                )
            if user.low_battery_threshold != data.low_battery_threshold:
                changes.append(
                    f"low_battery_threshold: {user.low_battery_threshold}% -> {data.low_battery_threshold}%"
                )
                user.low_battery_threshold = data.low_battery_threshold

        if data.default_search_radius is not None:
            if data.default_search_radius < 1 or data.default_search_radius > 50:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Search radius must be between 1 and 50 km.",
                )
            if user.default_search_radius != data.default_search_radius:
                changes.append(
                    f"search_radius: {user.default_search_radius}km -> {data.default_search_radius}km"
                )
                user.default_search_radius = data.default_search_radius

        if data.notify_email is not None and user.notify_email != data.notify_email:
            changes.append(f"notify_email: {user.notify_email} -> {data.notify_email}")
            user.notify_email = data.notify_email

        if data.notify_sms is not None and user.notify_sms != data.notify_sms:
            changes.append(f"notify_sms: {user.notify_sms} -> {data.notify_sms}")
            user.notify_sms = data.notify_sms

        if data.notify_push is not None and user.notify_push != data.notify_push:
            changes.append(f"notify_push: {user.notify_push} -> {data.notify_push}")
            user.notify_push = data.notify_push

        if changes:
            AuditService.log_action(
                db=db,
                user_id=user.id,
                action="PROFILE_PREFERENCES_UPDATED",
                resource=f"user:{user.id}",
                details=f"Profile updated: {'; '.join(changes)}",
                ip_address=ip_address,
                commit=False,
            )

        db.commit()
        db.refresh(user)
        return ProfilePreferencesResponse.model_validate(user)

    @staticmethod
    def get_validation_rules() -> ProfileValidationRulesResponse:
        """
        Return metadata validation rules for profile and preference fields (REQ-F1-17).
        """
        rules = {
            "name": {
                "required": True,
                "min_length": 2,
                "max_length": 100,
                "description": "Full name of the user; cannot be blank.",
            },
            "phone": {
                "required": True,
                "pattern": r"^\+?[0-9]{10,15}$",
                "description": "Phone number must contain 10 to 15 digits, optionally preceded by '+'.",
            },
            "default_charging_mode": {
                "required": False,
                "allowed_values": [mode.value for mode in ChargingMode],
                "default": ChargingMode.FASTEST.value,
                "description": "Preferred charging mode (Fastest, Cheapest, Nearest).",
            },
            "default_target_battery": {
                "required": False,
                "min": 50,
                "max": 100,
                "default": 80,
                "unit": "%",
                "description": "Target battery level percentage (50-100%).",
            },
            "low_battery_threshold": {
                "required": False,
                "min": 10,
                "max": 30,
                "default": 20,
                "unit": "%",
                "description": "Low battery alert threshold percentage (10-30%).",
            },
            "default_search_radius": {
                "required": False,
                "min": 1,
                "max": 50,
                "default": 10,
                "unit": "km",
                "description": "Search radius for nearby charging stations (1-50 km).",
            },
            "notifications": {
                "notify_email": {"type": "boolean", "default": True},
                "notify_sms": {"type": "boolean", "default": True},
                "notify_push": {"type": "boolean", "default": True},
            },
        }
        return ProfileValidationRulesResponse(rules=rules, status="success")

    @staticmethod
    def validate_profile_inputs(
        db: Session,
        payload: ProfileValidationCheckRequest,
        current_user_id: int | None = None,
    ) -> ProfileValidationCheckResponse:
        """
        Validate profile and preference inputs returning inline error feedback (CS19-017 / REQ-F1-17).
        """
        errors: dict[str, str] = {}

        if payload.name is not None:
            trimmed = payload.name.strip()
            if len(trimmed) < 2:
                errors["name"] = "Name must be at least 2 characters long and cannot be blank."
            elif len(trimmed) > 100:
                errors["name"] = "Name cannot exceed 100 characters."

        if payload.phone is not None:
            cleaned = re.sub(r"[\s\-()]", "", payload.phone)
            if not re.match(r"^\+?[0-9]{10,15}$", cleaned):
                errors["phone"] = "Phone number must contain 10 to 15 digits, optionally preceded by '+'."
            else:
                existing_query = db.query(User).filter(User.phone == cleaned)
                if current_user_id is not None:
                    existing_query = existing_query.filter(User.id != current_user_id)
                if existing_query.first():
                    errors["phone"] = "Phone number is already registered to another account."

        if payload.default_charging_mode is not None:
            allowed = [mode.value for mode in ChargingMode]
            if payload.default_charging_mode not in allowed:
                errors["default_charging_mode"] = f"Invalid charging mode. Allowed values: {', '.join(allowed)}."

        if payload.default_target_battery is not None:
            if payload.default_target_battery < 50 or payload.default_target_battery > 100:
                errors["default_target_battery"] = "Target battery percentage must be between 50% and 100%."

        if payload.low_battery_threshold is not None:
            if payload.low_battery_threshold < 10 or payload.low_battery_threshold > 30:
                errors["low_battery_threshold"] = "Low battery threshold must be between 10% and 30%."

        if payload.default_search_radius is not None:
            if payload.default_search_radius < 1 or payload.default_search_radius > 50:
                errors["default_search_radius"] = "Search radius must be between 1 and 50 km."

        is_valid = len(errors) == 0
        message = "Validation successful. All field values are valid." if is_valid else "Validation failed with field errors."

        return ProfileValidationCheckResponse(
            is_valid=is_valid,
            errors=errors,
            message=message,
        )
