"""
Unit and Integration Tests for Charger and Connector CRUD
Requirement: REQ-F2-02 (Charger and connector CRUD)
Story ID: CS19-028
Test Case ID: TC-F2-02
System Test Case ID: STC-F2-02
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def operator_user(db_session: Session) -> User:
    operator = User(
        name="Alex Operator",
        email="alex.op.chargers@example.com",
        phone="+919876541001",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="ElectroCharge Hubs",
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    db_session.refresh(operator)
    return operator


@pytest.fixture
def foreign_operator(db_session: Session) -> User:
    operator = User(
        name="Sam Competitor",
        email="sam.foreign.chargers@example.com",
        phone="+919876541002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="VoltNetwork",
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.commit()
    db_session.refresh(operator)
    return operator


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        name="Super Admin",
        email="super.admin.chargers@example.com",
        phone="+919876541003",
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
        name="Dev Driver",
        email="dev.driver.chargers@example.com",
        phone="+919876541004",
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
def operator_station(db_session: Session, operator_user: User) -> Station:
    station = Station(
        operator_id=operator_user.id,
        name="Indiranagar Fast Charge Hub",
        address="100 Feet Rd, Indiranagar, Bengaluru",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["restroom", "cafe", "wifi"],
        operating_hours="24 hours",
        contact_phone="+919876541001",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def foreign_station(db_session: Session, foreign_operator: User) -> Station:
    station = Station(
        operator_id=foreign_operator.id,
        name="Whitefield Competitor Plaza",
        address="ITPB Rd, Whitefield, Bengaluru",
        latitude=12.9698,
        longitude=77.7500,
        amenities=["parking"],
        operating_hours="24 hours",
        contact_phone="+919876541002",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def sample_charger(db_session: Session, operator_station: Station) -> Charger:
    charger = Charger(
        station_id=operator_station.id,
        name="Fast Charger Unit 1",
        power_kw=150.0,
        current_type=CurrentType.DC,
        gateway_id="OCPP-BLR-001",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector1 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    connector2 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CHADEMO,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add_all([connector1, connector2])
    db_session.commit()
    db_session.refresh(charger)
    return charger


# =========================================================================
# TC-F2-02: Charger Creation Tests
# =========================================================================

def test_tc_f2_02_add_charger_to_station_success(
    client: TestClient, operator_user: User, operator_station: Station, db_session: Session
):
    """
    TC-F2-02-01: Operator can add a charger with power rating, current type,
    gateway identifier, and connectors to their station (REQ-F2-02).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {
        "name": "Super Fast DC 240",
        "power_kw": 240.0,
        "current_type": "DC",
        "gateway_id": "OCPP-INDR-002",
        "connectors": [
            {"connector_type": "CCS2"},
            {"connector_type": "GB/T"},
        ],
    }
    response = client.post(f"/api/v1/stations/{operator_station.id}/chargers", json=payload, headers=headers)
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Super Fast DC 240"
    assert data["power_kw"] == 240.0
    assert data["current_type"] == "DC"
    assert data["gateway_id"] == "OCPP-INDR-002"
    assert data["station_id"] == operator_station.id
    assert data["is_active"] is True
    assert len(data["connectors"]) == 2

    # Verify connectors saved
    conn_types = [c["connector_type"] for c in data["connectors"]]
    assert "CCS2" in conn_types
    assert "GB/T" in conn_types

    # Verify audit log (REQ-F1-14)
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "CHARGER_CREATED",
        AuditLog.user_id == operator_user.id,
    ).first()
    assert audit is not None
    assert f"Charger:{data['id']}" in audit.resource


