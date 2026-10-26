import pytest
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.utils.security import validate_password_policy, hash_password, verify_password


# ==========================================
# Unit Tests for Password Policy (CS19-002 / TC-F1-02)
# ==========================================

def test_password_policy_too_short():
    valid, msg = validate_password_policy("Ab1!xyz")
    assert not valid
    assert "at least 8 characters" in msg


def test_password_policy_missing_uppercase():
    valid, msg = validate_password_policy("password123!")
    assert not valid
    assert "uppercase letter" in msg


def test_password_policy_missing_lowercase():
    valid, msg = validate_password_policy("PASSWORD123!")
    assert not valid
    assert "lowercase letter" in msg


def test_password_policy_missing_digit():
    valid, msg = validate_password_policy("Password!@#")
    assert not valid
    assert "at least one digit" in msg


def test_password_policy_missing_special_char():
    valid, msg = validate_password_policy("Password123")
    assert not valid
    assert "special character" in msg


def test_password_policy_valid():
    valid, msg = validate_password_policy("StrongPass123!")
    assert valid
    assert msg == ""


def test_password_hashing_and_verification():
    raw = "MySecurePwd123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


# ==========================================
# Integration & API Tests for Register (CS19-001 / TC-F1-01)
# ==========================================

def test_tc_f1_01_successful_registration(client, db_session):
    """
    TC-F1-01: System allows new user registration and assigns Driver role by default.
    """
    payload = {
        "name": "Jane Driver",
        "email": "jane.driver@example.com",
        "phone": "+919876543210",
        "password": "SecurePassword123!"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Jane Driver"
    assert data["email"] == "jane.driver@example.com"
    assert data["phone"] == "+919876543210"
    assert data["role"] == "driver"
    assert data["is_active"] is True
    assert data["is_verified"] is False
    assert "hashed_password" not in data

    # Verify user exists in database
    user = db_session.query(User).filter(User.email == "jane.driver@example.com").first()
    assert user is not None
    assert user.role == UserRole.DRIVER

    # Verify audit log was recorded (CS19-014)
    audit = db_session.query(AuditLog).filter(AuditLog.user_id == user.id).first()
    assert audit is not None
    assert audit.action == "USER_REGISTERED"


def test_tc_f1_01b_duplicate_email_rejected(client):
    """
    TC-F1-01b: Reject registration when email is already registered (409 Conflict).
    """
    payload = {
        "name": "First User",
        "email": "unique@example.com",
        "phone": "+919876543201",
        "password": "ValidPassword123!"
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload_duplicate_email = {
        "name": "Second User",
        "email": "unique@example.com",
        "phone": "+919876543202",
        "password": "ValidPassword123!"
    }
    res2 = client.post("/api/v1/auth/register", json=payload_duplicate_email)
    assert res2.status_code == 409
    assert "email already exists" in res2.json()["detail"]


def test_tc_f1_01c_duplicate_phone_rejected(client):
    """
    TC-F1-01c: Reject registration when phone is already registered (409 Conflict).
    """
    payload = {
        "name": "First User",
        "email": "first@example.com",
        "phone": "+919999888877",
        "password": "ValidPassword123!"
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload_duplicate_phone = {
        "name": "Second User",
        "email": "second@example.com",
        "phone": "+919999888877",
        "password": "ValidPassword123!"
    }
    res2 = client.post("/api/v1/auth/register", json=payload_duplicate_phone)
    assert res2.status_code == 409
    assert "phone number already exists" in res2.json()["detail"]


def test_tc_f1_02_registration_rejects_weak_password(client):
    """
    TC-F1-02: Registration rejected with 422 if password does not satisfy policy.
    """
    payload = {
        "name": "Weak Pass User",
        "email": "weak@example.com",
        "phone": "+919123456789",
        "password": "weak"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert "at least 8 characters" in response.text


def test_validation_rejects_invalid_name_and_phone(client):
    """
    Validation tests for empty name and invalid phone digits.
    """
    res1 = client.post("/api/v1/auth/register", json={
        "name": "   ",
        "email": "test@example.com",
        "phone": "+919876543210",
        "password": "StrongPassword123!"
    })
    assert res1.status_code == 422

    res2 = client.post("/api/v1/auth/register", json={
        "name": "Valid Name",
        "email": "test@example.com",
        "phone": "not-a-number",
        "password": "StrongPassword123!"
    })
    assert res2.status_code == 422
