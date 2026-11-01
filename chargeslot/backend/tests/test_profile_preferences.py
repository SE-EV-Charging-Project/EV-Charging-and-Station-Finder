"""
Unit and Integration Tests for Driver Profile and Preferences Management and Validation.
Requirements: REQ-F1-16, REQ-F1-17
Story IDs: CS19-016, CS19-017
Test Case IDs: TC-F1-16, TC-F1-17
System Test Case IDs: STC-F1-16, STC-F1-17
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole, ChargingMode
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Alex Driver",
        email="alex.driver@example.com",
        phone="+12003004001",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(driver)
    db_session.commit()
    db_session.refresh(driver)
    return driver


@pytest.fixture
def other_user(db_session: Session) -> User:
    user = User(
        name="Other User",
        email="other.user@example.com",
        phone="+12003004002",
        hashed_password=hash_password("OtherPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# ==============================================================================
# CS19-016 / REQ-F1-16: Edit Profile and Preferences
# ==============================================================================

def test_get_profile_default_values(client: TestClient, driver_user: User):
    """TC-F1-16-01: Verifies fetching profile returns system defaults for preferences."""
    token = make_token(driver_user)
    resp = client.get(
        "/api/v1/accounts/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == driver_user.id
    assert data["name"] == "Alex Driver"
    assert data["email"] == "alex.driver@example.com"
    assert data["phone"] == "+12003004001"
    assert data["default_charging_mode"] == "Fastest"
    assert data["default_target_battery"] == 80
    assert data["low_battery_threshold"] == 20
    assert data["default_search_radius"] == 10
    assert data["notify_email"] is True
    assert data["notify_sms"] is True
    assert data["notify_push"] is True


def test_get_profile_architecture_route_alias(client: TestClient, driver_user: User):
    """TC-F1-16-02: Verifies SW Architecture route GET /api/v1/accounts/edit-profile-and-preferences."""
    token = make_token(driver_user)
    resp = client.get(
        "/api/v1/accounts/edit-profile-and-preferences",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == driver_user.id
    assert data["default_charging_mode"] == "Fastest"


def test_edit_profile_and_preferences_success(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-16-03 / STC-F1-16-01: Updates all preferences and driver profile info successfully."""
    token = make_token(driver_user)
    payload = {
        "name": "Alexandria Driver",
        "phone": "+19998887771",
        "default_charging_mode": "Cheapest",
        "default_target_battery": 90,
        "low_battery_threshold": 15,
        "default_search_radius": 25,
        "notify_email": False,
        "notify_sms": True,
        "notify_push": False,
    }
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Alexandria Driver"
    assert data["phone"] == "+19998887771"
    assert data["default_charging_mode"] == "Cheapest"
    assert data["default_target_battery"] == 90
    assert data["low_battery_threshold"] == 15
    assert data["default_search_radius"] == 25
    assert data["notify_email"] is False
    assert data["notify_sms"] is True
    assert data["notify_push"] is False

    # Check database persistence
    db_session.refresh(driver_user)
    assert driver_user.name == "Alexandria Driver"
    assert driver_user.phone == "+19998887771"
    assert driver_user.default_charging_mode == ChargingMode.CHEAPEST
    assert driver_user.default_target_battery == 90
    assert driver_user.low_battery_threshold == 15
    assert driver_user.default_search_radius == 25
    assert driver_user.notify_email is False
    assert driver_user.notify_push is False


