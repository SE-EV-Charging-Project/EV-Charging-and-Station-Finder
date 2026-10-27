from datetime import datetime, timedelta, timezone
import pytest
from app.models.user import User, UserRole
from app.models.token import PasswordResetCode, RevokedToken
from app.models.audit import AuditLog
from app.utils.security import hash_password, verify_password


@pytest.fixture
def registered_user(db_session):
    user = User(
        name="Reset Test User",
        email="reset.user@example.com",
        phone="+919876543111",
        hashed_password=hash_password("OriginalPassword123!"),
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
# TC-F1-06: Password Reset Tests (CS19-006 / REQ-F1-06)
# =========================================================================

def test_tc_f1_06_request_and_confirm_password_reset(client, registered_user, db_session):
    """
    TC-F1-06: Request reset code, confirm with new policy-compliant password, verify new login.
    """
    # 1. Request password reset
    req_res = client.post("/api/v1/auth/password-reset/request", json={
        "email": registered_user.email
    })
    assert req_res.status_code == 200
    reset_data = req_res.json()
    assert "code has been sent" in reset_data["message"]
    reset_code = reset_data["dev_code"]
    assert len(reset_code) == 6
    assert reset_code.isdigit()

    # 2. Confirm password reset with new strong password
    new_pass = "BrandNewPassword123!"
    confirm_res = client.post("/api/v1/auth/password-reset/confirm", json={
        "email": registered_user.email,
        "code": reset_code,
        "new_password": new_pass
    })
    assert confirm_res.status_code == 200
    assert "successfully reset" in confirm_res.json()["message"]

    # 3. Old password should now fail
    old_login = client.post("/api/v1/auth/login", json={
        "identifier": registered_user.email,
        "password": "OriginalPassword123!"
    })
    assert old_login.status_code == 401

    # 4. New password should succeed
    new_login = client.post("/api/v1/auth/login", json={
        "identifier": registered_user.email,
        "password": new_pass
    })
    assert new_login.status_code == 200
    assert "access_token" in new_login.json()

    # Verify audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == registered_user.id,
        AuditLog.action == "PASSWORD_RESET_COMPLETED"
    ).first()
    assert audit is not None


def test_tc_f1_06b_weak_password_rejected_on_reset(client, registered_user):
    """
    TC-F1-06b: Password reset enforces password complexity rules (REQ-F1-02).
    """
    req_res = client.post("/api/v1/auth/password-reset/request", json={
        "email": registered_user.email
    })
    reset_code = req_res.json()["dev_code"]

    confirm_res = client.post("/api/v1/auth/password-reset/confirm", json={
        "email": registered_user.email,
        "code": reset_code,
        "new_password": "weak"
    })
    assert confirm_res.status_code == 422
    assert "at least 8 characters" in confirm_res.text


def test_tc_f1_06c_expired_reset_code_rejected(client, registered_user, db_session):
    """
    TC-F1-06c: Reset code expires after 15 minutes and is rejected.
    """
    req_res = client.post("/api/v1/auth/password-reset/request", json={
        "email": registered_user.email
    })
    reset_code = req_res.json()["dev_code"]

    # Manually backdate the code in database to simulate expiration
    entry = db_session.query(PasswordResetCode).filter(
        PasswordResetCode.user_id == registered_user.id,
        PasswordResetCode.code == reset_code
    ).first()
    entry.expires_at = datetime.now(timezone.utc) - timedelta(minutes=16)
    db_session.commit()

    confirm_res = client.post("/api/v1/auth/password-reset/confirm", json={
        "email": registered_user.email,
        "code": reset_code,
        "new_password": "NewStrongPass123!"
    })
    assert confirm_res.status_code == 400
    assert "expired" in confirm_res.json()["detail"].lower()


def test_tc_f1_06d_used_reset_code_cannot_be_reused(client, registered_user):
    """
    TC-F1-06d: Reset code is strictly single-use.
    """
    req_res = client.post("/api/v1/auth/password-reset/request", json={
        "email": registered_user.email
    })
    reset_code = req_res.json()["dev_code"]

    # First reset succeeds
    res1 = client.post("/api/v1/auth/password-reset/confirm", json={
        "email": registered_user.email,
        "code": reset_code,
        "new_password": "FirstNewPass123!"
    })
    assert res1.status_code == 200

    # Second attempt with same code fails
    res2 = client.post("/api/v1/auth/password-reset/confirm", json={
        "email": registered_user.email,
        "code": reset_code,
        "new_password": "SecondNewPass123!"
    })
    assert res2.status_code == 400


def test_tc_f1_06e_request_reset_nonexistent_email(client):
    """
    TC-F1-06e: Requesting reset for unregistered email returns generic success to avoid enumeration.
    """
    res = client.post("/api/v1/auth/password-reset/request", json={
        "email": "ghost.user@example.com"
    })
    assert res.status_code == 200
    assert "code has been sent" in res.json()["message"]
    assert res.json()["dev_code"] is None


# =========================================================================
# TC-F1-07: Logout & Token Revocation Tests (CS19-007 / REQ-F1-07)
# =========================================================================

def test_tc_f1_07_logout_revokes_refresh_token(client, registered_user, db_session):
    """
    TC-F1-07: Logging out revokes the refresh token; subsequent refresh attempts are denied.
    """
    # 1. Login to get tokens
    login_res = client.post("/api/v1/auth/login", json={
        "identifier": registered_user.email,
        "password": "OriginalPassword123!"
    })
    assert login_res.status_code == 200
    refresh_token = login_res.json()["refresh_token"]

    # 2. Verify refresh token works before logout
    pre_res = client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert pre_res.status_code == 200

    # 3. Logout using the refresh token
    logout_res = client.post("/api/v1/auth/logout", json={
        "refresh_token": refresh_token
    })
    assert logout_res.status_code == 200
    assert "revoked" in logout_res.json()["message"].lower()

    # 4. Attempt to refresh with the revoked token must return 401 Unauthorized
    post_res = client.post("/api/v1/auth/refresh", json={
        "refresh_token": refresh_token
    })
    assert post_res.status_code == 401
    assert "revoked" in post_res.json()["detail"].lower()

    # Verify audit log was recorded
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == registered_user.id,
        AuditLog.action == "USER_LOGOUT"
    ).first()
    assert audit is not None


def test_tc_f1_07b_logout_with_invalid_token_handled_gracefully(client):
    """
    TC-F1-07b: Logging out with a malformed token succeeds safely without crashing.
    """
    res = client.post("/api/v1/auth/logout", json={
        "refresh_token": "malformed.token.value"
    })
    assert res.status_code == 200
    assert "logged out" in res.json()["message"].lower()
