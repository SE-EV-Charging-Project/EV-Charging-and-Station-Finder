"""
Tests for Server-side Role-Based Access Control (RBAC)
Requirement: REQ-F1-11
Story ID: CS19-011
Test Case ID: TC-F1-11
"""

import pytest
from datetime import timedelta
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user,
    get_current_active_user,
    require_roles,
    RequireRoles,
    require_admin,
    require_operator,
    require_driver,
)
from app.models.user import User, UserRole
from app.utils.security import (
    hash_password,
    create_access_token,
    create_refresh_token,
)


@pytest.fixture
def test_driver(db_session: Session) -> User:
    driver = User(
        name="Alice Driver",
        email="alice.driver@example.com",
        phone="+12345678901",
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
def test_operator(db_session: Session) -> User:
    operator = User(
        name="Bob Operator",
        email="bob.operator@example.com",
        phone="+12345678902",
        hashed_password=hash_password("Password123!"),
        role=UserRole.OPERATOR,
        operator_organization="VoltGrid Charging Co",
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    db_session.refresh(operator)
    return operator


@pytest.fixture
def test_admin(db_session: Session) -> User:
    admin = User(
        name="Charlie Admin",
        email="charlie.admin@example.com",
        phone="+12345678903",
        hashed_password=hash_password("Password123!"),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    db_session.refresh(admin)
    return admin


@pytest.fixture
def test_inactive_user(db_session: Session) -> User:
    inactive = User(
        name="Inactive User",
        email="inactive.user@example.com",
        phone="+12345678904",
        hashed_password=hash_password("Password123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()
    db_session.refresh(inactive)
    return inactive


def make_token(user: User, token_type: str = "access", expires_delta: timedelta | None = None) -> str:
    data = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role)
    }
    if token_type == "access":
        return create_access_token(data, expires_delta=expires_delta)
    return create_refresh_token(data, expires_delta=expires_delta)


# =========================================================================
# TC-F1-11: Authentication & Token Validation for Protected Endpoints
# =========================================================================

def test_protected_endpoint_without_token_returns_401(client: TestClient):
    """TC-F1-11-01: Accessing protected endpoints without an Authorization header must return 401."""
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert "Not authenticated" in res.json()["detail"]

    res_rbac = client.get("/api/v1/accounts/server-side-rbac")
    assert res_rbac.status_code == 401


def test_protected_endpoint_with_invalid_or_expired_token_returns_401(client: TestClient, test_driver: User):
    """TC-F1-11-02: Tampered or expired JWT token must be rejected with 401."""
    # Tampered token
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.token.payload"}
    )
    assert res.status_code == 401
    assert "Could not validate credentials" in res.json()["detail"]

    # Expired token
    expired_token = make_token(test_driver, expires_delta=timedelta(seconds=-10))
    res_exp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert res_exp.status_code == 401


def test_protected_endpoint_with_refresh_token_returns_401(client: TestClient, test_driver: User):
    """TC-F1-11-03: Refresh tokens cannot be used as Bearer access tokens on protected endpoints."""
    refresh_tok = make_token(test_driver, token_type="refresh")
    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refresh_tok}"}
    )
    assert res.status_code == 401
    assert "Invalid token type" in res.json()["detail"]


def test_protected_endpoint_with_nonexistent_or_malformed_user_id(client: TestClient):
    """TC-F1-11-04: Token with unknown or non-numeric subject must return 401."""
    # Unknown user id
    token_unknown = create_access_token({"sub": "999999", "role": "driver"})
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_unknown}"})
    assert res.status_code == 401
    assert "User not found" in res.json()["detail"]

    # Missing subject
    token_no_sub = create_access_token({"role": "driver"})
    res2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_no_sub}"})
    assert res2.status_code == 401
    assert "missing subject" in res2.json()["detail"]

    # Non-integer subject
    token_bad_sub = create_access_token({"sub": "not_an_int", "role": "driver"})
    res3 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token_bad_sub}"})
    assert res3.status_code == 401
    assert "invalid subject" in res3.json()["detail"]


