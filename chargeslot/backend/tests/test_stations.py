"""
Unit and Integration Tests for Station CRUD
Requirement: REQ-F2-01 (Station CRUD)
Story ID: CS19-027
Test Case ID: TC-F2-01
System Test Case ID: STC-F2-01
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
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
        email="alex.operator@example.com",
        phone="+919876543001",
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
        email="sam.competitor@example.com",
        phone="+919876543002",
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
        email="super.admin@example.com",
        phone="+919876543003",
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
        email="dev.driver@example.com",
        phone="+919876543004",
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
def sample_station(db_session: Session, operator_user: User) -> Station:
    station = Station(
        operator_id=operator_user.id,
        name="Indiranagar Fast Charge",
        address="100 Feet Rd, Indiranagar, Bengaluru, Karnataka 560038",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["restroom", "cafe", "wifi", "parking"],
        operating_hours="24 hours",
        contact_phone="+919876543001",
        contact_email="support@electrocharge.in",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


# =========================================================================
# TC-F2-01: Station Creation Tests
# =========================================================================

def test_tc_f2_01_create_station_success(client: TestClient, operator_user: User, db_session: Session):
    """
    TC-F2-01-01: Station Operator can create a station with location, amenities,
    operating hours, and contact details. Initial status is 'pending' (REQ-F2-01, REQ-F2-03).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {
        "name": "Koramangala Supercharger",
        "address": "80 Feet Rd, 4th Block, Koramangala, Bengaluru, Karnataka 560034",
        "latitude": 12.9352,
        "longitude": 77.6245,
        "amenities": ["restroom", "cafe", "parking"],
        "operating_hours": "06:00-23:00",
        "contact_phone": "+919876500001",
        "contact_email": "koramangala@electrocharge.in",
    }
    response = client.post("/api/v1/stations", json=payload, headers=headers)
    assert response.status_code == 201

    data = response.json()
    assert data["name"] == "Koramangala Supercharger"
    assert data["address"] == "80 Feet Rd, 4th Block, Koramangala, Bengaluru, Karnataka 560034"
    assert data["latitude"] == 12.9352
    assert data["longitude"] == 77.6245
    assert data["amenities"] == ["restroom", "cafe", "parking"]
    assert data["operating_hours"] == "06:00-23:00"
    assert data["contact_phone"] == "+919876500001"
    assert data["contact_email"] == "koramangala@electrocharge.in"
    assert data["operator_id"] == operator_user.id
    assert data["status"] == "pending"
    assert data["is_active"] is True

    # Verify database persistence
    station = db_session.query(Station).filter(Station.id == data["id"]).first()
    assert station is not None
    assert station.operator_id == operator_user.id

    # Verify audit log (CS19-014 / REQ-F1-14)
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "STATION_CREATED",
        AuditLog.user_id == operator_user.id,
    ).first()
    assert audit is not None
    assert f"Station:{station.id}" in audit.resource


def test_tc_f2_01_driver_cannot_create_station(client: TestClient, driver_user: User):
    """
    TC-F2-01-02: Driver role cannot create stations; access is rejected with 403 Forbidden.
    """
    headers = {"Authorization": f"Bearer {make_token(driver_user)}"}
    payload = {
        "name": "Illegal Driver Station",
        "address": "Random Rd, City",
        "latitude": 12.9,
        "longitude": 77.6,
        "amenities": [],
        "operating_hours": "24 hours",
        "contact_phone": "+919876500002",
    }
    response = client.post("/api/v1/stations", json=payload, headers=headers)
    assert response.status_code == 403
    assert "Insufficient permissions" in response.json()["detail"]


def test_tc_f2_01_unauthenticated_cannot_create_station(client: TestClient):
    """
    TC-F2-01-03: Unauthenticated access is rejected with 401 Unauthorized.
    """
    payload = {
        "name": "Unauthenticated Station",
        "address": "Random Rd, City",
        "latitude": 12.9,
        "longitude": 77.6,
        "amenities": [],
        "operating_hours": "24 hours",
        "contact_phone": "+919876500003",
    }
    response = client.post("/api/v1/stations", json=payload)
    assert response.status_code == 401


# =========================================================================
# TC-F2-01: Station Retrieval & Scoping Tests
# =========================================================================

