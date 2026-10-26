import pytest
from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.utils.security import validate_password_policy, hash_password, verify_password


# =========================================================================
# TC-F1-02: Password Policy Tests (CS19-002 / REQ-F1-02)
# =========================================================================

def test_tc_f1_02_password_policy_too_short():
    valid, msg = validate_password_policy("Ab1!xyz")
    assert not valid
    assert "at least 8 characters" in msg


def test_tc_f1_02_password_policy_missing_uppercase():
    valid, msg = validate_password_policy("password123!")
    assert not valid
    assert "uppercase letter" in msg


def test_tc_f1_02_password_policy_missing_lowercase():
    valid, msg = validate_password_policy("PASSWORD123!")
    assert not valid
    assert "lowercase letter" in msg


def test_tc_f1_02_password_policy_missing_digit():
    valid, msg = validate_password_policy("Password!@#")
    assert not valid
    assert "at least one digit" in msg


def test_tc_f1_02_password_policy_missing_special_char():
    valid, msg = validate_password_policy("Password123")
    assert not valid
    assert "special character" in msg


def test_tc_f1_02_password_policy_valid():
    valid, msg = validate_password_policy("StrongPass123!")
    assert valid
    assert msg == ""


def test_tc_f1_02_password_hashing_and_verification():
    raw = "MySecurePwd123!"
    hashed = hash_password(raw)
    assert hashed != raw
    assert verify_password(raw, hashed) is True
    assert verify_password("WrongPassword123!", hashed) is False


def test_tc_f1_02_api_rejects_weak_password(client):
    payload = {
        "name": "Weak Pass User",
        "email": "weak@example.com",
        "phone": "+919123456789",
        "password": "weak"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422
    assert "at least 8 characters" in response.text


# =========================================================================
# TC-F1-01: User Registration Tests (CS19-001 / REQ-F1-01)
# =========================================================================

def test_tc_f1_01_successful_registration(client, db_session):
    """
    TC-F1-01: System allows new user registration with name, email, phone, password.
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


# =========================================================================
# TC-F1-08: Reject Duplicate Account Tests (CS19-008 / REQ-F1-08)
# =========================================================================

def test_tc_f1_08_duplicate_email_rejected(client):
    """
    TC-F1-08: System rejects registration when email already belongs to an existing account.
    """
    payload = {
        "name": "First User",
        "email": "duplicate.email@example.com",
        "phone": "+919876543201",
        "password": "ValidPassword123!"
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload_duplicate_email = {
        "name": "Second User",
        "email": "duplicate.email@example.com",
        "phone": "+919876543202",
        "password": "ValidPassword123!"
    }
    res2 = client.post("/api/v1/auth/register", json=payload_duplicate_email)
    assert res2.status_code == 409
    assert "email already exists" in res2.json()["detail"]


def test_tc_f1_08_duplicate_phone_rejected(client):
    """
    TC-F1-08: System rejects registration when phone already belongs to an existing account.
    """
    payload = {
        "name": "First User",
        "email": "phone1@example.com",
        "phone": "+919999888877",
        "password": "ValidPassword123!"
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    payload_duplicate_phone = {
        "name": "Second User",
        "email": "phone2@example.com",
        "phone": "+919999888877",
        "password": "ValidPassword123!"
    }
    res2 = client.post("/api/v1/auth/register", json=payload_duplicate_phone)
    assert res2.status_code == 409
    assert "phone number already exists" in res2.json()["detail"]


# =========================================================================
# TC-F1-10: Assign Exactly One Role Tests (CS19-010 / REQ-F1-10)
# =========================================================================

def test_tc_f1_10_self_registration_defaults_to_single_driver_role(client, db_session):
    """
    TC-F1-10: Self-registered account has exactly one role and defaults to Driver.
    """
    payload = {
        "name": "Role Test User",
        "email": "role.test@example.com",
        "phone": "+919888777666",
        "password": "StrongPassword123!"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    assert response.json()["role"] == "driver"

    user = db_session.query(User).filter(User.email == "role.test@example.com").first()
    assert user.role == UserRole.DRIVER
    assert isinstance(user.role, UserRole)
    # Confirm role belongs to the allowed 3 roles only
    assert user.role in [UserRole.DRIVER, UserRole.OPERATOR, UserRole.ADMIN]


# =========================================================================
# Data Validation & Bad Inputs
# =========================================================================

def test_validation_rejects_empty_name_and_invalid_phone(client):
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
        "phone": "invalid_phone_string",
        "password": "StrongPassword123!"
    })
    assert res2.status_code == 422
