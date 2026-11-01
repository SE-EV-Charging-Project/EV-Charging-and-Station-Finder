"""
Unit and Integration Tests for EV Vehicle Registration.
Requirement: REQ-F1-18
Story ID: CS19-018
Test Case ID: TC-F1-18
System Test Case ID: STC-F1-18
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Morgan Driver",
        email="morgan.driver@example.com",
        phone="+15556667771",
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
def other_driver(db_session: Session) -> User:
    driver = User(
        name="Jordan Driver",
        email="jordan.driver@example.com",
        phone="+15556667772",
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
def operator_user(db_session: Session) -> User:
    operator = User(
        name="Sam Operator",
        email="sam.operator@example.com",
        phone="+15556667773",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    db_session.refresh(operator)
    return operator


# ==============================================================================
# CS19-018 / REQ-F1-18: Add Vehicle
# ==============================================================================

def test_add_vehicle_success_rest_endpoint(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-18-01 / STC-F1-18-01: Driver successfully adds a vehicle via POST /api/v1/vehicles."""
    token = make_token(driver_user)
    payload = {
        "make": "Tesla",
        "model": "Model 3 Long Range",
        "battery_kwh": 75.0,
        "connector_type": "CCS2",
        "max_ac_kw": 11.0,
        "max_dc_kw": 250.0,
        "consumption_kwh_100km": 16.0,
        "registration_no": "KA01EV9999",
        "is_default": True,
    }
    resp = client.post(
        "/api/v1/vehicles",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] is not None
    assert data["user_id"] == driver_user.id
    assert data["make"] == "Tesla"
    assert data["model"] == "Model 3 Long Range"
    assert data["battery_kwh"] == 75.0
    assert data["connector_type"] == "CCS2"
    assert data["max_ac_kw"] == 11.0
    assert data["max_dc_kw"] == 250.0
    assert data["consumption_kwh_100km"] == 16.0
    assert data["registration_no"] == "KA01EV9999"
    assert data["is_default"] is True

    # Check database persistence
    saved_vehicle = db_session.query(Vehicle).filter(Vehicle.id == data["id"]).first()
    assert saved_vehicle is not None
    assert saved_vehicle.user_id == driver_user.id
    assert saved_vehicle.make == "Tesla"


