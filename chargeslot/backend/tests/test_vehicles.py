"""
Unit and Integration Tests for EV Vehicle Registration.
Requirement: REQ-F1-18
Story ID: CS19-018
Test Case ID: TC-F1-18
System Test Case ID: STC-F1-18
"""

from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.models.booking import Booking, BookingStatus
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


# ==============================================================================
# CS19-019 / REQ-F1-19: Vehicle Validation
# ==============================================================================

def test_get_vehicle_validation_rules(client: TestClient):
    """TC-F1-19-01: Verifies validation rules metadata endpoint via REST."""
    resp = client.get("/api/v1/vehicles/validation-rules")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    rules = data["rules"]
    assert "battery_kwh" in rules
    assert rules["battery_kwh"]["min"] == 5.0
    assert rules["battery_kwh"]["max"] == 250.0
    assert "connector_type" in rules
    assert set(rules["connector_type"]["allowed_values"]) == {"CCS2", "CHAdeMO", "Type 2", "GB/T"}
    assert rules["max_ac_kw"]["min"] == 1.0
    assert rules["max_ac_kw"]["max"] == 50.0
    assert rules["consumption_kwh_100km"]["min"] == 5.0
    assert rules["consumption_kwh_100km"]["max"] == 50.0


def test_get_vehicle_validation_rules_architecture(client: TestClient):
    """TC-F1-19-02: Verifies SW Architecture route GET /api/v1/accounts/vehicle-value-validation."""
    resp = client.get("/api/v1/accounts/vehicle-value-validation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert "battery_kwh" in data["rules"]


def test_validate_vehicle_inputs_valid(client: TestClient, driver_user: User):
    """TC-F1-19-03: Verifies inline pre-save validation returns is_valid=True for valid fields."""
    token = make_token(driver_user)
    payload = {
        "make": "BMW",
        "model": "i4 eDrive40",
        "battery_kwh": 83.9,
        "connector_type": "CCS2",
        "max_ac_kw": 11.0,
        "max_dc_kw": 205.0,
        "consumption_kwh_100km": 18.0,
        "registration_no": "KA05EV0001",
    }
    resp = client.post(
        "/api/v1/vehicles/validate",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is True
    assert data["errors"] == {}
    assert "successful" in data["message"].lower()


def test_validate_vehicle_inputs_invalid(client: TestClient, driver_user: User):
    """TC-F1-19-04: Verifies inline pre-save validation returns field-level error messages."""
    token = make_token(driver_user)
    payload = {
        "make": " ",  # blank
        "model": "",  # blank
        "battery_kwh": 300.0,  # > 250
        "connector_type": "InvalidPlug",
        "max_ac_kw": 0.2,  # < 1.0
        "max_dc_kw": 5.0,  # must be 0 or 10-400
        "consumption_kwh_100km": 55.0,  # > 50
        "registration_no": "A" * 20,  # > 15 chars
    }
    resp = client.post(
        "/api/v1/vehicles/validate",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_valid"] is False
    errors = data["errors"]
    assert "make" in errors
    assert "model" in errors
    assert "battery_kwh" in errors
    assert "connector_type" in errors
    assert "max_ac_kw" in errors
    assert "max_dc_kw" in errors
    assert "consumption_kwh_100km" in errors
    assert "registration_no" in errors


def test_validate_vehicle_architecture_endpoint(client: TestClient, driver_user: User):
    """TC-F1-19-05: Verifies SW Architecture route POST /api/v1/accounts/vehicle-value-validation."""
    token = make_token(driver_user)
    payload = {
        "battery_kwh": 70.0,
        "connector_type": "CCS2",
        "max_ac_kw": 11.0,
    }
    resp = client.post(
        "/api/v1/accounts/vehicle-value-validation",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["is_valid"] is True


# ==============================================================================
# CS19-020 / REQ-F1-20: Vehicle Summary Card
# ==============================================================================

def test_get_vehicle_summary_card_success(client: TestClient, driver_user: User):
    """TC-F1-20-01 / STC-F1-20-01: Verifies summary card generation with compatibility badges & icons."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Audi",
            "model": "e-tron GT",
            "battery_kwh": 93.4,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 270.0,
            "consumption_kwh_100km": 19.5,
            "registration_no": "MH12EV0007",
            "is_default": True,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_resp.status_code == 201
    veh_id = create_resp.json()["id"]

    resp = client.get(
        f"/api/v1/vehicles/{veh_id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_id"] == veh_id
    assert data["display_title"] == "Audi e-tron GT"
    assert data["connector_icon"] == "icon-ccs2"
    assert data["current_type"] == "AC/DC"
    assert data["fast_charging_support"] is True
    assert data["max_ac_kw"] == 22.0
    assert data["max_dc_kw"] == 270.0
    # Calculations check:
    # estimated = round(93.4 / (19.5 / 100), 1) = 479.0
    # usable = round(0.9 * 93.4 / (19.5 / 100), 1) = 431.1
    assert data["estimated_range_km"] == 479.0
    assert data["usable_range_km"] == 431.1
    # Check compatibility badges
    badges = data["compatibility_badges"]
    assert any("CCS2" in b for b in badges)
    assert any("Fast Charging" in b for b in badges)
    assert any("Long Range" in b for b in badges)
    assert any("Default Vehicle" in b for b in badges)


def test_get_vehicle_summary_card_ac_only(client: TestClient, driver_user: User):
    """TC-F1-20-02: Verifies summary card for AC-only vehicle."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Smart",
            "model": "EQ Fortwo",
            "battery_kwh": 17.6,
            "connector_type": "Type 2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 0.0,
            "consumption_kwh_100km": 16.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    resp = client.get(
        f"/api/v1/vehicles/{veh_id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["connector_icon"] == "icon-type2"
    assert data["current_type"] == "AC Only"
    assert data["fast_charging_support"] is False
    assert any("AC Charging Only" in b for b in data["compatibility_badges"])


def test_list_vehicle_summary_cards(client: TestClient, driver_user: User):
    """TC-F1-20-03: Lists summary cards for all vehicles of driver."""
    token = make_token(driver_user)
    client.post(
        "/api/v1/vehicles",
        json={
            "make": "Polestar",
            "model": "2 Long Range",
            "battery_kwh": 78.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 150.0,
            "consumption_kwh_100km": 17.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    resp = client.get(
        "/api/v1/vehicles/summary/cards",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert all("connector_icon" in item for item in data["items"])


def test_vehicle_summary_card_architecture_routes(client: TestClient, driver_user: User):
    """TC-F1-20-04: Verifies SW Architecture routes for vehicle summary cards."""
    token = make_token(driver_user)
    client.post(
        "/api/v1/vehicles",
        json={
            "make": "Volvo",
            "model": "XC40 Recharge",
            "battery_kwh": 78.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 150.0,
            "consumption_kwh_100km": 19.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    # List route
    resp_list = client.get(
        "/api/v1/accounts/vehicle-summary-card",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_list.status_code == 200
    assert resp_list.json()["total"] >= 1

    first_veh_id = resp_list.json()["items"][0]["vehicle_id"]
    # Single vehicle route
    resp_single = client.get(
        f"/api/v1/accounts/vehicle-summary-card/{first_veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_single.status_code == 200
    assert resp_single.json()["vehicle_id"] == first_veh_id


def test_vehicle_summary_card_driver_isolation(
    client: TestClient, driver_user: User, other_driver: User
):
    """TC-F1-20-05: Driver B cannot view Driver A's vehicle summary card (REQ-F1-26)."""
    driver_a_token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Porsche",
            "model": "Taycan",
            "battery_kwh": 93.4,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 270.0,
            "consumption_kwh_100km": 21.0,
        },
        headers={"Authorization": f"Bearer {driver_a_token}"},
    )
    veh_id = create_resp.json()["id"]

    driver_b_token = make_token(other_driver)
    resp = client.get(
        f"/api/v1/vehicles/{veh_id}/summary",
        headers={"Authorization": f"Bearer {driver_b_token}"},
    )
    assert resp.status_code == 403


def test_vehicle_summary_card_not_found(client: TestClient, driver_user: User):
    """TC-F1-20-06: Requesting summary card for non-existent vehicle returns 404."""
    token = make_token(driver_user)
    resp = client.get(
        "/api/v1/vehicles/999999/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ==============================================================================
# CS19-021 / REQ-F1-21: Edit or Remove Vehicle
# ==============================================================================

def test_edit_vehicle_success(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-21-01 / STC-F1-21-01: Driver successfully updates vehicle attributes."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Lucid",
            "model": "Air Pure",
            "battery_kwh": 88.0,
            "connector_type": "CCS2",
            "max_ac_kw": 19.2,
            "max_dc_kw": 250.0,
            "consumption_kwh_100km": 14.5,
            "registration_no": "KA01EV1111",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    update_payload = {
        "model": "Air Touring",
        "battery_kwh": 92.0,
        "max_dc_kw": 300.0,
        "consumption_kwh_100km": 15.0,
        "registration_no": "KA01EV2222",
    }
    resp = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json=update_payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["model"] == "Air Touring"
    assert data["battery_kwh"] == 92.0
    assert data["max_dc_kw"] == 300.0
    assert data["consumption_kwh_100km"] == 15.0
    assert data["registration_no"] == "KA01EV2222"

    # Verify DB persistence
    veh = db_session.query(Vehicle).filter(Vehicle.id == veh_id).first()
    assert veh.model == "Air Touring"
    assert veh.battery_kwh == 92.0


def test_edit_vehicle_architecture_route(client: TestClient, driver_user: User):
    """TC-F1-21-02: Verifies SW Architecture route PATCH /api/v1/accounts/vehicle-crud/{id}."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Ford",
            "model": "Mustang Mach-E",
            "battery_kwh": 75.7,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 150.0,
            "consumption_kwh_100km": 18.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    resp = client.patch(
        f"/api/v1/accounts/vehicle-crud/{veh_id}",
        json={"max_dc_kw": 190.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["max_dc_kw"] == 190.0


def test_edit_vehicle_default_reassignment(client: TestClient, driver_user: User):
    """TC-F1-21-03: Setting is_default=True on a second vehicle automatically unsets it on the first."""
    token = make_token(driver_user)
    # First vehicle (automatically default)
    resp1 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tesla",
            "model": "Model S",
            "battery_kwh": 100.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 250.0,
            "consumption_kwh_100km": 18.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    id1 = resp1.json()["id"]
    assert resp1.json()["is_default"] is True

    # Second vehicle (not default)
    resp2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tesla",
            "model": "Model X",
            "battery_kwh": 100.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 250.0,
            "consumption_kwh_100km": 20.0,
            "is_default": False,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    id2 = resp2.json()["id"]
    assert resp2.json()["is_default"] is False

    # Update second vehicle to default
    update_resp = client.patch(
        f"/api/v1/vehicles/{id2}",
        json={"is_default": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["is_default"] is True

    # Check that first vehicle is no longer default
    get1_resp = client.get(
        f"/api/v1/vehicles/{id1}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get1_resp.json()["is_default"] is False


def test_edit_vehicle_creates_audit_log(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-21-04: Verifies editing a vehicle creates an audit log entry."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Kia",
            "model": "Niro EV",
            "battery_kwh": 64.8,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 84.0,
            "consumption_kwh_100km": 16.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"max_dc_kw": 100.0},
        headers={"Authorization": f"Bearer {token}"},
    )

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver_user.id,
            AuditLog.action == "VEHICLE_UPDATED",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_entry is not None
    assert "max_dc_kw" in audit_entry.details


def test_edit_vehicle_validation_errors(client: TestClient, driver_user: User):
    """TC-F1-21-05: Rejects invalid attribute updates with 422."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "BMW",
            "model": "iX3",
            "battery_kwh": 74.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 150.0,
            "consumption_kwh_100km": 18.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    # Invalid battery capacity (> 250)
    resp = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"battery_kwh": 300.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    # Invalid max_dc_kw (between 0 and 10)
    resp = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"max_dc_kw": 5.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422

    # Blank make
    resp = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"make": "   "},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422


def test_edit_vehicle_driver_isolation(
    client: TestClient, driver_user: User, other_driver: User
):
    """TC-F1-21-06: Driver B cannot edit Driver A's vehicle (REQ-F1-26)."""
    driver_a_token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Genesis",
            "model": "GV60",
            "battery_kwh": 77.4,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 235.0,
            "consumption_kwh_100km": 19.0,
        },
        headers={"Authorization": f"Bearer {driver_a_token}"},
    )
    veh_id = create_resp.json()["id"]

    driver_b_token = make_token(other_driver)
    resp = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"model": "GV70 Electrified"},
        headers={"Authorization": f"Bearer {driver_b_token}"},
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


def test_edit_vehicle_not_found(client: TestClient, driver_user: User):
    """TC-F1-21-07: Updating non-existent vehicle returns 404."""
    token = make_token(driver_user)
    resp = client.patch(
        "/api/v1/vehicles/999999",
        json={"model": "Ghost EV"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


def test_remove_vehicle_success(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-21-08 / STC-F1-21-02: Driver removes vehicle via DELETE /api/v1/vehicles/{id}."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Fiat",
            "model": "500e",
            "battery_kwh": 42.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 85.0,
            "consumption_kwh_100km": 14.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    data = del_resp.json()
    assert data["status"] == "success"
    assert data["vehicle_id"] == veh_id

    # Verify vehicle is deleted from database
    veh_in_db = db_session.query(Vehicle).filter(Vehicle.id == veh_id).first()
    assert veh_in_db is None


def test_remove_vehicle_architecture_route(client: TestClient, driver_user: User):
    """TC-F1-21-09: Verifies SW Architecture route DELETE /api/v1/accounts/vehicle-crud/{id}."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Mini",
            "model": "Cooper SE",
            "battery_kwh": 32.6,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.2,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    del_resp = client.delete(
        f"/api/v1/accounts/vehicle-crud/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    assert del_resp.json()["status"] == "success"


def test_remove_vehicle_default_fallback(client: TestClient, driver_user: User):
    """TC-F1-21-10: Deleting default vehicle reassigns default status to remaining vehicle."""
    token = make_token(driver_user)
    # Add vehicle 1 (default)
    resp1 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Jaguar",
            "model": "I-Pace",
            "battery_kwh": 90.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 100.0,
            "consumption_kwh_100km": 22.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    id1 = resp1.json()["id"]

    # Add vehicle 2
    resp2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Mercedes",
            "model": "EQE",
            "battery_kwh": 90.6,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 170.0,
            "consumption_kwh_100km": 18.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    id2 = resp2.json()["id"]

    # Delete vehicle 1
    client.delete(
        f"/api/v1/vehicles/{id1}",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Vehicle 2 must now be default
    get2 = client.get(
        f"/api/v1/vehicles/{id2}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get2.json()["is_default"] is True


def test_remove_vehicle_creates_audit_log(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-21-11: Verifies removing a vehicle creates a VEHICLE_DELETED audit log entry."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Skoda",
            "model": "Enyaq iV",
            "battery_kwh": 77.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 135.0,
            "consumption_kwh_100km": 17.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]

    client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver_user.id,
            AuditLog.action == "VEHICLE_DELETED",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_entry is not None
    assert "Enyaq" in audit_entry.details


def test_remove_vehicle_driver_isolation(
    client: TestClient, driver_user: User, other_driver: User
):
    """TC-F1-21-12: Driver B cannot delete Driver A's vehicle (REQ-F1-26)."""
    driver_a_token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Volkswagen",
            "model": "ID.4",
            "battery_kwh": 77.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 135.0,
            "consumption_kwh_100km": 17.5,
        },
        headers={"Authorization": f"Bearer {driver_a_token}"},
    )
    veh_id = create_resp.json()["id"]

    driver_b_token = make_token(other_driver)
    resp = client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {driver_b_token}"},
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


def test_remove_vehicle_not_found(client: TestClient, driver_user: User):
    """TC-F1-21-13: Deleting non-existent vehicle returns 404."""
    token = make_token(driver_user)
    resp = client.delete(
        "/api/v1/vehicles/999999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


# ==============================================================================
# CS19-022 / REQ-F1-22: Max 5 Vehicles Rule & Exactly One Default Vehicle
# ==============================================================================

def test_get_vehicle_limit_and_default_empty(client: TestClient, driver_user: User):
    """TC-F1-22-01 / STC-F1-22-01: Verifies vehicle limit info when driver has 0 vehicles."""
    token = make_token(driver_user)
    # REST route
    resp = client.get(
        "/api/v1/vehicles/limit-and-default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["max_vehicles_allowed"] == 5
    assert data["current_vehicle_count"] == 0
    assert data["can_add_more"] is True
    assert data["default_vehicle_id"] is None
    assert data["default_vehicle"] is None

    # Architecture route
    resp_arch = client.get(
        "/api/v1/accounts/vehicle-limit-and-default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_arch.status_code == 200
    assert resp_arch.json()["max_vehicles_allowed"] == 5


def test_first_vehicle_becomes_default_and_get_default_endpoint(client: TestClient, driver_user: User):
    """TC-F1-22-02: Verifies first added vehicle is automatically default and retrievable."""
    token = make_token(driver_user)
    create_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Lucid",
            "model": "Air Gravity",
            "battery_kwh": 118.0,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 300.0,
            "consumption_kwh_100km": 18.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = create_resp.json()["id"]
    assert create_resp.json()["is_default"] is True

    # Check GET /vehicles/default
    resp_def = client.get(
        "/api/v1/vehicles/default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_def.status_code == 200
    assert resp_def.json()["id"] == veh_id
    assert resp_def.json()["is_default"] is True

    # Check limit-and-default reflects this
    limit_resp = client.get(
        "/api/v1/vehicles/limit-and-default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert limit_resp.json()["current_vehicle_count"] == 1
    assert limit_resp.json()["default_vehicle_id"] == veh_id


def test_set_default_vehicle_rest_and_architecture(client: TestClient, driver_user: User):
    """TC-F1-22-03: Switching default vehicle unsets previous default, keeping exactly one default."""
    token = make_token(driver_user)
    # Add Vehicle 1 (default)
    v1 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Rivian",
            "model": "R1T",
            "battery_kwh": 135.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.5,
            "max_dc_kw": 220.0,
            "consumption_kwh_100km": 24.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    # Add Vehicle 2
    v2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Rivian",
            "model": "R1S",
            "battery_kwh": 135.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.5,
            "max_dc_kw": 220.0,
            "consumption_kwh_100km": 25.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    # REST: Set vehicle 2 as default
    set_resp = client.patch(
        f"/api/v1/vehicles/{v2['id']}/set-default",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert set_resp.status_code == 200
    assert set_resp.json()["success"] is True
    assert set_resp.json()["default_vehicle"]["id"] == v2["id"]

    # Verify vehicle 1 is now not default
    get_v1 = client.get(f"/api/v1/vehicles/{v1['id']}", headers={"Authorization": f"Bearer {token}"}).json()
    assert get_v1["is_default"] is False

    # Architecture: Switch default back to vehicle 1 via PATCH /api/v1/accounts/vehicle-limit-and-default
    arch_resp = client.patch(
        "/api/v1/accounts/vehicle-limit-and-default",
        json={"vehicle_id": v1["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert arch_resp.status_code == 200
    assert arch_resp.json()["default_vehicle"]["id"] == v1["id"]

    # Architecture POST alias
    arch_post = client.post(
        "/api/v1/accounts/vehicle-limit-and-default",
        json={"vehicle_id": v2["id"]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert arch_post.status_code == 200
    assert arch_post.json()["default_vehicle"]["id"] == v2["id"]


def test_set_default_vehicle_audit_log(
    client: TestClient, db_session: Session, driver_user: User
):
    """TC-F1-22-04: Changing default vehicle creates a VEHICLE_DEFAULT_SET audit log entry."""
    token = make_token(driver_user)
    v1 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Audi",
            "model": "Q4 e-tron",
            "battery_kwh": 77.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 135.0,
            "consumption_kwh_100km": 17.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    v2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Audi",
            "model": "Q8 e-tron",
            "battery_kwh": 106.0,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 170.0,
            "consumption_kwh_100km": 21.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    client.patch(
        f"/api/v1/vehicles/{v2['id']}/set-default",
        headers={"Authorization": f"Bearer {token}"},
    )

    audit_entry = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver_user.id,
            AuditLog.action == "VEHICLE_DEFAULT_SET",
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit_entry is not None
    assert "Q8 e-tron" in audit_entry.details


def test_cannot_unset_default_on_only_vehicle(client: TestClient, driver_user: User):
    """TC-F1-22-05: Driver cannot set is_default=False on their only registered vehicle."""
    token = make_token(driver_user)
    veh = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Kia",
            "model": "EV9",
            "battery_kwh": 99.8,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 210.0,
            "consumption_kwh_100km": 22.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    ).json()

    # Attempt to unset default
    resp = client.patch(
        f"/api/v1/vehicles/{veh['id']}",
        json={"is_default": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "exactly one default vehicle" in resp.json()["detail"].lower()


def test_set_default_vehicle_foreign_driver_denied(
    client: TestClient, driver_user: User, other_driver: User
):
    """TC-F1-22-06: Driver B cannot set Driver A's vehicle as default (REQ-F1-26)."""
    token_a = make_token(driver_user)
    veh_a = client.post(
        "/api/v1/vehicles",
        json={
            "make": "BMW",
            "model": "iX M60",
            "battery_kwh": 105.2,
            "connector_type": "CCS2",
            "max_ac_kw": 22.0,
            "max_dc_kw": 195.0,
            "consumption_kwh_100km": 23.0,
        },
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()

    token_b = make_token(other_driver)
    resp = client.patch(
        f"/api/v1/vehicles/{veh_a['id']}/set-default",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert resp.status_code == 403
    assert "access denied" in resp.json()["detail"].lower()


def test_enforce_5_vehicles_and_reopen_on_deletion(client: TestClient, driver_user: User):
    """TC-F1-22-07 / STC-F1-22-02: Strictly limits vehicles to 5; deleting opens slot to add again."""
    token = make_token(driver_user)
    vehicle_ids = []
    # Add 5 vehicles
    for i in range(1, 6):
        resp = client.post(
            "/api/v1/vehicles",
            json={
                "make": "QuotaTest",
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
        vehicle_ids.append(resp.json()["id"])

    # Verify limit status
    limit_resp = client.get("/api/v1/vehicles/limit-and-default", headers={"Authorization": f"Bearer {token}"}).json()
    assert limit_resp["current_vehicle_count"] == 5
    assert limit_resp["can_add_more"] is False

    # Attempt to add 6th vehicle via standard route
    resp6 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "QuotaTest",
            "model": "Model 6",
            "battery_kwh": 60.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp6.status_code == 400
    assert "maximum limit of 5 vehicles" in resp6.json()["detail"].lower()

    # Attempt to add 6th vehicle via architecture route
    resp6_arch = client.post(
        "/api/v1/accounts/vehicle-crud",
        json={
            "make": "QuotaTest",
            "model": "Model 6",
            "battery_kwh": 60.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp6_arch.status_code == 400

    # Delete one vehicle
    client.delete(f"/api/v1/vehicles/{vehicle_ids[0]}", headers={"Authorization": f"Bearer {token}"})

    # Now limit allows adding again
    limit_after = client.get("/api/v1/vehicles/limit-and-default", headers={"Authorization": f"Bearer {token}"}).json()
    assert limit_after["current_vehicle_count"] == 4
    assert limit_after["can_add_more"] is True

    # Successfully add 5th vehicle
    resp_readd = client.post(
        "/api/v1/vehicles",
        json={
            "make": "QuotaTest",
            "model": "Model 5 Replacement",
            "battery_kwh": 65.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_readd.status_code == 201


# ==============================================================================
# CS19-023 / REQ-F1-23: Preset EV Models (TC-F1-23 / STC-F1-23)
# ==============================================================================

def test_list_preset_ev_models_rest_and_architecture(client: TestClient, driver_user: User):
    """TC-F1-23-01 / STC-F1-23-01: List preset EV models via REST and architecture routes."""
    # REST route
    resp1 = client.get("/api/v1/vehicles/presets")
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["total"] >= 10
    preset_ids = [p["id"] for p in data1["items"]]
    assert "tata-nexon-ev-lr" in preset_ids
    assert "hyundai-ioniq-5" in preset_ids
    assert "tesla-model-3" in preset_ids
    assert "nissan-leaf" in preset_ids

    # Architecture route
    resp2 = client.get("/api/v1/accounts/preset-ev-models")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["total"] == data1["total"]


def test_filter_preset_ev_models(client: TestClient):
    """TC-F1-23-02: Filter presets by make and connector type."""
    # Filter by make
    resp_make = client.get("/api/v1/vehicles/presets?make=Tata")
    assert resp_make.status_code == 200
    data_make = resp_make.json()
    assert data_make["total"] >= 3
    for p in data_make["items"]:
        assert p["make"].lower() == "tata"

    # Filter by connector type
    resp_conn = client.get("/api/v1/vehicles/presets?connector_type=CHAdeMO")
    assert resp_conn.status_code == 200
    data_conn = resp_conn.json()
    assert data_conn["total"] >= 1
    for p in data_conn["items"]:
        assert p["connector_type"] == "CHAdeMO"


def test_get_single_preset_ev_model(client: TestClient):
    """TC-F1-23-03: Retrieve single preset EV model by ID."""
    resp = client.get("/api/v1/vehicles/presets/tata-nexon-ev-lr")
    assert resp.status_code == 200
    p = resp.json()
    assert p["id"] == "tata-nexon-ev-lr"
    assert p["make"] == "Tata"
    assert p["battery_kwh"] == 40.5
    assert p["connector_type"] == "CCS2"
    assert p["max_ac_kw"] == 7.2
    assert p["max_dc_kw"] == 50.0

    # Non-existent preset returns 404
    resp_404 = client.get("/api/v1/vehicles/presets/non-existent-ev-model")
    assert resp_404.status_code == 404
    assert "not found" in resp_404.json()["detail"].lower()


def test_apply_preset_prefill_only(client: TestClient, driver_user: User):
    """TC-F1-23-04: Apply preset EV model to prefill specification fields without creating vehicle."""
    token = make_token(driver_user)
    payload = {
        "preset_id": "hyundai-ioniq-5",
        "registration_no": "KA05EV1122",
        "custom_battery_kwh": 70.0,
        "create_vehicle": False,
    }
    # Test via REST route
    resp = client.post(
        "/api/v1/vehicles/presets/apply",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["preset_id"] == "hyundai-ioniq-5"
    assert data["created_vehicle"] is None
    spec = data["prefilled_spec"]
    assert spec["make"] == "Hyundai"
    assert spec["model"] == "Ioniq 5 RWD"
    assert spec["battery_kwh"] == 70.0  # overridden
    assert spec["max_ac_kw"] == 11.0  # preset default
    assert spec["connector_type"] == "CCS2"
    assert spec["registration_no"] == "KA05EV1122"

    # Architecture route POST /api/v1/accounts/preset-ev-models
    resp_arch = client.post(
        "/api/v1/accounts/preset-ev-models",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_arch.status_code == 200
    assert resp_arch.json()["preset_id"] == "hyundai-ioniq-5"


def test_apply_preset_create_vehicle_in_garage(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-23-05 / STC-F1-23-02: Apply preset with create_vehicle=True saves vehicle to driver profile."""
    token = make_token(driver_user)
    payload = {
        "preset_id": "tesla-model-3",
        "registration_no": "MH12EV9876",
        "create_vehicle": True,
    }
    resp = client.post(
        "/api/v1/vehicles/presets/apply",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["created_vehicle"] is not None
    created = data["created_vehicle"]
    assert created["make"] == "Tesla"
    assert created["model"] == "Model 3 RWD"
    assert created["battery_kwh"] == 60.0
    assert created["registration_no"] == "MH12EV9876"
    assert created["is_default"] is True  # First vehicle becomes default

    # Verify audit log was recorded for vehicle addition
    audit = db_session.query(AuditLog).filter(
        AuditLog.user_id == driver_user.id,
        AuditLog.action == "VEHICLE_ADDED",
    ).first()
    assert audit is not None


def test_apply_preset_invalid_preset_id_and_out_of_range(client: TestClient, driver_user: User):
    """TC-F1-23-06: Applying invalid preset ID returns 404; out of range override returns 422."""
    token = make_token(driver_user)
    # Invalid preset ID
    resp_404 = client.post(
        "/api/v1/vehicles/presets/apply",
        json={"preset_id": "non-existent-id"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_404.status_code == 404

    # Out of range battery override (> 250 kWh)
    resp_422 = client.post(
        "/api/v1/vehicles/presets/apply",
        json={
            "preset_id": "tesla-model-3",
            "custom_battery_kwh": 300.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_422.status_code == 422


# ==============================================================================
# CS19-024 / REQ-F1-24: Vehicle Value Validation (TC-F1-24 / STC-F1-24)
# ==============================================================================

def test_vehicle_validation_rules_metadata_appendix_b(client: TestClient):
    """TC-F1-24-01: Metadata validation rules reflect Appendix B.3 ranges."""
    # REST route
    resp = client.get("/api/v1/vehicles/validation-rules")
    assert resp.status_code == 200
    rules = resp.json()["rules"]
    assert rules["battery_kwh"]["min"] == 5.0
    assert rules["battery_kwh"]["max"] == 250.0
    assert rules["max_ac_kw"]["min"] == 1.0
    assert rules["max_ac_kw"]["max"] == 50.0
    assert rules["max_dc_kw"]["min_if_supported"] == 10.0
    assert rules["max_dc_kw"]["max"] == 400.0
    assert rules["consumption_kwh_100km"]["min"] == 5.0
    assert rules["consumption_kwh_100km"]["max"] == 50.0
    assert rules["make"]["max_length"] == 40
    assert rules["model"]["max_length"] == 40
    assert rules["registration_no"]["max_length"] == 15

    # Architecture route
    resp_arch = client.get("/api/v1/accounts/vehicle-value-validation")
    assert resp_arch.status_code == 200
    assert resp_arch.json()["rules"]["battery_kwh"]["max"] == 250.0


def test_vehicle_validation_check_valid_and_boundaries(client: TestClient, driver_user: User):
    """TC-F1-24-02: Boundary valid values in Appendix B.3 are accepted."""
    token = make_token(driver_user)
    # Lower boundary
    resp_low = client.post(
        "/api/v1/vehicles/validate",
        json={
            "make": "A",
            "model": "B",
            "battery_kwh": 5.0,
            "connector_type": "CCS2",
            "max_ac_kw": 1.0,
            "max_dc_kw": 0.0,
            "consumption_kwh_100km": 5.0,
            "registration_no": "A",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_low.status_code == 200
    assert resp_low.json()["is_valid"] is True
    assert resp_low.json()["errors"] == {}

    # Upper boundary
    resp_high = client.post(
        "/api/v1/accounts/vehicle-value-validation",
        json={
            "make": "M" * 40,
            "model": "O" * 40,
            "battery_kwh": 250.0,
            "connector_type": "GB/T",
            "max_ac_kw": 50.0,
            "max_dc_kw": 400.0,
            "consumption_kwh_100km": 50.0,
            "registration_no": "R" * 15,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_high.status_code == 200
    assert resp_high.json()["is_valid"] is True
    assert resp_high.json()["errors"] == {}

    # DC lower boundary when supported (10.0 kW)
    resp_dc_min = client.post(
        "/api/v1/vehicles/validate",
        json={"max_dc_kw": 10.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_dc_min.status_code == 200
    assert resp_dc_min.json()["is_valid"] is True


def test_vehicle_validation_check_out_of_range_rejected(client: TestClient, driver_user: User):
    """TC-F1-24-03 / STC-F1-24-01: Values outside Appendix B.3 ranges are rejected with errors."""
    token = make_token(driver_user)
    # Below minimums
    resp_below = client.post(
        "/api/v1/vehicles/validate",
        json={
            "make": "   ",
            "model": "",
            "battery_kwh": 4.9,
            "connector_type": "UnsupportedType",
            "max_ac_kw": 0.9,
            "max_dc_kw": 5.0,  # Below 10.0 when > 0
            "consumption_kwh_100km": 4.9,
            "registration_no": "TOOLONGREGISTRATIONNO",  # > 15 chars
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_below.status_code == 200
    data_below = resp_below.json()
    assert data_below["is_valid"] is False
    errors = data_below["errors"]
    assert "make" in errors
    assert "model" in errors
    assert "battery_kwh" in errors
    assert "connector_type" in errors
    assert "max_ac_kw" in errors
    assert "max_dc_kw" in errors
    assert "consumption_kwh_100km" in errors
    assert "registration_no" in errors

    # Above maximums
    resp_above = client.post(
        "/api/v1/accounts/vehicle-value-validation",
        json={
            "make": "M" * 41,
            "model": "O" * 41,
            "battery_kwh": 250.1,
            "max_ac_kw": 50.1,
            "max_dc_kw": 400.1,
            "consumption_kwh_100km": 50.1,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_above.status_code == 200
    data_above = resp_above.json()
    assert data_above["is_valid"] is False
    errors_above = data_above["errors"]
    assert "make" in errors_above
    assert "model" in errors_above
    assert "battery_kwh" in errors_above
    assert "max_ac_kw" in errors_above
    assert "max_dc_kw" in errors_above
    assert "consumption_kwh_100km" in errors_above


def test_vehicle_create_and_update_strictly_enforce_appendix_b(client: TestClient, driver_user: User):
    """TC-F1-24-04 / STC-F1-24-02: POST and PATCH vehicle endpoints strictly reject out-of-range values."""
    token = make_token(driver_user)
    # POST with battery_kwh > 250
    resp_bad_create = client.post(
        "/api/v1/vehicles",
        json={
            "make": "InvalidVolt",
            "model": "Megabattery",
            "battery_kwh": 300.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_bad_create.status_code == 422

    # POST with DC rate between 0 and 10 kW (e.g. 5 kW)
    resp_bad_dc = client.post(
        "/api/v1/vehicles",
        json={
            "make": "InvalidVolt",
            "model": "WeirdDC",
            "battery_kwh": 50.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 5.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_bad_dc.status_code == 422

    # Create a valid vehicle first
    resp_valid = client.post(
        "/api/v1/vehicles",
        json={
            "make": "ValidVolt",
            "model": "EV One",
            "battery_kwh": 50.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_valid.status_code == 201
    veh_id = resp_valid.json()["id"]

    # PATCH with consumption > 50
    resp_bad_patch = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"consumption_kwh_100km": 60.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_bad_patch.status_code == 422

    # PATCH with AC rate < 1.0
    resp_bad_ac = client.patch(
        f"/api/v1/vehicles/{veh_id}",
        json={"max_ac_kw": 0.5},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_bad_ac.status_code == 422


# ==============================================================================
# CS19-025 / REQ-F1-25: Protect Booked Vehicle (TC-F1-25 / STC-F1-25)
# ==============================================================================

def test_delete_vehicle_blocked_when_active_booking_exists(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-25-01 / STC-F1-25-01: Vehicle cannot be deleted when linked to an active booking."""
    token = make_token(driver_user)
    # 1. Add vehicle
    v_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tata",
            "model": "Nexon EV",
            "battery_kwh": 40.5,
            "connector_type": "CCS2",
            "max_ac_kw": 7.2,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert v_resp.status_code == 201
    veh_id = v_resp.json()["id"]

    # 2. Seed an ACTIVE booking linked to this vehicle
    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=driver_user.id,
        vehicle_id=veh_id,
        status=BookingStatus.ACTIVE,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    db_session.add(booking)
    db_session.commit()

    # 3. Attempt to delete vehicle via REST endpoint -> rejected with 400
    del_resp = client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 400
    assert "active or upcoming booking" in del_resp.json()["detail"].lower()
    assert "REQ-F1-25" in del_resp.json()["detail"]

    # 4. Attempt to delete via architecture route DELETE /api/v1/accounts/vehicle-crud -> rejected with 400
    del_arch = client.delete(
        f"/api/v1/accounts/vehicle-crud?vehicle_id={veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_arch.status_code == 400
    assert "active or upcoming booking" in del_arch.json()["detail"].lower()

    # 5. Verify vehicle still persists in DB
    check_veh = db_session.query(Vehicle).filter(Vehicle.id == veh_id).first()
    assert check_veh is not None


def test_delete_vehicle_blocked_when_upcoming_booking_exists(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-25-02: Vehicle cannot be deleted when linked to an upcoming CONFIRMED or HELD booking."""
    token = make_token(driver_user)
    v_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "MG",
            "model": "ZS EV",
            "battery_kwh": 50.3,
            "connector_type": "CCS2",
            "max_ac_kw": 7.4,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 16.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert v_resp.status_code == 201
    veh_id = v_resp.json()["id"]

    # Seed upcoming CONFIRMED booking
    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=driver_user.id,
        vehicle_id=veh_id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(days=1),
        end_time=now + timedelta(days=1, hours=1),
    )
    db_session.add(booking)
    db_session.commit()

    del_resp = client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 400
    assert "REQ-F1-25" in del_resp.json()["detail"]


def test_protect_booked_vehicle_inspection_endpoints(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-25-03: Inspect vehicle protection status via REST and SW Architecture routes."""
    token = make_token(driver_user)
    v_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Hyundai",
            "model": "Ioniq 5",
            "battery_kwh": 72.6,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 350.0,
            "consumption_kwh_100km": 17.0,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = v_resp.json()["id"]

    # Initially no bookings -> can_delete=True, is_protected=False
    resp_init = client.get(
        f"/api/v1/vehicles/{veh_id}/booking-protection",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_init.status_code == 200
    assert resp_init.json()["is_protected"] is False
    assert resp_init.json()["can_delete"] is True
    assert resp_init.json()["active_booking_count"] == 0

    # Add active booking
    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=driver_user.id,
        vehicle_id=veh_id,
        status=BookingStatus.ACTIVE,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    db_session.add(booking)
    db_session.commit()

    # Query via SW Architecture route POST /api/v1/accounts/protect-booked-vehicle
    resp_arch = client.post(
        "/api/v1/accounts/protect-booked-vehicle",
        json={"vehicle_id": veh_id},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_arch.status_code == 200
    arch_data = resp_arch.json()
    assert arch_data["is_protected"] is True
    assert arch_data["can_delete"] is False
    assert arch_data["active_booking_count"] == 1
    assert arch_data["active_bookings"][0]["id"] == booking.id

    # Query via GET /api/v1/accounts/protect-booked-vehicle/{vehicle_id}
    resp_arch_get = client.get(
        f"/api/v1/accounts/protect-booked-vehicle/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp_arch_get.status_code == 200
    assert resp_arch_get.json()["is_protected"] is True


def test_delete_vehicle_allowed_with_completed_or_cancelled_bookings(client: TestClient, db_session: Session, driver_user: User):
    """TC-F1-25-04: Vehicles with only completed or cancelled bookings can be deleted safely."""
    token = make_token(driver_user)
    v_resp = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Mahindra",
            "model": "XUV400",
            "battery_kwh": 39.4,
            "connector_type": "CCS2",
            "max_ac_kw": 7.2,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 15.5,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    veh_id = v_resp.json()["id"]

    # Seed COMPLETED and CANCELLED bookings
    now = datetime.now(timezone.utc)
    b1 = Booking(
        user_id=driver_user.id,
        vehicle_id=veh_id,
        status=BookingStatus.COMPLETED,
        start_time=now - timedelta(days=2),
        end_time=now - timedelta(days=2, hours=1),
    )
    b2 = Booking(
        user_id=driver_user.id,
        vehicle_id=veh_id,
        status=BookingStatus.CANCELLED,
        start_time=now - timedelta(days=1),
        end_time=now - timedelta(days=1, hours=1),
    )
    db_session.add_all([b1, b2])
    db_session.commit()

    # Deletion should succeed
    del_resp = client.delete(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_resp.status_code == 200
    assert "successfully removed" in del_resp.json()["message"]


# ==============================================================================
# CS19-026 / REQ-F1-26: Driver Sees Own Data Only (TC-F1-26 / STC-F1-26)
# ==============================================================================

def test_driver_data_scope_own_data_accessible(client: TestClient, driver_user: User, other_driver: User):
    """TC-F1-26-01 / STC-F1-26-01: Driver can view their own tenancy scope and vehicles."""
    token1 = make_token(driver_user)
    token2 = make_token(other_driver)

    # Driver 1 registers a vehicle
    r1 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Tesla",
            "model": "Model 3",
            "battery_kwh": 60.0,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 170.0,
            "consumption_kwh_100km": 14.5,
        },
        headers={"Authorization": f"Bearer {token1}"},
    )
    veh1_id = r1.json()["id"]

    # Driver 2 registers a vehicle
    r2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Kia",
            "model": "EV6",
            "battery_kwh": 77.4,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 350.0,
            "consumption_kwh_100km": 16.5,
        },
        headers={"Authorization": f"Bearer {token2}"},
    )
    veh2_id = r2.json()["id"]

    # Driver 1 calls /api/v1/accounts/driver-sees-own-data-only
    resp1 = client.get(
        "/api/v1/accounts/driver-sees-own-data-only",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp1.status_code == 200
    d1 = resp1.json()
    assert d1["user_id"] == driver_user.id
    assert veh1_id in d1["accessible_vehicle_ids"]
    assert veh2_id not in d1["accessible_vehicle_ids"]

    # Driver 2 calls /api/v1/accounts/driver-sees-own-data-only
    resp2 = client.get(
        "/api/v1/accounts/driver-sees-own-data-only",
        headers={"Authorization": f"Bearer {token2}"},
    )
    assert resp2.status_code == 200
    d2 = resp2.json()
    assert d2["user_id"] == other_driver.id
    assert veh2_id in d2["accessible_vehicle_ids"]
    assert veh1_id not in d2["accessible_vehicle_ids"]


def test_driver_blocked_from_other_driver_resources(client: TestClient, driver_user: User, other_driver: User):
    """TC-F1-26-02: Tenancy isolation strictly denies viewing or modifying foreign driver data with 403."""
    token1 = make_token(driver_user)
    token2 = make_token(other_driver)

    # Driver 2 owns a vehicle
    r2 = client.post(
        "/api/v1/vehicles",
        json={
            "make": "Nissan",
            "model": "Leaf",
            "battery_kwh": 40.0,
            "connector_type": "CHAdeMO",
            "max_ac_kw": 6.6,
            "max_dc_kw": 50.0,
            "consumption_kwh_100km": 17.0,
        },
        headers={"Authorization": f"Bearer {token2}"},
    )
    foreign_veh_id = r2.json()["id"]

    # 1. Driver 1 cannot inspect Driver 2's data scope
    resp_scope_probe = client.get(
        f"/api/v1/accounts/driver-sees-own-data-only?target_user_id={other_driver.id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_scope_probe.status_code == 403
    assert "REQ-F1-26" in resp_scope_probe.json()["detail"]

    # 2. Driver 1 cannot view Driver 2's vehicle
    resp_get = client.get(
        f"/api/v1/vehicles/{foreign_veh_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_get.status_code == 403
    assert "REQ-F1-26" in resp_get.json()["detail"]

    # 3. Driver 1 cannot edit Driver 2's vehicle
    resp_patch = client.patch(
        f"/api/v1/vehicles/{foreign_veh_id}",
        json={"make": "TamperedMake"},
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_patch.status_code == 403

    # 4. Driver 1 cannot delete Driver 2's vehicle
    resp_del = client.delete(
        f"/api/v1/vehicles/{foreign_veh_id}",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_del.status_code == 403

    # 5. Driver 1 cannot view summary card of Driver 2's vehicle
    resp_summary = client.get(
        f"/api/v1/vehicles/{foreign_veh_id}/summary",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_summary.status_code == 403

    # 6. Driver 1 cannot set default on Driver 2's vehicle
    resp_default = client.patch(
        f"/api/v1/vehicles/{foreign_veh_id}/set-default",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_default.status_code == 403

    # 7. Driver 1 cannot check booking protection on Driver 2's vehicle
    resp_prot = client.get(
        f"/api/v1/vehicles/{foreign_veh_id}/booking-protection",
        headers={"Authorization": f"Bearer {token1}"},
    )
    assert resp_prot.status_code == 403


def test_admin_global_access_and_operator_denied(client: TestClient, db_session: Session, driver_user: User, operator_user: User):
    """TC-F1-26-03: Administrators have global scope; Station Operators cannot access driver vehicles."""
    # Create admin
    admin = User(
        name="Chief Admin",
        email="chief.admin@example.com",
        phone="+15556667779",
        hashed_password=hash_password("AdminPass123!"),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()
    admin_token = make_token(admin)
    driver_token = make_token(driver_user)
    op_token = make_token(operator_user)

    # Driver adds vehicle
    r = client.post(
        "/api/v1/vehicles",
        json={
            "make": "BMW",
            "model": "i4",
            "battery_kwh": 83.9,
            "connector_type": "CCS2",
            "max_ac_kw": 11.0,
            "max_dc_kw": 205.0,
            "consumption_kwh_100km": 18.0,
        },
        headers={"Authorization": f"Bearer {driver_token}"},
    )
    veh_id = r.json()["id"]

    # Admin CAN view driver's vehicle
    admin_get = client.get(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_get.status_code == 200
    assert admin_get.json()["id"] == veh_id

    # Admin CAN query driver's tenancy scope
    admin_scope = client.get(
        f"/api/v1/accounts/driver-sees-own-data-only?target_user_id={driver_user.id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert admin_scope.status_code == 200

    # Station Operator CANNOT view driver's vehicle
    op_get = client.get(
        f"/api/v1/vehicles/{veh_id}",
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert op_get.status_code == 403