def test_edit_profile_partial_update(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-16-04: Partially updates charging mode to Nearest without affecting other fields."""
    token = make_token(driver_user)
    payload = {"default_charging_mode": "Nearest"}
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["default_charging_mode"] == "Nearest"
    assert data["default_target_battery"] == 80  # unchanged
    assert data["name"] == "Alex Driver"  # unchanged


def test_edit_profile_creates_audit_log(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-16-05: Verifies that updating profile writes an immutable audit log entry."""
    token = make_token(driver_user)
    payload = {"default_target_battery": 95}
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver_user.id,
            AuditLog.action == "PROFILE_PREFERENCES_UPDATED",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_entry is not None
    assert "target_battery" in audit_entry.details


def test_edit_profile_phone_conflict(
    client: TestClient, driver_user: User, other_user: User
):
    """TC-F1-16-06: Verifies 409 Conflict when attempting to use an already registered phone."""
    token = make_token(driver_user)
    payload = {"phone": other_user.phone}
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
    assert "already registered" in resp.json()["detail"].lower()


# ==============================================================================
# CS19-017 / REQ-F1-17: Profile Validation
# ==============================================================================

def test_validation_reject_blank_name(client: TestClient, driver_user: User):
    """TC-F1-17-01: Rejects blank or single character name with 422."""
    token = make_token(driver_user)
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"name": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    resp_single = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"name": "A"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_single.status_code == 422


def test_validation_reject_malformed_phone(client: TestClient, driver_user: User):
    """TC-F1-17-02: Rejects invalid format phone numbers with 422."""
    token = make_token(driver_user)
    for bad_phone in ["invalid-phone", "123", "+12345678901234567890"]:
        resp = client.patch(
            "/api/v1/accounts/edit-profile-and-preferences",
            json={"phone": bad_phone},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


def test_validation_reject_out_of_range_target_battery(client: TestClient, driver_user: User):
    """TC-F1-17-03: Rejects target battery below 50% or above 100%."""
    token = make_token(driver_user)
    # Below 50%
    resp_low = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_target_battery": 49},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 100%
    resp_high = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_target_battery": 101},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_reject_out_of_range_low_battery_threshold(client: TestClient, driver_user: User):
    """TC-F1-17-04: Rejects low battery threshold below 10% or above 30%."""
    token = make_token(driver_user)
    # Below 10%
    resp_low = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"low_battery_threshold": 9},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 30%
    resp_high = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"low_battery_threshold": 31},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_reject_out_of_range_search_radius(client: TestClient, driver_user: User):
    """TC-F1-17-05: Rejects search radius below 1 km or above 50 km."""
    token = make_token(driver_user)
    resp_low = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_search_radius": 0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    resp_high = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_search_radius": 51},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_reject_invalid_charging_mode(client: TestClient, driver_user: User):
    """TC-F1-17-06: Rejects unsupported charging modes with 422."""
    token = make_token(driver_user)
    resp = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_charging_mode": "UltraFastTurbo"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_get_profile_validation_rules(client: TestClient):
    """TC-F1-17-07 / STC-F1-17-01: Verifies validation metadata schema endpoint."""
    resp = client.get("/api/v1/accounts/profile-validation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    rules = data["rules"]
    assert "name" in rules
    assert "phone" in rules
    assert "default_charging_mode" in rules
    assert rules["default_charging_mode"]["allowed_values"] == ["Fastest", "Cheapest", "Nearest"]
    assert rules["default_target_battery"]["min"] == 50
    assert rules["default_target_battery"]["max"] == 100
    assert rules["low_battery_threshold"]["min"] == 10
    assert rules["low_battery_threshold"]["max"] == 30
    assert rules["default_search_radius"]["min"] == 1
    assert rules["default_search_radius"]["max"] == 50


def test_post_inline_profile_validation_valid(client: TestClient, driver_user: User):
    """TC-F1-17-08: Verifies dynamic inline validation returns is_valid=True for valid fields."""
    token = make_token(driver_user)
    payload = {
        "name": "Jane Valid",
        "phone": "+19876543210",
        "default_charging_mode": "Cheapest",
        "default_target_battery": 75,
        "low_battery_threshold": 18,
        "default_search_radius": 15,
    }
    resp = client.post(
        "/api/v1/accounts/profile-validation",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True
    assert data["errors"] == {}


def test_post_inline_profile_validation_invalid(
    client: TestClient, driver_user: User, other_user: User
):
    """TC-F1-17-09: Verifies dynamic inline validation returns field-level error messages."""
    token = make_token(driver_user)
    payload = {
        "name": " ",  # blank name
        "phone": other_user.phone,  # duplicate phone
        "default_charging_mode": "InvalidMode",
        "default_target_battery": 120,  # > 100
        "low_battery_threshold": 5,  # < 10
        "default_search_radius": 100,  # > 50
    }
    resp = client.post(
        "/api/v1/accounts/profile-validation",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    errors = data["errors"]
    assert "name" in errors
    assert "phone" in errors
    assert "already registered" in errors["phone"].lower()
    assert "default_charging_mode" in errors
    assert "default_target_battery" in errors
    assert "low_battery_threshold" in errors
    assert "default_search_radius" in errors


def test_unauthenticated_requests_rejected(client: TestClient):
    """TC-F1-16-07: Verifies unauthenticated calls to profile endpoints return 401."""
    resp_get = client.get("/api/v1/accounts/profile")
    assert resp_get.status_code == 401

    resp_patch = client.patch(
        "/api/v1/accounts/edit-profile-and-preferences",
        json={"default_target_battery": 90},
    )
    assert resp_patch.status_code == 401