def test_add_vehicle_architecture_route(client: TestClient, driver_user: User):
    """TC-F1-18-02: Verifies SW Architecture route POST /api/v1/accounts/vehicle-crud."""
    token = make_token(driver_user)
    payload = {
        "make": "Hyundai",
        "model": "Ioniq 5",
        "battery_kwh": 72.6,
        "connector_type": "CCS2",
        "max_ac_kw": 10.5,
        "max_dc_kw": 220.0,
        "consumption_kwh_100km": 17.5,
        "registration_no": "DL02EV1234",
    }
    resp = client.post(
        "/api/v1/accounts/vehicle-crud",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["make"] == "Hyundai"
    assert data["model"] == "Ioniq 5"
    assert data["is_default"] is True  # First vehicle becomes default automatically


def test_list_driver_vehicles(client: TestClient, driver_user: User):
    """TC-F1-18-03: Lists all vehicles registered to the driver."""
    token = make_token(driver_user)
    client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tata",
            "model": "Nexon EV Max",
            "battery_kwh": 40.5,
            "connector_type": "CCS2",
            "max_ac_kw": 7.2,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    resp = client.get(
        "/api/v1/vehicles",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(v["make"] == "Tata" for v in data["items"])

    # Test architecture route list
    resp_arch = client.get(
        "/api/v1/accounts/vehicle-crud",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_arch.status_code == 200
    assert resp_arch.json()["total"] == data["total"]


def test_get_vehicle_by_id(client: TestClient, driver_user: User):
    """TC-F1-18-04: Retrieves single vehicle by ID."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "MG",
            "model": "ZS EV",
            "battery_kwh": 50.3,
            "connector_type": "CCS2",
            "max_ac_kw": 7.4,
            "max_dc_kw": 75.0,
            "consumption_kwh_100km": 16.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    resp = client.get(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == veh_id
    assert resp.json()["model"] == "ZS EV"


def test_add_vehicle_creates_audit_log(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-18-05: Verifies that adding a vehicle writes an immutable audit log entry."""
    token = make_token(driver_user)
    resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Nissan",
            "model": "Leaf",
            "battery_kwh": 40.0,
            "connector_type": "CHAdeMO",
            "max_ac_kw": 6.6,
            "max_dc_kw": 46.0,
            "consumption_kwh_100km": 17.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver_user.id,
            AuditLog.action == "VEHICLE_ADDED",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_entry is not None
    assert "Nissan Leaf" in audit_entry.details


def test_add_vehicle_ac_only_supported(client: TestClient, driver_user: User):
    """TC-F1-18-06: Verifies max_dc_kw=0 is allowed for AC-only vehicles."""
    token = make_token(driver_user)
    resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Renault",
            "model": "Zoe",
            "battery_kwh": 52.0,
            "connector_type": "Type 2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 0.0,
            "consumption_kwh_100km": 17.2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 201
    assert resp.json()["max_dc_kw"] == 0.0


def test_add_vehicle_unauthenticated_rejected(client: TestClient):
    """TC-F1-18-07: Verifies unauthenticated vehicle creation is rejected with 401."""
    resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tesla",
            "model": "Model 3",
            "battery_kwh": 60.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 170.0,
            "consumption_kwh_100km": 15.0,
        },
    )
    assert resp.status_code == 401


def test_add_vehicle_operator_forbidden(client: TestClient, operator_user: User):
    """TC-F1-18-08: Station Operators are forbidden from registering driver vehicles."""
    token = make_token(operator_user)
    resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tesla",
            "model": "Model Y",
            "battery_kwh": 75.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 250.0,
            "consumption_kwh_100km": 16.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


def test_validation_rejects_blank_make_or_model(client: TestClient, driver_user: User):
    """TC-F1-18-09: Rejects empty or whitespace-only make or model."""
    token = make_token(driver_user)
    for bad_make in ["", "   "]:
        resp = client.post(
            "/api/v1/vehicles",
            json={
                "make": bad_make,
                "model": "Valid Model",
                "battery_kwh": 50.0,
                "connector_type": "CCS2",
                "max_ac_kw": 11.0,
                "max_dc_kw": 50.0,
                "consumption_kwh_100km": 15.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 422


def test_validation_rejects_out_of_range_battery_capacity(client: TestClient, driver_user: User):
    """TC-F1-18-10: Battery capacity must be between 5.0 and 250.0 kWh (Appendix B.3)."""
    token = make_token(driver_user)
    # Below 5.0 kWh
    resp_low = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Micro",
            "model": "EV",
            "battery_kwh": 4.9,
            "connector_type": "Type 2",
            "max_ac_kw": 3.3,
            "max_dc_kw": 0.0,
            "consumption_kwh_100km": 10.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 250.0 kWh
    resp_high = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Heavy",
            "model": "Semi",
            "battery_kwh": 250.1,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 350.0,
            "consumption_kwh_100km": 40.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_rejects_out_of_range_max_ac_power(client: TestClient, driver_user: User):
    """TC-F1-18-11: Max AC charging power must be between 1.0 and 50.0 kW (Appendix B.3)."""
    token = make_token(driver_user)
    # Below 1.0 kW
    resp_low = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 30.0,
            "connector_type": "Type 2",
            "max_ac_kw": 0.5,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 50.0 kW
    resp_high = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 30.0,
            "connector_type": "Type 2",
            "max_ac_kw": 50.5,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_rejects_out_of_range_max_dc_power(client: TestClient, driver_user: User):
    """TC-F1-18-12: Max DC charging power must be 0 kW or between 10.0 and 400.0 kW (Appendix B.3)."""
    token = make_token(driver_user)
    # Between 0 and 10 kW (invalid DC rating)
    resp_low = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 40.0,
            "connector_type": "CCS2",
            "max_ac_kw": 7.0,
            "max_dc_kw": 8.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 400.0 kW
    resp_high = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 100.0,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 401.0,
            "consumption_kwh_100km": 20.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_validation_rejects_out_of_range_consumption(client: TestClient, driver_user: User):
    """TC-F1-18-13: Energy consumption must be between 5.0 and 50.0 kWh per 100 km (Appendix B.3)."""
    token = make_token(driver_user)
    # Below 5.0
    resp_low = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 40.0,
            "connector_type": "CCS2",
            "max_ac_kw": 7.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 4.9,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 422

    # Above 50.0
    resp_high = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Test",
            "model": "EV",
            "battery_kwh": 40.0,
            "connector_type": "CCS2",
            "max_ac_kw": 7.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 50.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 422


def test_driver_isolation_access_denied(
    client: TestClient, driver_user: User, other_driver: User
):
    """TC-F1-18-14: Drivers cannot view vehicles owned by other drivers (REQ-F1-26)."""
    driver_a_token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Kia",
            "model": "EV6",
            "battery_kwh": 77.4,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 240.0,
            "consumption_kwh_100km": 16.5,
        },
        headers={"Authorization": f"Bearer {driver_a_token}"},
    )
    veh_id = create_resp.json()["id"]

    # Driver B tries to fetch Driver A's vehicle
    driver_b_token = make_token(other_driver)
    resp = client.get(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {driver_b_token}"},
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


def test_max_five_vehicles_limit(client: TestClient, driver_user: User):
    """TC-F1-18-15: Driver cannot add more than 5 vehicles (REQ-F1-22 / CS19-022)."""
    token = make_token(driver_user)
    # Add 5 vehicles
    for i in range(1, 6):
        resp = client.post(
            "/api/v1/vehicles",
            json={
                "make": "EVBrand",
                "model": f"Model {i}",
                "battery_kwh": 50.0 + i,
                "connector_type": "CCS2",
                "max_ac_kw": 11.0,
                "max_dc_kw": 50.0,
                "consumption_kwh_100km": 15.0,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 201

    # Attempt to add 6th vehicle
    resp_sixth = client.post(
        "/api/v1/vehicles",
        json={
            "make": "EVBrand",
            "model": "Model 6",
            "battery_kwh": 60.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_sixth.status_code == 400
    assert "maximum limit of 5 vehicles" in resp_sixth.json()["detail"].lower()
