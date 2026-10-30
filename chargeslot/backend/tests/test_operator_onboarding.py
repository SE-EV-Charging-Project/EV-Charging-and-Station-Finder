"""
Tests for Station Operator Onboarding
Requirement: REQ-F1-15 (and REQ-F1-14 audit integration)
Story ID: CS19-015
Test Case ID: TC-F1-15
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.operator_application import OperatorApplication, ApplicationStatus
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token


@pytest.fixture
def test_admin(db_session: Session) -> User:
    admin = User(
        name="Admin Approver",
        email="onboard.admin@example.com",
        phone="+12345678920",
        hashed_password=hash_password("AdminPass123!"),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def test_driver(db_session: Session) -> User:
    driver = User(
        name="Applicant Driver",
        email="onboard.driver@example.com",
        phone="+12345678921",
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
def second_driver(db_session: Session) -> User:
    driver2 = User(
        name="Other Driver",
        email="other.driver@example.com",
        phone="+12345678922",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(driver2)
    db_session.commit()
    db_session.refresh(driver2)
    return driver2


@pytest.fixture
def existing_operator(db_session: Session) -> User:
    operator = User(
        name="Existing Op",
        email="existing.op@example.com",
        phone="+12345678923",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Existing Power Grid",
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    db_session.refresh(operator)
    return operator


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def admin_token(test_admin: User) -> str:
    return make_token(test_admin)


@pytest.fixture
def driver_token(test_driver: User) -> str:
    return make_token(test_driver)


@pytest.fixture
def second_driver_token(second_driver: User) -> str:
    return make_token(second_driver)


@pytest.fixture
def operator_token(existing_operator: User) -> str:
    return make_token(existing_operator)


def test_driver_can_apply_for_operator_status(client: TestClient, driver_token: str, db_session: Session, test_driver: User):
    """TC-F1-15.1: Driver successfully submits an operator application and audit log is written."""
    payload = {
        "business_name": "ElectroCharge Solutions Ltd",
        "contact_email": "biz@electrocharge.com",
        "contact_phone": "+12345678921",
        "business_address": "123 Green Way, Bangalore, India",
        "tax_identifier": "GSTIN1234567890",
    }
    resp = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["business_name"] == "ElectroCharge Solutions Ltd"
    assert data["status"] == "PENDING"
    assert data["user_id"] == test_driver.id

    # Verify audit log recorded
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == test_driver.id,
        AuditLog.action == "OPERATOR_APPLICATION_SUBMITTED"
    ).first()
    assert audit is not None
    assert "ElectroCharge Solutions Ltd" in audit.details


def test_duplicate_pending_application_rejected(client: TestClient, driver_token: str):
    """TC-F1-15.2: Applying a second time while an application is pending returns HTTP 400."""
    payload = {
        "business_name": "First Energy Corp",
        "contact_email": "first@energy.com",
        "contact_phone": "+12345678921",
    }
    resp1 = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    assert resp1.status_code == 201

    # Second submission
    resp2 = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    assert resp2.status_code == 400
    assert "already have an operator onboarding application" in resp2.json()["detail"]


def test_operator_or_admin_cannot_apply(client: TestClient, operator_token: str, admin_token: str):
    """TC-F1-15.3: Users who are already Operators or Admins cannot submit onboarding applications."""
    payload = {
        "business_name": "Invalid Request Inc",
        "contact_email": "invalid@request.com",
        "contact_phone": "+12345678923",
    }
    # Operator attempt
    resp_op = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {operator_token}"},
        json=payload,
    )
    assert resp_op.status_code == 400

    # Admin attempt
    resp_admin = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {admin_token}"},
        json=payload,
    )
    assert resp_admin.status_code == 400


def test_invalid_application_payload_rejected(client: TestClient, driver_token: str):
    """TC-F1-15.4: Missing or invalid fields (e.g. blank name, bad phone) return 422."""
    # Empty business name
    resp1 = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json={
            "business_name": " ",
            "contact_email": "valid@email.com",
            "contact_phone": "+12345678921",
        },
    )
    assert resp1.status_code == 422

    # Malformed phone
    resp2 = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json={
            "business_name": "Valid Name",
            "contact_email": "valid@email.com",
            "contact_phone": "123",
        },
    )
    assert resp2.status_code == 422


def test_driver_views_own_application_and_cross_driver_blocked(
    client: TestClient,
    driver_token: str,
    second_driver_token: str,
    db_session: Session,
    test_driver: User,
):
    """TC-F1-15.5: Drivers can view own application status; foreign driver access is denied (403)."""
    payload = {
        "business_name": "Private Grid Ltd",
        "contact_email": "private@grid.com",
        "contact_phone": "+12345678921",
    }
    resp_create = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    assert resp_create.status_code == 201
    app_id = resp_create.json()["id"]

    # Driver checks status
    resp_status = client.get(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp_status.status_code == 200
    assert resp_status.json()["id"] == app_id

    # Second driver tries to access specific application ID -> 403 Forbidden
    resp_foreign = client.get(
        f"/api/v1/accounts/operator-onboarding/{app_id}",
        headers={"Authorization": f"Bearer {second_driver_token}"},
    )
    assert resp_foreign.status_code == 403


def test_admin_approve_operator_application(
    client: TestClient,
    admin_token: str,
    driver_token: str,
    db_session: Session,
    test_driver: User,
    test_admin: User,
):
    """TC-F1-15.6: Admin approves application; role is promoted to operator and audit logs are recorded."""
    payload = {
        "business_name": "Approved EV Network",
        "contact_email": "approved@ev.com",
        "contact_phone": "+12345678921",
    }
    resp_create = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    app_id = resp_create.json()["id"]

    # Admin approves via admin endpoint
    resp_approve = client.post(
        f"/api/v1/admin/operator-applications/{app_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_approve.status_code == 200
    app_data = resp_approve.json()
    assert app_data["status"] == "APPROVED"
    assert app_data["reviewed_by_admin_id"] == test_admin.id

    # Verify applicant role is promoted to OPERATOR
    db_session.refresh(test_driver)
    assert test_driver.role == UserRole.OPERATOR
    assert test_driver.operator_organization == "Approved EV Network"

    # Verify audit logs (REQ-F1-14)
    audit_approval = db_session.query(AuditLog).filter(
        AuditLog.user_id == test_admin.id,
        AuditLog.action == "OPERATOR_APPLICATION_APPROVED",
    ).first()
    assert audit_approval is not None

    audit_role = db_session.query(AuditLog).filter(
        AuditLog.user_id == test_admin.id,
        AuditLog.action == "ROLE_CHANGED",
    ).first()
    assert audit_role is not None

    # Cannot approve again -> 400 Bad Request
    resp_reapprove = client.post(
        f"/api/v1/admin/operator-applications/{app_id}/approve",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_reapprove.status_code == 400


def test_admin_reject_operator_application_with_reason(
    client: TestClient,
    admin_token: str,
    driver_token: str,
    db_session: Session,
    test_driver: User,
    test_admin: User,
):
    """TC-F1-15.7: Admin rejects application with a recorded reason; audit log is written."""
    payload = {
        "business_name": "Rejected Station Org",
        "contact_email": "reject@biz.com",
        "contact_phone": "+12345678921",
    }
    resp_create = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json=payload,
    )
    app_id = resp_create.json()["id"]

    # Rejection without sufficient reason fails (validation)
    resp_bad = client.post(
        f"/api/v1/accounts/operator-onboarding/{app_id}/reject",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "bad"},
    )
    assert resp_bad.status_code == 422

    # Valid rejection via accounts route (SW Architecture Page 5)
    resp_reject = client.post(
        f"/api/v1/accounts/operator-onboarding/{app_id}/reject",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"reason": "Business registration documents could not be verified."},
    )
    assert resp_reject.status_code == 200
    data = resp_reject.json()
    assert data["status"] == "REJECTED"
    assert data["rejection_reason"] == "Business registration documents could not be verified."

    # User role remains DRIVER
    db_session.refresh(test_driver)
    assert test_driver.role == UserRole.DRIVER

    # Audit log entry created
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == test_admin.id,
        AuditLog.action == "OPERATOR_APPLICATION_REJECTED",
    ).first()
    assert audit is not None
    assert "Business registration documents" in audit.details


def test_non_admin_cannot_approve_or_reject(
    client: TestClient,
    driver_token: str,
    second_driver_token: str,
):
    """TC-F1-15.8: Regular driver cannot approve or reject applications (403 Forbidden)."""
    resp_create = client.post(
        "/api/v1/accounts/operator-onboarding",
        headers={"Authorization": f"Bearer {driver_token}"},
        json={
            "business_name": "Test Net",
            "contact_email": "t@net.com",
            "contact_phone": "+12345678921",
        },
    )
    app_id = resp_create.json()["id"]

    # Driver tries to approve own or other app
    resp_app = client.post(
        f"/api/v1/accounts/operator-onboarding/{app_id}/approve",
        headers={"Authorization": f"Bearer {second_driver_token}"},
    )
    assert resp_app.status_code == 403

    resp_rej = client.post(
        f"/api/v1/accounts/operator-onboarding/{app_id}/reject",
        headers={"Authorization": f"Bearer {second_driver_token}"},
        json={"reason": "Unauthorized attempt to reject"},
    )
    assert resp_rej.status_code == 403
