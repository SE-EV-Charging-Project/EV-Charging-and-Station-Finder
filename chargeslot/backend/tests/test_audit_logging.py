"""
Tests for System Audit Logging (Audit User Actions)
Requirement: REQ-F1-14
Story ID: CS19-014
Test Case ID: TC-F1-14
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.audit import AuditLog
from app.services.audit_service import AuditService
from app.utils.security import hash_password, create_access_token


@pytest.fixture
def test_admin(db_session: Session) -> User:
    admin = User(
        name="Super Admin",
        email="audit.admin@example.com",
        phone="+12345678910",
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
        name="Dave Driver",
        email="audit.driver@example.com",
        phone="+12345678911",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(driver)
    db_session.commit()
    db_session.refresh(driver)
    return driver


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


def test_audit_service_log_and_query(db_session: Session, test_admin: User):
    """TC-F1-14.1: Direct service writes and queries audit logs correctly."""
    log1 = AuditService.log_action(
        db=db_session,
        user_id=test_admin.id,
        action="TEST_ACTION_ONE",
        resource="test_resource",
        details="Details for test action one",
        ip_address="127.0.0.1",
    )
    assert log1.id is not None
    assert log1.action == "TEST_ACTION_ONE"

    results, total = AuditService.list_logs(db=db_session, action="TEST_ACTION_ONE")
    assert total == 1
    assert len(results) == 1
    assert results[0]["action"] == "TEST_ACTION_ONE"
    assert results[0]["user_email"] == test_admin.email
    assert results[0]["resource"] == "test_resource"


def test_admin_audit_logs_endpoint_success(client: TestClient, admin_token: str, db_session: Session, test_admin: User):
    """TC-F1-14.2: Administrator can query audit logs via GET /api/v1/admin/audit-logs."""
    AuditService.log_action(
        db=db_session,
        user_id=test_admin.id,
        action="SYSTEM_BOOT",
        resource="system",
        details="System initialization",
    )

    resp = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert data["total"] >= 1
    actions = [item["action"] for item in data["items"]]
    assert "SYSTEM_BOOT" in actions


def test_architecture_audit_user_actions_endpoint(client: TestClient, admin_token: str, db_session: Session, test_admin: User):
    """TC-F1-14.3: Proposed route GET /api/v1/accounts/audit-user-actions returns logs for admin."""
    AuditService.log_action(
        db=db_session,
        user_id=test_admin.id,
        action="CONFIG_UPDATE",
        resource="config",
        details="Updated rate limits",
    )

    resp = client.get(
        "/api/v1/accounts/audit-user-actions?action=CONFIG_UPDATE",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["items"][0]["action"] == "CONFIG_UPDATE"
    assert data["items"][0]["user_email"] == test_admin.email


def test_driver_denied_access_to_audit_logs(client: TestClient, driver_token: str):
    """TC-F1-14.4: Driver role is denied access (HTTP 403 Forbidden) to audit logs."""
    resp1 = client.get(
        "/api/v1/admin/audit-logs",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp1.status_code == 403

    resp2 = client.get(
        "/api/v1/accounts/audit-user-actions",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp2.status_code == 403


def test_unauthenticated_denied_access_to_audit_logs(client: TestClient):
    """TC-F1-14.5: Unauthenticated request is rejected with HTTP 401 Unauthorized."""
    resp = client.get("/api/v1/admin/audit-logs")
    assert resp.status_code == 401


def test_audit_log_filters_by_user_and_resource(client: TestClient, admin_token: str, db_session: Session, test_admin: User, test_driver: User):
    """TC-F1-14.6: Audit logs can be filtered by user_id and resource."""
    AuditService.log_action(
        db=db_session,
        user_id=test_admin.id,
        action="ADMIN_SPECIFIC",
        resource="users",
        details="Admin modified user",
    )
    AuditService.log_action(
        db=db_session,
        user_id=test_driver.id,
        action="DRIVER_SPECIFIC",
        resource="bookings",
        details="Driver booking slot",
    )

    # Filter by user_id
    resp = client.get(
        f"/api/v1/admin/audit-logs?user_id={test_driver.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert all(item["user_id"] == test_driver.id for item in data["items"])
    assert any(item["action"] == "DRIVER_SPECIFIC" for item in data["items"])

    # Filter by resource
    resp_res = client.get(
        "/api/v1/admin/audit-logs?resource=users",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp_res.status_code == 200
    data_res = resp_res.json()
    assert all(item["resource"] == "users" for item in data_res["items"])


def test_audit_log_pagination(client: TestClient, admin_token: str, db_session: Session, test_admin: User):
    """TC-F1-14.7: Verifies pagination (page, page_size) on audit log endpoint."""
    for i in range(15):
        AuditService.log_action(
            db=db_session,
            user_id=test_admin.id,
            action=f"BATCH_ACTION_{i}",
            resource="batch",
        )

    resp = client.get(
        "/api/v1/admin/audit-logs?resource=batch&page=1&page_size=5",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 15
    assert len(data["items"]) == 5
    assert data["page"] == 1
    assert data["page_size"] == 5
