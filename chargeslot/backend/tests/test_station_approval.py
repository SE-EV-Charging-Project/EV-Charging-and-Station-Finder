"""
Unit and Integration Tests for Station Approval Gate
Requirement: REQ-F2-03 (Station approval gate)
Story ID: CS19-029
Test Case ID: TC-F2-03
System Test Case ID: STC-F2-03
"""

import pytest
from datetime import datetime
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token
from app.stations.moderation import StationModerationService


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        name="Super Admin",
        email="super.admin.approval@example.com",
        phone="+919876543001",
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
def operator_a(db_session: Session) -> User:
    op = User(
        name="Operator Alpha",
        email="alpha.op.approval@example.com",
        phone="+919876543002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Alpha Hubs",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op)
    db_session.commit()
    db_session.refresh(op)
    return op


@pytest.fixture
def operator_b(db_session: Session) -> User:
    op = User(
        name="Operator Beta",
        email="beta.op.approval@example.com",
        phone="+919876543003",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Beta Hubs",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op)
    db_session.commit()
    db_session.refresh(op)
    return op


@pytest.fixture
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Driver Dave",
        email="driver.dave.approval@example.com",
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
def pending_station(db_session: Session, operator_a: User) -> Station:
    station = Station(
        operator_id=operator_a.id,
        name="Whitefield FastCharge Hub",
        address="100 ITPL Main Road, Bangalore",
        latitude=12.9850,
        longitude=77.7300,
        amenities=["Restroom", "Cafe", "WiFi"],
        operating_hours="24 hours",
        contact_phone="+919876543002",
        contact_email="whitefield@alphahubs.com",
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


# ==============================================================================
# TC-F2-03: Unit & Integration Tests (REQ-F2-03 / CS19-029)
# ==============================================================================

def test_tc_f2_03_new_station_hidden_from_drivers_when_pending(
    client: TestClient, operator_a: User, driver_user: User, db_session: Session
):
    """
    TC-F2-03-01: A newly created station has status='pending' and is hidden from drivers (REQ-F2-03).
    """
    op_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    create_payload = {
        "name": "Koramangala EV Spot",
        "address": "4th Block Koramangala, Bangalore",
        "latitude": 12.9352,
        "longitude": 77.6245,
        "amenities": ["Restroom", "WiFi"],
        "operating_hours": "24 hours",
        "contact_phone": "+919876543210",
        "contact_email": "koramangala@alphahubs.com",
    }
    create_res = client.post("/api/v1/stations", json=create_payload, headers=op_headers)
    assert create_res.status_code == 201
    station_data = create_res.json()
    station_id = station_data["id"]
    assert station_data["status"] == "pending"

    # Driver attempts to fetch the pending station -> 404 (hidden from drivers per REQ-F2-03)
    driver_res = client.get(f"/api/v1/stations/{station_id}", headers=driver_headers)
    assert driver_res.status_code == 404
    assert "pending administrative approval" in driver_res.json()["detail"]

    # Driver lists stations -> pending station must NOT appear
    driver_list_res = client.get("/api/v1/stations", headers=driver_headers)
    assert driver_list_res.status_code == 200
    station_ids = [s["id"] for s in driver_list_res.json()["items"]]
    assert station_id not in station_ids


def test_tc_f2_03_admin_approves_station_success(
    client: TestClient, admin_user: User, driver_user: User, pending_station: Station, db_session: Session
):
    """
    TC-F2-03-02: Administrator approves a pending station; it becomes visible to drivers (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    # Admin approves station
    approve_res = client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=admin_headers)
    assert approve_res.status_code == 200
    data = approve_res.json()
    assert data["status"] == "approved"
    assert data["reviewed_by_admin_id"] == admin_user.id
    assert data["reviewed_at"] is not None
    assert data["rejection_reason"] is None
    assert "successfully approved" in data["message"]

    # Audit log created
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "STATION_APPROVED", AuditLog.resource == f"Station:{pending_station.id}")
        .first()
    )
    assert log is not None
    assert log.user_id == admin_user.id

    # Driver can now access the approved station
    driver_res = client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers)
    assert driver_res.status_code == 200
    assert driver_res.json()["name"] == pending_station.name
    assert driver_res.json()["status"] == "approved"

    # Driver sees station in listing
    driver_list_res = client.get("/api/v1/stations", headers=driver_headers)
    assert driver_list_res.status_code == 200
    station_ids = [s["id"] for s in driver_list_res.json()["items"]]
    assert pending_station.id in station_ids


def test_tc_f2_03_edited_station_hidden_from_drivers_until_reapproved(
    client: TestClient, admin_user: User, operator_a: User, driver_user: User, pending_station: Station, db_session: Session
):
    """
    TC-F2-03-03: When an approved station is edited by an operator, its status resets to 'pending'
    and it is hidden from drivers until an Administrator re-approves it (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    op_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    # 1. Admin approves station initially
    client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=admin_headers)

    # Driver confirms station is visible
    assert client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers).status_code == 200

    # 2. Operator edits station name and operating hours
    update_payload = {
        "name": "Whitefield Ultra Charging Complex",
        "operating_hours": "06:00-23:00",
    }
    update_res = client.put(f"/api/v1/stations/{pending_station.id}", json=update_payload, headers=op_headers)
    assert update_res.status_code == 200
    assert update_res.json()["status"] == "pending"

    # 3. Driver attempts to access edited station -> 404 (hidden from drivers!)
    driver_res = client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers)
    assert driver_res.status_code == 404
    assert "pending administrative approval" in driver_res.json()["detail"]

    # 4. Admin re-approves the edited station
    reapprove_res = client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=admin_headers)
    assert reapprove_res.status_code == 200
    assert reapprove_res.json()["status"] == "approved"

    # 5. Driver can access again and sees updated details
    driver_res2 = client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers)
    assert driver_res2.status_code == 200
    assert driver_res2.json()["name"] == "Whitefield Ultra Charging Complex"
    assert driver_res2.json()["operating_hours"] == "06:00-23:00"


