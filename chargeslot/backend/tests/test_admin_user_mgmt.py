"""
Tests for Admin User Management
Requirement: REQ-F1-13, REQ-F1-14
Story ID: CS19-013
Test Case ID: TC-F1-13
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        name="Chief Admin",
        email="chief.admin@example.com",
        phone="+12345678990",
        hashed_password=hash_password("AdminSecure123!"),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Dan Driver",
        email="dan.driver@example.com",
        phone="+12345678991",
        hashed_password=hash_password("Password123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(driver)
    db_session.commit()
    db_session.refresh(driver)
    return driver


@pytest.fixture
def operator_user(db_session: Session) -> User:
    operator = User(
        name="Olivia Operator",
        email="olivia.op@example.com",
        phone="+12345678992",
        hashed_password=hash_password("Password123!"),
        role=UserRole.OPERATOR,
        operator_organization="ChargeNet Solutions",
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


# =========================================================================
# TC-F1-13: Access Control & Permissions for Admin Endpoints
# =========================================================================

def test_unauthorized_access_denied(client: TestClient, driver_user: User, operator_user: User):
    """TC-F1-13-01: Non-admins cannot access admin user management routes."""
    # No token
    res_no_auth = client.get("/api/v1/admin/users")
    assert res_no_auth.status_code == 401

    # Driver token -> 403
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}
    res_driver = client.get("/api/v1/admin/users", headers=driver_headers)
    assert res_driver.status_code == 403
    assert "Insufficient permissions" in res_driver.json()["detail"]

    # Operator token -> 403
    op_headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    res_op = client.get("/api/v1/admin/users", headers=op_headers)
    assert res_op.status_code == 403

    # Architecture route with driver token
    res_arch = client.get("/api/v1/accounts/admin-user-management", headers=driver_headers)
    assert res_arch.status_code == 403


# =========================================================================
# TC-F1-13: List & Search Users with Filters & Pagination
# =========================================================================

def test_list_and_search_users(
    client: TestClient, admin_user: User, driver_user: User, operator_user: User
):
    """TC-F1-13-02: Admin lists and searches users with filters and pagination."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # List all users
    res = client.get("/api/v1/admin/users", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 3
    assert len(data["items"]) >= 3

    # Search by name query
    res_search = client.get("/api/v1/admin/users?q=Olivia", headers=headers)
    assert res_search.status_code == 200
    search_data = res_search.json()
    assert search_data["total"] == 1
    assert search_data["items"][0]["email"] == operator_user.email

    # Filter by role
    res_role = client.get("/api/v1/admin/users?role=operator", headers=headers)
    assert res_role.status_code == 200
    assert all(item["role"] == "operator" for item in res_role.json()["items"])

    # Filter by is_active
    res_active = client.get("/api/v1/admin/users?is_active=true", headers=headers)
    assert res_active.status_code == 200
    assert res_active.json()["total"] >= 3

    # Pagination test
    res_page = client.get("/api/v1/admin/users?page=1&page_size=2", headers=headers)
    assert res_page.status_code == 200
    assert len(res_page.json()["items"]) == 2
    assert res_page.json()["page"] == 1


# =========================================================================
# TC-F1-13: Admin Creates User Account
# =========================================================================

def test_admin_create_user(client: TestClient, admin_user: User, db_session: Session):
    """TC-F1-13-03: Admin creates user account with audit entry."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    payload = {
        "name": "New Station Operator",
        "email": "new.operator@chargeslot.com",
        "phone": "+19998887777",
        "password": "SecurePassword123!",
        "role": "operator",
        "is_verified": True,
        "operator_organization": "GreenVolt Power",
    }
    res = client.post("/api/v1/admin/users", json=payload, headers=headers)
    assert res.status_code == 201
    user_data = res.json()
    assert user_data["email"] == payload["email"]
    assert user_data["role"] == "operator"
    assert user_data["is_verified"] is True
    assert user_data["is_active"] is True

    # Audit log check
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "ADMIN_CREATE_USER",
        AuditLog.user_id == admin_user.id
    ).first()
    assert audit is not None
    assert payload["email"] in audit.details

    # Duplicate email rejected
    res_dup = client.post("/api/v1/admin/users", json=payload, headers=headers)
    assert res_dup.status_code == 409
    assert "email address already exists" in res_dup.json()["detail"]

    # Duplicate phone rejected
    payload2 = {
        "name": "Another User",
        "email": "unique.email@example.com",
        "phone": "+19998887777",  # same phone
        "password": "SecurePassword123!",
        "role": "driver",
    }
    res_dup_phone = client.post("/api/v1/admin/users", json=payload2, headers=headers)
    assert res_dup_phone.status_code == 409
    assert "phone number already exists" in res_dup_phone.json()["detail"]


# =========================================================================
# TC-F1-13: Admin Views & Updates User (Deactivate, Reactivate, Change Role)
# =========================================================================

def test_get_user_details(client: TestClient, admin_user: User, driver_user: User):
    """TC-F1-13-04: Admin views single user details."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    res = client.get(f"/api/v1/admin/users/{driver_user.id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["id"] == driver_user.id
    assert res.json()["email"] == driver_user.email

    res_not_found = client.get("/api/v1/admin/users/999999", headers=headers)
    assert res_not_found.status_code == 404


def test_admin_change_role_and_audit(
    client: TestClient, admin_user: User, driver_user: User, db_session: Session
):
    """TC-F1-13-05: Admin changes user role and records audit entry (REQ-F1-13, REQ-F1-14)."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    update_payload = {"name": "Daniel Driver Updated", "role": "operator", "operator_organization": "SuperCharge Inc"}
    res = client.patch(f"/api/v1/admin/users/{driver_user.id}", json=update_payload, headers=headers)
    assert res.status_code == 200
    assert res.json()["name"] == "Daniel Driver Updated"
    assert res.json()["role"] == "operator"


    # Verify audit log (REQ-F1-14)
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "ROLE_CHANGED",
        AuditLog.user_id == admin_user.id
    ).first()
    assert audit is not None
    assert "from driver to operator" in audit.details


def test_admin_deactivate_and_reactivate_user(
    client: TestClient, admin_user: User, driver_user: User, db_session: Session
):
    """TC-F1-13-06: Admin deactivates and reactivates user account with audit log."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # Deactivate
    res_deact = client.post(f"/api/v1/admin/users/{driver_user.id}/deactivate", headers=headers)
    assert res_deact.status_code == 200
    assert res_deact.json()["is_active"] is False

    audit_deact = db_session.query(AuditLog).filter(
        AuditLog.action == "ACCOUNT_DEACTIVATED",
        AuditLog.user_id == admin_user.id
    ).first()
    assert audit_deact is not None
    assert driver_user.email in audit_deact.details

    # Deactivated user cannot access protected endpoints
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}
    res_access = client.get("/api/v1/auth/me", headers=driver_headers)
    assert res_access.status_code == 403
    assert "Inactive user account" in res_access.json()["detail"]

    # Reactivate
    res_react = client.post(f"/api/v1/admin/users/{driver_user.id}/reactivate", headers=headers)
    assert res_react.status_code == 200
    assert res_react.json()["is_active"] is True

    audit_react = db_session.query(AuditLog).filter(
        AuditLog.action == "ACCOUNT_REACTIVATED",
        AuditLog.user_id == admin_user.id
    ).first()
    assert audit_react is not None


def test_admin_cannot_deactivate_or_demote_self(client: TestClient, admin_user: User):
    """TC-F1-13-07: Safety constraint: Administrator cannot deactivate or demote own account."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # Attempt self-deactivation
    res_self_deact = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        json={"is_active": False},
        headers=headers,
    )
    assert res_self_deact.status_code == 400
    assert "cannot deactivate their own account" in res_self_deact.json()["detail"]

    # Attempt self-demotion
    res_self_demote = client.patch(
        f"/api/v1/admin/users/{admin_user.id}",
        json={"role": "driver"},
        headers=headers,
    )
    assert res_self_demote.status_code == 400
    assert "cannot demote their own admin role" in res_self_demote.json()["detail"]


# =========================================================================
# TC-F1-13: Software Architecture Page 5 Route: /accounts/admin-user-management
# =========================================================================

def test_architecture_admin_user_management_endpoints(
    client: TestClient, admin_user: User, driver_user: User
):
    """TC-F1-13-08: Tests PATCH & GET /api/v1/accounts/admin-user-management per architecture spec."""
    headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # GET list
    res_get = client.get("/api/v1/accounts/admin-user-management?q=Dan", headers=headers)
    assert res_get.status_code == 200
    assert res_get.json()["total"] == 1
    assert res_get.json()["items"][0]["email"] == driver_user.email

    # PATCH status & role
    patch_payload = {
        "user_id": driver_user.id,
        "role": "operator",
        "is_active": True,
        "is_verified": True,
    }
    res_patch = client.patch(
        "/api/v1/accounts/admin-user-management",
        json=patch_payload,
        headers=headers,
    )
    assert res_patch.status_code == 200
    updated_user = res_patch.json()
    assert updated_user["id"] == driver_user.id
    assert updated_user["role"] == "operator"
    assert updated_user["is_verified"] is True