def test_protected_endpoint_with_valid_token_succeeds(client: TestClient, test_driver: User):
    """TC-F1-11-05: Authenticated caller successfully accesses GET /auth/me and /accounts/server-side-rbac."""
    token = make_token(test_driver)
    headers = {"Authorization": f"Bearer {token}"}

    res = client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == test_driver.id
    assert data["email"] == test_driver.email
    assert data["role"] == "driver"

    res_rbac = client.get("/api/v1/accounts/server-side-rbac", headers=headers)
    assert res_rbac.status_code == 200
    rbac_data = res_rbac.json()
    assert rbac_data["status"] == "authorized"
    assert rbac_data["role"] == "driver"


def test_inactive_user_cannot_access_protected_endpoint(client: TestClient, test_inactive_user: User):
    """TC-F1-11-06: Deactivated/inactive accounts must be denied access with 403 Forbidden."""
    token = make_token(test_inactive_user)
    res = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 403
    assert "Inactive user account" in res.json()["detail"]


# =========================================================================
# TC-F1-11: Role-Based Access Control (RBAC) Enforcement
# =========================================================================

def test_driver_cannot_access_admin_or_operator_endpoints(
    client: TestClient, test_driver: User
):
    """TC-F1-11-07: Driver must be denied access to operator and admin endpoints (403 Forbidden)."""
    token = make_token(test_driver)
    headers = {"Authorization": f"Bearer {token}"}

    # Driver -> Admin endpoint
    res_admin = client.get("/api/v1/accounts/server-side-rbac/admin", headers=headers)
    assert res_admin.status_code == 403
    assert "Insufficient permissions" in res_admin.json()["detail"]
    assert "admin" in res_admin.json()["detail"]

    # Driver -> Operator endpoint
    res_op = client.get("/api/v1/accounts/server-side-rbac/operator", headers=headers)
    assert res_op.status_code == 403
    assert "Insufficient permissions" in res_op.json()["detail"]

    # Driver -> Driver endpoint (allowed)
    res_driver = client.get("/api/v1/accounts/server-side-rbac/driver", headers=headers)
    assert res_driver.status_code == 200
    assert res_driver.json()["status"] == "authorized"


def test_operator_access_rules(
    client: TestClient, test_operator: User
):
    """TC-F1-11-08: Station Operator can access operator endpoint but is denied admin endpoints."""
    token = make_token(test_operator)
    headers = {"Authorization": f"Bearer {token}"}

    # Operator -> Operator endpoint
    res_op = client.get("/api/v1/accounts/server-side-rbac/operator", headers=headers)
    assert res_op.status_code == 200
    assert res_op.json()["role"] == "operator"

    # Operator -> Admin endpoint (forbidden)
    res_admin = client.get("/api/v1/accounts/server-side-rbac/admin", headers=headers)
    assert res_admin.status_code == 403
    assert "Insufficient permissions" in res_admin.json()["detail"]


def test_admin_has_unrestricted_access(
    client: TestClient, test_admin: User
):
    """TC-F1-11-09: Administrator has permission across admin, operator, and driver endpoints."""
    token = make_token(test_admin)
    headers = {"Authorization": f"Bearer {token}"}

    res_admin = client.get("/api/v1/accounts/server-side-rbac/admin", headers=headers)
    assert res_admin.status_code == 200
    assert res_admin.json()["role"] == "admin"

    res_op = client.get("/api/v1/accounts/server-side-rbac/operator", headers=headers)
    assert res_op.status_code == 200
    assert res_op.json()["role"] == "admin"

    res_driver = client.get("/api/v1/accounts/server-side-rbac/driver", headers=headers)
    assert res_driver.status_code == 200
    assert res_driver.json()["role"] == "admin"


def test_require_roles_dependency_unit(test_driver: User, test_admin: User):
    """TC-F1-11-10: Direct unit testing of RequireRoles dependency class."""
    admin_guard = require_roles(UserRole.ADMIN)
    # Admin allowed
    assert admin_guard(current_user=test_admin) == test_admin

    # Driver denied
    with pytest.raises(HTTPException) as exc_info:
        admin_guard(current_user=test_driver)
    assert exc_info.value.status_code == 403
    assert "Insufficient permissions" in exc_info.value.detail

    # get_current_active_user helper
    assert get_current_active_user(current_user=test_admin) == test_admin
