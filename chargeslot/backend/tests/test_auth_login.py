from datetime import datetime, timedelta, timezone
import pytest
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token, decode_token


@pytest.fixture
def test_driver(db_session):
    user = User(
        name="John Test Driver",
        email="john.driver@example.com",
        phone="+919876543210",
        hashed_password=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
        failed_login_attempts=0
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =========================================================================
# TC-F1-04: Login & JWT Tokens (CS19-004 / REQ-F1-04)
# =========================================================================

def test_tc_f1_04_successful_login_with_email(client, test_driver):
    """
    TC-F1-04: Authenticate with email & password, receiving short-lived access and refresh tokens.
    """
    response = client.post("/api/v1/auth/login", json={
        "identifier": "john.driver@example.com",
        "password": "ValidPassword123!"
    })
    assert response.status_code == 200

    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 30 * 60

    # Verify access token content
    payload = decode_token(data["access_token"])
    assert payload["sub"] == str(test_driver.id)
    assert payload["email"] == test_driver.email
    assert payload["role"] == "driver"
    assert payload["type"] == "access"


def test_tc_f1_04b_successful_login_with_phone(client, test_driver):
    """
    TC-F1-04b: Authenticate with registered phone number & password.
    """
    response = client.post("/api/v1/auth/login", json={
        "identifier": "+919876543210",
        "password": "ValidPassword123!"
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


def test_tc_f1_04c_token_refresh(client, test_driver):
    """
    TC-F1-04c: Exchange a valid refresh token for a new access token.
    """
    login_res = client.post("/api/v1/auth/login", json={
        "identifier": test_driver.email,
        "password": "ValidPassword123!"
    })
    refresh_token = login_res.json()["refresh_token"]

    refresh_res = client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert refresh_res.status_code == 200
    new_data = refresh_res.json()
    assert "access_token" in new_data
    assert "refresh_token" in new_data


def test_tc_f1_04d_invalid_refresh_token(client):
    """
    TC-F1-04d: Reject malformed or expired refresh token.
    """
    response = client.post("/api/v1/auth/refresh", json={
        "refresh_token": "invalid.jwt.token"
    })
    assert response.status_code == 401


# =========================================================================
# TC-F1-09: Generic Login Error (CS19-009 / REQ-F1-09)
# =========================================================================

def test_tc_f1_09_generic_error_wrong_password(client, test_driver):
    """
    TC-F1-09: Returns generic error message to prevent user enumeration on wrong password.
    """
    response = client.post("/api/v1/auth/login", json={
        "identifier": test_driver.email,
        "password": "WrongPassword123!"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email/phone or password."


def test_tc_f1_09_generic_error_nonexistent_user(client):
    """
    TC-F1-09: Returns generic error message when user doesn't exist.
    """
    response = client.post("/api/v1/auth/login", json={
        "identifier": "nonexistent@example.com",
        "password": "SomePassword123!"
    })
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email/phone or password."


# =========================================================================
# TC-F1-05: Account Lockout (CS19-005 / REQ-F1-05)
# =========================================================================

def test_tc_f1_05_account_lockout_after_5_failed_attempts(client, test_driver, db_session):
    """
    TC-F1-05: System locks account for 15 minutes after 5 consecutive failed login attempts.
    """
    # 4 failed attempts should return 401
    for i in range(4):
        res = client.post("/api/v1/auth/login", json={
            "identifier": test_driver.email,
            "password": "WrongPassword123!"
        })
        assert res.status_code == 401

    # 5th failed attempt triggers 15-minute lockout (HTTP 423 Locked)
    fifth_res = client.post("/api/v1/auth/login", json={
        "identifier": test_driver.email,
        "password": "WrongPassword123!"
    })
    assert fifth_res.status_code == 423
    assert "locked for 15 minutes" in fifth_res.json()["detail"]

    # Even with correct password, login is blocked while locked
    locked_res = client.post("/api/v1/auth/login", json={
        "identifier": test_driver.email,
        "password": "ValidPassword123!"
    })
    assert locked_res.status_code == 423
    assert "temporarily locked" in locked_res.json()["detail"]

    # Verify audit log recorded USER_LOCKOUT
    lockout_audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == test_driver.id,
        AuditLog.action == "USER_LOCKOUT"
    ).first()
    assert lockout_audit is not None