def test_tc_f2_01_list_stations_scoped_to_operator(
    client: TestClient,
    operator_user: User,
    foreign_operator: User,
    sample_station: Station,
    db_session: Session,
):
    """
    TC-F2-01-04: Operator sees only their own stations (REQ-F1-12 operator scoping).
    """
    # Seed foreign station
    foreign_station = Station(
        operator_id=foreign_operator.id,
        name="Competitor Station Whitefield",
        address="ITPB Rd, Whitefield, Bengaluru",
        latitude=12.9698,
        longitude=77.7500,
        amenities=["restroom"],
        operating_hours="24 hours",
        contact_phone="+919876500099",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(foreign_station)
    db_session.commit()

    # Operator Alex logs in
    alex_headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    res_alex = client.get("/api/v1/stations", headers=alex_headers)
    assert res_alex.status_code == 200
    alex_data = res_alex.json()
    assert alex_data["total"] == 1
    assert alex_data["items"][0]["id"] == sample_station.id
    assert alex_data["items"][0]["name"] == sample_station.name

    # Foreign operator Sam logs in
    sam_headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    res_sam = client.get("/api/v1/stations", headers=sam_headers)
    assert res_sam.status_code == 200
    sam_data = res_sam.json()
    assert sam_data["total"] == 1
    assert sam_data["items"][0]["id"] == foreign_station.id
    assert sam_data["items"][0]["name"] == foreign_station.name


def test_tc_f2_01_admin_sees_all_stations(
    client: TestClient,
    admin_user: User,
    sample_station: Station,
    foreign_operator: User,
    db_session: Session,
):
    """
    TC-F2-01-05: Administrator has global scope and sees stations across all operators.
    """
    foreign_station = Station(
        operator_id=foreign_operator.id,
        name="Foreign Station",
        address="MG Road, Bengaluru",
        latitude=12.9750,
        longitude=77.6090,
        amenities=[],
        operating_hours="24 hours",
        contact_phone="+919876500088",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(foreign_station)
    db_session.commit()

    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    response = client.get("/api/v1/stations", headers=admin_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["total"] >= 2
    station_ids = [s["id"] for s in data["items"]]
    assert sample_station.id in station_ids
    assert foreign_station.id in station_ids


def test_tc_f2_01_get_station_detail_by_owner(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
):
    """
    TC-F2-01-06: Operator can retrieve details of their own station.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.get(f"/api/v1/stations/{sample_station.id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == sample_station.id
    assert data["name"] == sample_station.name


def test_tc_f2_01_foreign_operator_cannot_get_station_detail(
    client: TestClient,
    foreign_operator: User,
    sample_station: Station,
):
    """
    TC-F2-01-07: Operator cannot view another operator's station details (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    response = client.get(f"/api/v1/stations/{sample_station.id}", headers=headers)
    assert response.status_code == 403
    assert "Access denied" in response.json()["detail"]


# =========================================================================
# TC-F2-01: Station Update Tests
# =========================================================================

def test_tc_f2_01_update_station_success(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
    db_session: Session,
):
    """
    TC-F2-01-08: Operator can update station attributes. Content modification
    resets approval status to 'pending' per REQ-F2-03. Audit log is recorded.
    """
    assert sample_station.status == StationStatus.APPROVED

    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    payload = {
        "name": "Indiranagar Fast Charge & Cafe",
        "operating_hours": "07:00-23:00",
        "amenities": ["restroom", "cafe", "wifi", "parking", "lounge"],
    }
    response = client.put(f"/api/v1/stations/{sample_station.id}", json=payload, headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["name"] == "Indiranagar Fast Charge & Cafe"
    assert data["operating_hours"] == "07:00-23:00"
    assert "lounge" in data["amenities"]
    assert data["status"] == "pending"  # Reset per REQ-F2-03

    # Check audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "STATION_UPDATED",
        AuditLog.resource == f"Station:{sample_station.id}",
    ).first()
    assert audit is not None


def test_tc_f2_01_foreign_operator_cannot_update_station(
    client: TestClient,
    foreign_operator: User,
    sample_station: Station,
):
    """
    TC-F2-01-09: Operator cannot modify another operator's station (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    payload = {"name": "Hacked Station Name"}
    response = client.put(f"/api/v1/stations/{sample_station.id}", json=payload, headers=headers)
    assert response.status_code == 403


# =========================================================================
# TC-F2-01: Station Deactivation Tests
# =========================================================================

def test_tc_f2_01_deactivate_station_success(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
    db_session: Session,
):
    """
    TC-F2-01-10: Operator can deactivate a station. Sets is_active=False and status=INACTIVE.
    Audit log is recorded (REQ-F2-01).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.delete(f"/api/v1/stations/{sample_station.id}", headers=headers)
    assert response.status_code == 200

    data = response.json()
    assert data["message"] == "Station successfully deactivated."
    assert data["station_id"] == sample_station.id
    assert data["is_active"] is False
    assert data["status"] == "inactive"

    db_session.refresh(sample_station)
    assert sample_station.is_active is False
    assert sample_station.status == StationStatus.INACTIVE

    # Check audit log
    audit = db_session.query(AuditLog).filter(
        AuditLog.action == "STATION_DEACTIVATED",
        AuditLog.resource == f"Station:{sample_station.id}",
    ).first()
    assert audit is not None


def test_tc_f2_01_deactivate_station_explicit_action(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
    db_session: Session,
):
    """
    TC-F2-01-11: Explicit POST /deactivate action endpoint also successfully deactivates station.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    response = client.post(f"/api/v1/stations/{sample_station.id}/deactivate", headers=headers)
    assert response.status_code == 200
    assert response.json()["is_active"] is False


def test_tc_f2_01_foreign_operator_cannot_deactivate_station(
    client: TestClient,
    foreign_operator: User,
    sample_station: Station,
):
    """
    TC-F2-01-12: Foreign operator cannot deactivate another operator's station (403 Forbidden).
    """
    headers = {"Authorization": f"Bearer {make_token(foreign_operator)}"}
    response = client.delete(f"/api/v1/stations/{sample_station.id}", headers=headers)
    assert response.status_code == 403


def test_tc_f2_01_nonexistent_station_returns_404(
    client: TestClient,
    operator_user: User,
):
    """
    TC-F2-01-13: Accessing or modifying a non-existent station ID returns 404 Not Found.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}
    assert client.get("/api/v1/stations/99999", headers=headers).status_code == 404
    assert client.put("/api/v1/stations/99999", json={"name": "test"}, headers=headers).status_code == 404
    assert client.delete("/api/v1/stations/99999", headers=headers).status_code == 404


# =========================================================================
# TC-F2-01: Validation & Boundary Tests (Appendix B.4 / REQ-F2-04)
# =========================================================================

def test_tc_f2_01_invalid_coordinates_rejected(client: TestClient, operator_user: User):
    """
    TC-F2-01-14: Coordinates outside valid ranges [-90, 90] and [-180, 180] are rejected with 422.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}

    # Latitude too high (> 90)
    payload_lat = {
        "name": "Invalid Lat Station",
        "address": "North Pole Beyond",
        "latitude": 91.5,
        "longitude": 77.0,
        "operating_hours": "24 hours",
        "contact_phone": "+919876543210",
    }
    res_lat = client.post("/api/v1/stations", json=payload_lat, headers=headers)
    assert res_lat.status_code == 422

    # Longitude too low (< -180)
    payload_lon = {
        "name": "Invalid Lon Station",
        "address": "Out of Bounds",
        "latitude": 12.0,
        "longitude": -185.0,
        "operating_hours": "24 hours",
        "contact_phone": "+919876543210",
    }
    res_lon = client.post("/api/v1/stations", json=payload_lon, headers=headers)
    assert res_lon.status_code == 422


def test_tc_f2_01_missing_mandatory_fields_rejected(client: TestClient, operator_user: User):
    """
    TC-F2-01-15: Missing mandatory fields return 422 Unprocessable Entity.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}

    # Missing address
    payload_no_address = {
        "name": "No Address Station",
        "latitude": 12.0,
        "longitude": 77.0,
        "operating_hours": "24 hours",
        "contact_phone": "+919876543210",
    }
    res = client.post("/api/v1/stations", json=payload_no_address, headers=headers)
    assert res.status_code == 422


def test_tc_f2_01_list_stations_with_filters_and_search(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
    db_session: Session,
):
    """
    TC-F2-01-16: Station listing supports filters by active status, approval status, and text search.
    """
    # Create second station
    s2 = Station(
        operator_id=operator_user.id,
        name="Hebbal Rapid DC",
        address="Bellary Rd, Hebbal, Bengaluru",
        latitude=13.0358,
        longitude=77.5970,
        amenities=["restroom"],
        operating_hours="24 hours",
        contact_phone="+919876543005",
        status=StationStatus.PENDING,
        is_active=False,
    )
    db_session.add(s2)
    db_session.commit()

    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}

    # Filter is_active=true
    res_active = client.get("/api/v1/stations?is_active=true", headers=headers)
    assert res_active.status_code == 200
    assert res_active.json()["total"] == 1
    assert res_active.json()["items"][0]["id"] == sample_station.id

    # Filter status=pending
    res_pending = client.get("/api/v1/stations?status=pending", headers=headers)
    assert res_pending.status_code == 200
    assert res_pending.json()["total"] == 1
    assert res_pending.json()["items"][0]["id"] == s2.id

    # Text search by query "Hebbal"
    res_search = client.get("/api/v1/stations?q=Hebbal", headers=headers)
    assert res_search.status_code == 200
    assert res_search.json()["total"] == 1
    assert res_search.json()["items"][0]["name"] == "Hebbal Rapid DC"


def test_tc_f2_01_update_station_empty_and_deactivate_via_update(
    client: TestClient,
    operator_user: User,
    sample_station: Station,
):
    """
    TC-F2-01-17: Empty update returns current station; updating is_active=False marks inactive.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_user)}"}

    # Empty update
    res_empty = client.put(f"/api/v1/stations/{sample_station.id}", json={}, headers=headers)
    assert res_empty.status_code == 200

    # Update is_active=false
    res_deact = client.put(f"/api/v1/stations/{sample_station.id}", json={"is_active": False}, headers=headers)
    assert res_deact.status_code == 200
    assert res_deact.json()["is_active"] is False
    assert res_deact.json()["status"] == "inactive"