def test_tc_f2_02_add_charger_to_foreign_station_denied(
    client: TestClient, operator_user: User, foreign_station: Station
):
    """
    TC-F2-02-02: Operator cannot add a charger to another operator's station (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {
        "name": "Illegal Charger",
        "power_kw": 50.0,
        "current_type": "AC",
        "gateway_id": "GW-HACK-001",
        "connectors": [{"connector_type": "Type 2"}],
    }
    response = client.post(f"/api/v1/stations/{foreign_station.id}/chargers", json=payload, headers=headers)
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


def test_tc_f2_02_driver_cannot_add_charger(
    client: TestClient, driver_user: User, operator_station: Station
):
    """
    TC-F2-02-03: Driver role is forbidden from adding chargers (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(driver_user)}"}
    payload = {
        "power_kw": 22.0,
        "current_type": "AC",
        "gateway_id": "GW-DRIVER-001",
    }
    response = client.post(f"/api/v1/stations/{operator_station.id}/chargers", json=payload, headers=headers)
    assert response.status_code == 403


# =========================================================================
# TC-F2-02: Charger Retrieval & Scoping Tests
# =========================================================================

def test_tc_f2_02_list_station_chargers(
    client: TestClient, operator_user: User, operator_station: Station, sample_charger: Charger
):
    """
    TC-F2-02-04: Operator can list all chargers belonging to their station.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.get(f"/api/v1/stations/{operator_station.id}/chargers", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == sample_charger.id
    assert data["items"][0]["power_kw"] == 150.0
    assert len(data["items"][0]["connectors"]) == 2


def test_tc_f2_02_get_charger_details(
    client: TestClient, operator_user: User, sample_charger: Charger
):
    """
    TC-F2-02-05: Operator can view details of their charger.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.get(f"/api/v1/chargers/{sample_charger.id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == sample_charger.id
    assert response.json()["gateway_id"] == sample_charger.gateway_id


def test_tc_f2_02_foreign_operator_cannot_view_charger(
    client: TestClient, foreign_operator: User, sample_charger: Charger
):
    """
    TC-F2-02-06: Operator cannot access another operator's charger (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    response = client.get(f"/api/v1/chargers/{sample_charger.id}", headers=headers)
    assert response.status_code == 403


# =========================================================================
# TC-F2-02: Charger Update & Deletion Tests
# =========================================================================

def test_tc_f2_02_update_charger_success(
    client: TestClient, operator_user: User, sample_charger: Charger, db_session: Session
):
    """
    TC-F2-02-07: Operator can edit charger power rating, current type, or gateway ID (REQ-F2-02).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {
        "name": "Upgraded Fast Charger 180",
        "power_kw": 180.0,
        "gateway_id": "OCPP-BLR-001-V2",
    }
    response = client.put(f"/api/v1/chargers/{sample_charger.id}", json=payload, headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Upgraded Fast Charger 180"
    assert data["power_kw"] == 180.0
    assert data["gateway_id"] == "OCPP-BLR-001-V2"

    # Verify audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "CHARGER_UPDATED",
        AuditLog.resource == f"Charger:{sample_charger.id}",
    ).first()
    assert audit is not None


def test_tc_f2_02_foreign_operator_cannot_update_charger(
    client: TestClient, foreign_operator: User, sample_charger: Charger
):
    """
    TC-F2-02-08: Operator cannot modify another operator's charger (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    response = client.put(f"/api/v1/chargers/{sample_charger.id}", json={"power_kw": 60.0}, headers=headers)
    assert response.status_code == 403


def test_tc_f2_02_remove_charger_success(
    client: TestClient, operator_user: User, sample_charger: Charger, db_session: Session
):
    """
    TC-F2-02-09: Operator can remove a charger and its attached connectors (REQ-F2-02).
    """
    cid = sample_charger.id
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.delete(f"/api/v1/chargers/{cid}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == cid

    # Verify deleted from database
    assert db_session.query(Charger).filter(Charger.id == cid).first() is None
    # Verify child connectors cascaded
    assert db_session.query(Connector).filter(Connector.charger_id == cid).count() == 0

    # Verify audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "CHARGER_DELETED",
        AuditLog.resource == f"Charger:{cid}",
    ).first()
    assert audit is not None


# =========================================================================
# TC-F2-02: Connector CRUD Tests
# =========================================================================

def test_tc_f2_02_add_connector_to_charger(
    client: TestClient, operator_user: User, sample_charger: Charger, db_session: Session
):
    """
    TC-F2-02-10: Operator can attach a new connector to an existing charger (REQ-F2-02).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {"connector_type": "Type 2"}
    response = client.post(f"/api/v1/chargers/{sample_charger.id}/connectors", json=payload, headers=headers)
    assert response.status_code == 201

    data = response.json()
    assert data["connector_type"] == "Type 2"
    assert data["status"] == "Available"
    assert data["charger_id"] == sample_charger.id

    # Verify in DB
    conn = db_session.query(Connector).filter(Connector.id == data["id"]).first()
    assert conn is not None
    assert conn.connector_type == ConnectorType.TYPE_2


def test_tc_f2_02_update_connector(
    client: TestClient, operator_user: User, sample_charger: Charger, db_session: Session
):
    """
    TC-F2-02-11: Operator can update connector type or status (REQ-F2-02).
    """
    conn = sample_charger.connectors[0]
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {"connector_type": "GB/T", "status": "Faulted"}
    response = client.put(f"/api/v1/connectors/{conn.id}", json=payload, headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["connector_type"] == "GB/T"
    assert data["status"] == "Faulted"


def test_tc_f2_02_remove_connector(
    client: TestClient, operator_user: User, sample_charger: Charger, db_session: Session
):
    """
    TC-F2-02-12: Operator can remove an individual connector from a charger (REQ-F2-02).
    """
    conn = sample_charger.connectors[0]
    conn_id = conn.id
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.delete(f"/api/v1/connectors/{conn_id}", headers=headers)
    assert response.status_code == 200
    assert response.json()["id"] == conn_id

    # Verify deleted
    assert db_session.query(Connector).filter(Connector.id == conn_id).first() is None


def test_tc_f2_02_foreign_operator_cannot_manage_connector(
    client: TestClient, foreign_operator: User, sample_charger: Charger
):
    """
    TC-F2-02-13: Foreign operator cannot add, edit, or remove another operator's connectors (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    conn = sample_charger.connectors[0]

    # Add connector denied
    res_add = client.post(f"/api/v1/chargers/{sample_charger.id}/connectors", json={"connector_type": "Type 2"}, headers=headers)
    assert res_add.status_code == 403

    # Update connector denied
    res_up = client.put(f"/api/v1/connectors/{conn.id}", json={"status": "Occupied"}, headers=headers)
    assert res_up.status_code == 403

    # Delete connector denied
    res_del = client.delete(f"/api/v1/connectors/{conn.id}", headers=headers)
    assert res_del.status_code == 403


# =========================================================================
# TC-F2-02: Validation & Error Handling Tests (REQ-F2-04 integration)
# =========================================================================

def test_tc_f2_02_invalid_charger_power_rejected(
    client: TestClient, operator_user: User, operator_station: Station
):
    """
    TC-F2-02-14: Power rating out of range [1.0, 400.0] is rejected with 422.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    for bad_power in [0.0, 500.0]:
        payload = {
            "power_kw": bad_power,
            "current_type": "AC",
            "gateway_id": "GW-TEST-001",
        }
        res = client.post(f"/api/v1/stations/{operator_station.id}/chargers", json=payload, headers=headers)
        assert res.status_code == 422


def test_tc_f2_02_nonexistent_station_or_charger_returns_404(
    client: TestClient, operator_user: User
):
    """
    TC-F2-02-15: Non-existent station, charger, or connector IDs return 404 Not Found.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    assert client.get("/api/v1/chargers/99999", headers=headers).status_code == 404
    assert client.put("/api/v1/chargers/99999", json={"power_kw": 50.0}, headers=headers).status_code == 404
    assert client.delete("/api/v1/chargers/99999", headers=headers).status_code == 404
    assert client.delete("/api/v1/connectors/99999", headers=headers).status_code == 404
    assert client.put("/api/v1/connectors/99999", json={"status": "Faulted"}, headers=headers).status_code == 404
