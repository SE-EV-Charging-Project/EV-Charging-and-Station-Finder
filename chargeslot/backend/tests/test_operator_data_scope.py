"""
Tests for Station Operator Data Scope
Requirement: REQ-F1-12
Story ID: CS19-012
Test Case ID: TC-F1-12
System Test Case ID: STC-F1-12
"""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.core.permissions import (
    enforce_operator_scope,
    scope_operator_query,
    authorize,
)
from app.utils.security import hash_password, create_access_token


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def operator_a(db_session: Session) -> User:
    op_a = User(
        name="Operator Alpha",
        email="operator.alpha@example.com",
        phone="+12345678931",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Alpha Power Network",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op_a)
    db_session.commit()
    db_session.refresh(op_a)
    return op_a


@pytest.fixture
def operator_b(db_session: Session) -> User:
    op_b = User(
        name="Operator Beta",
        email="operator.beta@example.com",
        phone="+12345678932",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Beta Charging Grid",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op_b)
    db_session.commit()
    db_session.refresh(op_b)
    return op_b


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        name="System Administrator",
        email="admin.scope@example.com",
        phone="+12345678933",
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
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Standard Driver",
        email="driver.scope@example.com",
        phone="+12345678934",
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
def inactive_operator(db_session: Session) -> User:
    inactive = User(
        name="Inactive Operator",
        email="inactive.op@example.com",
        phone="+12345678935",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Dead Grid",
        is_verified=True,
        is_active=False,
    )
    db_session.add(inactive)
    db_session.commit()
    db_session.refresh(inactive)
    return inactive


@pytest.fixture
def op_a_token(operator_a: User) -> str:
    return make_token(operator_a)


@pytest.fixture
def op_b_token(operator_b: User) -> str:
    return make_token(operator_b)


@pytest.fixture
def admin_token(admin_user: User) -> str:
    return make_token(admin_user)


@pytest.fixture
def driver_token(driver_user: User) -> str:
    return make_token(driver_user)


# ==============================================================================
# Endpoint Tests: GET /api/v1/accounts/operator-data-scope
# ==============================================================================

def test_operator_views_own_data_scope_profile(client: TestClient, op_a_token: str, operator_a: User):
    """TC-F1-12.1: Operator accesses GET /api/v1/accounts/operator-data-scope and receives scoped profile."""
    resp = client.get(
        "/api/v1/accounts/operator-data-scope",
        headers={"Authorization": f"Bearer {op_a_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["operator_id"] == operator_a.id
    assert data["operator_name"] == operator_a.name
    assert data["operator_organization"] == "Alpha Power Network"
    assert data["role"] == "operator"
    assert data["scope_type"] == "OWNED_RESOURCES_ONLY"
    assert "stations" in data["allowed_resources"]
    assert "chargers" in data["allowed_resources"]
    assert "tariffs" in data["allowed_resources"]
    assert "reports" in data["allowed_resources"]


def test_admin_receives_global_operator_scope(client: TestClient, admin_token: str, admin_user: User):
    """TC-F1-12.2: Administrator accesses GET /api/v1/accounts/operator-data-scope and receives global scope."""
    resp = client.get(
        "/api/v1/accounts/operator-data-scope",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["operator_id"] == admin_user.id
    assert data["role"] == "admin"
    assert data["scope_type"] == "GLOBAL"


def test_driver_denied_operator_data_scope_endpoint(client: TestClient, driver_token: str):
    """TC-F1-12.3: Driver is denied access (403 Forbidden) to operator data scope endpoint."""
    resp = client.get(
        "/api/v1/accounts/operator-data-scope",
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    assert resp.status_code == 403


def test_unauthenticated_denied_operator_data_scope(client: TestClient):
    """TC-F1-12.4: Unauthenticated request is rejected with 401 Unauthorized."""
    resp = client.get("/api/v1/accounts/operator-data-scope")
    assert resp.status_code == 401


# ==============================================================================
# Endpoint Tests: POST /api/v1/accounts/operator-data-scope/verify-access
# ==============================================================================

def test_operator_authorized_for_own_station_resource(client: TestClient, op_a_token: str, operator_a: User):
    """TC-F1-12.5: Operator successfully accesses a station/resource they own."""
    resp = client.post(
        "/api/v1/accounts/operator-data-scope/verify-access",
        headers={"Authorization": f"Bearer {op_a_token}"},
        json={"resource_operator_id": operator_a.id, "resource_type": "station"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["has_access"] is True
    assert data["operator_id"] == operator_a.id
    assert data["resource_operator_id"] == operator_a.id


def test_operator_forbidden_from_foreign_station_resource(
    client: TestClient,
    op_a_token: str,
    operator_a: User,
    operator_b: User,
):
    """TC-F1-12.6: Operator A attempting to access Operator B's station/resource is rejected (403 Forbidden)."""
    resp = client.post(
        "/api/v1/accounts/operator-data-scope/verify-access",
        headers={"Authorization": f"Bearer {op_a_token}"},
        json={"resource_operator_id": operator_b.id, "resource_type": "station"},
    )
    assert resp.status_code == 403
    assert "restricted to their own stations, chargers, tariffs, and reports" in resp.json()["detail"]


def test_admin_authorized_for_any_operator_resource(
    client: TestClient,
    admin_token: str,
    operator_a: User,
    operator_b: User,
):
    """TC-F1-12.7: Administrator has global scope and can access any operator's resources."""
    resp_a = client.post(
        "/api/v1/accounts/operator-data-scope/verify-access",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"resource_operator_id": operator_a.id, "resource_type": "station"},
    )
    assert resp_a.status_code == 200
    assert resp_a.json()["has_access"] is True

    resp_b = client.post(
        "/api/v1/accounts/operator-data-scope/verify-access",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"resource_operator_id": operator_b.id, "resource_type": "tariff"},
    )
    assert resp_b.status_code == 200
    assert resp_b.json()["has_access"] is True


def test_driver_denied_verify_access_endpoint(client: TestClient, driver_token: str, operator_a: User):
    """TC-F1-12.8: Driver calling verify-access is denied with HTTP 403 Forbidden."""
    resp = client.post(
        "/api/v1/accounts/operator-data-scope/verify-access",
        headers={"Authorization": f"Bearer {driver_token}"},
        json={"resource_operator_id": operator_a.id, "resource_type": "station"},
    )
    assert resp.status_code == 403


# ==============================================================================
# Unit Tests for Helper Functions in app/core/permissions.py
# ==============================================================================

def test_enforce_operator_scope_unit(operator_a: User, operator_b: User, admin_user: User, driver_user: User):
    """TC-F1-12.9: Direct unit test for enforce_operator_scope helper."""
    # Operator on own resource
    assert enforce_operator_scope(operator_a, operator_a.id) is True

    # Admin on any resource
    assert enforce_operator_scope(admin_user, operator_a.id) is True
    assert enforce_operator_scope(admin_user, operator_b.id) is True

    # Operator on foreign resource -> 403
    with pytest.raises(HTTPException) as exc_info:
        enforce_operator_scope(operator_a, operator_b.id)
    assert exc_info.value.status_code == 403
    assert "restricted to their own stations" in exc_info.value.detail

    # Driver -> 403
    with pytest.raises(HTTPException) as exc_driver:
        enforce_operator_scope(driver_user, operator_a.id)
    assert exc_driver.value.status_code == 403


def test_scope_operator_query_unit(db_session: Session, operator_a: User, operator_b: User, admin_user: User, driver_user: User):
    """TC-F1-12.10: Direct unit test for scope_operator_query SQLAlchemy helper."""
    from app.models.operator_application import OperatorApplication, ApplicationStatus

    app_a = OperatorApplication(
        user_id=operator_a.id,
        business_name="Alpha Station Ltd",
        contact_email="alpha@test.com",
        contact_phone="+12345678901",
        status=ApplicationStatus.APPROVED,
    )
    app_b = OperatorApplication(
        user_id=operator_b.id,
        business_name="Beta Station Ltd",
        contact_email="beta@test.com",
        contact_phone="+12345678902",
        status=ApplicationStatus.APPROVED,
    )
    db_session.add_all([app_a, app_b])
    db_session.commit()

    base_query = db_session.query(OperatorApplication)

    # Admin: sees both applications (global scope)
    admin_q = scope_operator_query(base_query, OperatorApplication, admin_user, operator_id_attr="user_id")
    assert len(admin_q.all()) == 2

    # Operator A: sees only Operator A's application
    op_a_q = scope_operator_query(base_query, OperatorApplication, operator_a, operator_id_attr="user_id")
    results = op_a_q.all()
    assert len(results) == 1
    assert results[0].user_id == operator_a.id

    # Driver: raises 403 Forbidden
    with pytest.raises(HTTPException) as exc_q:
        scope_operator_query(base_query, OperatorApplication, driver_user, operator_id_attr="user_id")
    assert exc_q.value.status_code == 403


def test_authorize_internal_contract_unit(
    operator_a: User,
    operator_b: User,
    admin_user: User,
    driver_user: User,
    inactive_operator: User,
):
    """TC-F1-12.11: Direct unit test for SW Architecture §11 authorize() contract."""
    # Admin is authorized for all actions
    assert authorize(admin_user, action="manage_station", resource_id=10, resource_owner_id=operator_a.id) is True

    # Operator authorized for own station
    assert authorize(operator_a, action="manage_station", resource_id=10, resource_owner_id=operator_a.id) is True
    assert authorize(operator_a, action="view_operator_reports", resource_owner_id=operator_a.id) is True

    # Operator denied for foreign station
    with pytest.raises(HTTPException) as exc_foreign:
        authorize(operator_a, action="manage_station", resource_id=20, resource_owner_id=operator_b.id)
    assert exc_foreign.value.status_code == 403

    # Driver denied operator action
    with pytest.raises(HTTPException) as exc_driver:
        authorize(driver_user, action="manage_station", resource_id=10, resource_owner_id=driver_user.id)
    assert exc_driver.value.status_code == 403

    # Inactive principal denied
    with pytest.raises(HTTPException) as exc_inactive:
        authorize(inactive_operator, action="view_station", resource_id=10)
    assert exc_inactive.value.status_code == 403
    assert "Inactive user account" in exc_inactive.value.detail