def test_tc_f2_03_admin_rejects_station_with_reason(
    client: TestClient, admin_user: User, driver_user: User, pending_station: Station, db_session: Session
):
    """
    TC-F2-03-04: Administrator rejects a station with a reason; station remains hidden from drivers (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    reject_payload = {
        "reason": "Missing mandatory municipal fire and electrical safety clearance documents."
    }
    reject_res = client.post(f"/api/v1/stations/{pending_station.id}/reject", json=reject_payload, headers=admin_headers)
    assert reject_res.status_code == 200
    data = reject_res.json()
    assert data["status"] == "rejected"
    assert data["rejection_reason"] == reject_payload["reason"]
    assert data["reviewed_by_admin_id"] == admin_user.id
    assert data["reviewed_at"] is not None

    # Audit log created
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "STATION_REJECTED", AuditLog.resource == f"Station:{pending_station.id}")
        .first()
    )
    assert log is not None
    assert "Missing mandatory municipal fire" in log.details

    # Driver cannot view rejected station
    driver_res = client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers)
    assert driver_res.status_code == 404


def test_tc_f2_03_reject_without_reason_fails(
    client: TestClient, admin_user: User, pending_station: Station
):
    """
    TC-F2-03-05: Rejecting a station without a reason is rejected with 422 Unprocessable Entity.
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # Blank / whitespace reason
    res = client.post(f"/api/v1/stations/{pending_station.id}/reject", json={"reason": "   "}, headers=admin_headers)
    assert res.status_code == 422

    # Missing reason field
    res2 = client.post(f"/api/v1/stations/{pending_station.id}/reject", json={}, headers=admin_headers)
    assert res2.status_code == 422


def test_tc_f2_03_non_admin_cannot_approve_or_reject(
    client: TestClient, operator_a: User, driver_user: User, pending_station: Station
):
    """
    TC-F2-03-06: Non-administrators (operators, drivers, unauthenticated) are forbidden
    from approving or rejecting stations (403/401).
    """
    op_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    # Operator cannot approve
    assert client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=op_headers).status_code == 403

    # Operator cannot reject
    assert client.post(
        f"/api/v1/stations/{pending_station.id}/reject", json={"reason": "Self rejection"}, headers=op_headers
    ).status_code == 403

    # Driver cannot approve or reject
    assert client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=driver_headers).status_code == 403
    assert client.post(
        f"/api/v1/stations/{pending_station.id}/reject", json={"reason": "Driver rejection"}, headers=driver_headers
    ).status_code == 403

    # Unauthenticated rejected with 401
    assert client.post(f"/api/v1/stations/{pending_station.id}/approve").status_code == 401
    assert client.post(f"/api/v1/stations/{pending_station.id}/reject", json={"reason": "Anon"}).status_code == 401


