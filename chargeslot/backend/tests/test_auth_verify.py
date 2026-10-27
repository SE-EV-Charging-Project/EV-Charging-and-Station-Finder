from datetime import datetime, timedelta, timezone
import pytest
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.models.verification import VerificationCode
from app.utils.security import hash_password


@pytest.fixture
def unverified_driver(db_session):
    user = User(
        name="Unverified Driver",
        email="unverified.driver@example.com",
        phone="+919876543299",
        hashed_password=hash_password("ValidPassword123!"),
        role=UserRole.DRIVER,
        is_verified=False,
        is_active=True,
        failed_login_attempts=0
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


# =========================================================================
# TC-F1-03: Verify Contact Details (CS19-003 / REQ-F1-03)
# =========================================================================

def test_tc_f1_03_send_and_verify_email_code(client, unverified_driver, db_session):
    """
    TC-F1-03: Issue 6-digit one-time code to email and verify successfully.
    """
    # 1. Send verification code
    send_res = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": unverified_driver.email,
        "channel": "email"
    })
    assert send_res.status_code == 200
    data = send_res.json()
    assert "code sent via email" in data["message"].lower()
    otp_code = data["dev_code"]
    assert len(otp_code) == 6
    assert otp_code.isdigit()

    # 2. Verify with code
    verify_res = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.email,
        "code": otp_code
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["is_verified"] is True

    # 3. Check DB state
    db_session.refresh(unverified_driver)
    assert unverified_driver.is_verified is True

    # Check audit log was recorded
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == unverified_driver.id,
        AuditLog.action == "USER_VERIFIED"
    ).first()
    assert audit is not None


def test_tc_f1_03b_send_and_verify_phone_code(client, unverified_driver, db_session):
    """
    TC-F1-03b: Issue 6-digit one-time code to phone and verify successfully.
    """
    send_res = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": unverified_driver.phone,
        "channel": "phone"
    })
    assert send_res.status_code == 200
    otp_code = send_res.json()["dev_code"]

    verify_res = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.phone,
        "code": otp_code
    })
    assert verify_res.status_code == 200
    assert verify_res.json()["is_verified"] is True

    db_session.refresh(unverified_driver)
    assert unverified_driver.is_verified is True


def test_tc_f1_03c_invalid_code_rejected(client, unverified_driver):
    """
    TC-F1-03c: Rejects incorrect OTP code with 400 Bad Request.
    """
    client.post("/api/v1/auth/verify/send-code", json={
        "identifier": unverified_driver.email,
        "channel": "email"
    })

    verify_res = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.email,
        "code": "999999"  # Incorrect code
    })
    assert verify_res.status_code == 400
    assert "invalid" in verify_res.json()["detail"].lower()


def test_tc_f1_03d_expired_code_rejected(client, unverified_driver, db_session):
    """
    TC-F1-03d: Rejects OTP code that has exceeded the 10-minute expiry window.
    """
    send_res = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": unverified_driver.email,
        "channel": "email"
    })
    otp_code = send_res.json()["dev_code"]

    # Manually expire the code in the DB
    otp_entry = db_session.query(VerificationCode).filter(
        VerificationCode.user_id == unverified_driver.id,
        VerificationCode.code == otp_code
    ).first()
    otp_entry.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    db_session.commit()

    verify_res = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.email,
        "code": otp_code
    })
    assert verify_res.status_code == 400
    assert "expired" in verify_res.json()["detail"].lower()


def test_tc_f1_03e_already_used_code_cannot_be_reused(client, unverified_driver):
    """
    TC-F1-03e: Single-use guarantee - OTP cannot be used multiple times.
    """
    send_res = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": unverified_driver.email,
        "channel": "email"
    })
    otp_code = send_res.json()["dev_code"]

    # First verification succeeds
    res1 = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.email,
        "code": otp_code
    })
    assert res1.status_code == 200

    # Second attempt with same code fails
    res2 = client.post("/api/v1/auth/verify", json={
        "identifier": unverified_driver.email,
        "code": otp_code
    })
    assert res2.status_code == 400


def test_tc_f1_03f_send_code_nonexistent_user(client):
    """
    TC-F1-03f: Requesting code for unregistered identifier returns 404.
    """
    res = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": "unknown@example.com",
        "channel": "email"
    })
    assert res.status_code == 404


def test_tc_f1_03g_verify_code_nonexistent_user(client):
    """
    TC-F1-03g: Verifying code for unregistered identifier returns 404.
    """
    res = client.post("/api/v1/auth/verify", json={
        "identifier": "unknown@example.com",
        "code": "123456"
    })
    assert res.status_code == 404


def test_validation_rejects_malformed_otp_and_channel(client):
    """
    Validation tests: non-numeric OTP, non-6-digit OTP, or invalid channel.
    """
    res1 = client.post("/api/v1/auth/verify/send-code", json={
        "identifier": "test@example.com",
        "channel": "telegram"  # invalid channel
    })
    assert res1.status_code == 422

    res2 = client.post("/api/v1/auth/verify", json={
        "identifier": "test@example.com",
        "code": "12345"  # 5 digits instead of 6
    })
    assert res2.status_code == 422