def test_tc_f2_03_admin_list_pending_stations_queue(
    client: TestClient, admin_user: User, operator_a: User, pending_station: Station, db_session: Session
):
    """
    TC-F2-03-07: Admin can view all pending stations in the moderation queue (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    op_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}

    # Create a second pending station
    s2 = Station(
        operator_id=operator_a.id,
        name="Indiranagar Charging Node",
        address="100 Feet Rd, Indiranagar, Bangalore",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["Restroom"],
        operating_hours="24 hours",
        contact_phone="+919876543002",
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(s2)
    db_session.commit()

    res = client.get("/api/v1/stations/pending-approval", headers=admin_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 2
    pending_ids = [s["id"] for s in data["items"]]
    assert pending_station.id in pending_ids
    assert s2.id in pending_ids

    # Operators cannot access pending approval queue
    assert client.get("/api/v1/stations/pending-approval", headers=op_headers).status_code == 403


def test_tc_f2_03_approval_gate_status_endpoint(
    client: TestClient, admin_user: User, operator_a: User, operator_b: User, pending_station: Station
):
    """
    TC-F2-03-08: Inspect approval gate status via /approval-status endpoint with role enforcement (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    op_a_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    op_b_headers = {"Authorization": f"Bearer {make_token(operator_b)}"}

    # Owner operator can view approval status
    res_a = client.get(f"/api/v1/stations/{pending_station.id}/approval-status", headers=op_a_headers)
    assert res_a.status_code == 200
    assert res_a.json()["visible_to_drivers"] is False
    assert res_a.json()["status"] == "pending"
    assert res_a.json()["can_approve"] is False

    # Foreign operator cannot view approval status (403)
    res_b = client.get(f"/api/v1/stations/{pending_station.id}/approval-status", headers=op_b_headers)
    assert res_b.status_code == 403

    # Admin can view approval status
    res_admin = client.get(f"/api/v1/stations/{pending_station.id}/approval-status", headers=admin_headers)
    assert res_admin.status_code == 200
    assert res_admin.json()["can_approve"] is True


def test_tc_f2_03_architecture_route_station_approval_gate(
    client: TestClient, admin_user: User, pending_station: Station
):
    """
    TC-F2-03-09: Verifies SW Architecture route GET & POST /api/v1/stations/station-approval-gate (Page 6).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}

    # 1. Architecture GET inspection route for specific station
    get_res = client.get(
        f"/api/v1/stations/station-approval-gate?station_id={pending_station.id}", headers=admin_headers
    )
    assert get_res.status_code == 200
    assert get_res.json()["station_id"] == pending_station.id
    assert get_res.json()["visible_to_drivers"] is False

    # 2. Architecture GET inspection route queue
    get_res_all = client.get("/api/v1/stations/station-approval-gate", headers=admin_headers)
    assert get_res_all.status_code == 200
    assert "items" in get_res_all.json()

    # 3. Architecture POST approval action
    post_res = client.post(
        "/api/v1/stations/station-approval-gate",
        json={"station_id": pending_station.id, "action": "approve"},
        headers=admin_headers,
    )
    assert post_res.status_code == 200
    assert post_res.json()["status"] == "approved"

    # 4. Architecture POST rejection action
    post_res2 = client.post(
        "/api/v1/stations/station-approval-gate",
        json={"station_id": pending_station.id, "action": "reject", "reason": "Requires inspection renewal."},
        headers=admin_headers,
    )
    assert post_res2.status_code == 200
    assert post_res2.json()["status"] == "rejected"

    # 5. Invalid action returns 400
    post_bad = client.post(
        "/api/v1/stations/station-approval-gate",
        json={"station_id": pending_station.id, "action": "unknown_action"},
        headers=admin_headers,
    )
    assert post_bad.status_code == 400


def test_tc_f2_03_inactive_station_hidden_from_drivers_even_if_approved(
    client: TestClient, admin_user: User, operator_a: User, driver_user: User, pending_station: Station
):
    """
    TC-F2-03-10: An approved station that is deactivated (is_active=False) remains hidden from drivers (REQ-F2-03).
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    op_headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}

    # Approve station
    client.post(f"/api/v1/stations/{pending_station.id}/approve", headers=admin_headers)
    assert client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers).status_code == 200

    # Operator deactivates station
    deact_res = client.delete(f"/api/v1/stations/{pending_station.id}", headers=op_headers)
    assert deact_res.status_code == 200
    assert deact_res.json()["is_active"] is False

    # Driver attempts to access deactivated station -> 404 (hidden)
    driver_res = client.get(f"/api/v1/stations/{pending_station.id}", headers=driver_headers)
    assert driver_res.status_code == 404


def test_tc_f2_03_moderation_service_unit_edge_cases(
    db_session: Session, admin_user: User, operator_a: User, pending_station: Station
):
    """
    TC-F2-03-11: Direct unit tests on StationModerationService for exception handling and boundaries.
    """
    # 1. Non-admin approving raises 403
    with pytest.raises(Exception) as exc:
        StationModerationService.approve_station(db_session, admin=operator_a, station_id=pending_station.id)
    assert exc.value.status_code == 403

    # 2. Non-admin rejecting raises 403
    with pytest.raises(Exception) as exc:
        StationModerationService.reject_station(db_session, admin=operator_a, station_id=pending_station.id, reason="Bad")
    assert exc.value.status_code == 403

    # 3. Nonexistent station raises 404
    with pytest.raises(Exception) as exc:
        StationModerationService.approve_station(db_session, admin=admin_user, station_id=999999)
    assert exc.value.status_code == 404

    with pytest.raises(Exception) as exc:
        StationModerationService.reject_station(db_session, admin=admin_user, station_id=999999, reason="Bad")
    assert exc.value.status_code == 404

    # 4. Empty rejection reason raises 422
    with pytest.raises(Exception) as exc:
        StationModerationService.reject_station(db_session, admin=admin_user, station_id=pending_station.id, reason="   ")
    assert exc.value.status_code == 422
