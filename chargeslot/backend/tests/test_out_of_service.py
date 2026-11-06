"""
Unit and Integration Tests for Out-of-Service Marking
Requirement: REQ-F2-05 (Out-of-service marking)
Story ID: CS19-031
Test Case ID: TC-F2-05
System Test Case ID: STC-F2-05
"""

import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token
from app.services.charger_service import ChargerService


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def admin_user(db_session: Session) -> User:
    admin = User(
        name="Chief Admin",
        email="chief.admin.oos@example.com",
        phone="+919876544001",
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
        name="Operator North",
        email="north.op.oos@example.com",
        phone="+919876544002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="North Chargers",
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
        name="Operator South",
        email="south.op.oos@example.com",
        phone="+919876544003",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="South Chargers",
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
        name="Driver Diana",
        email="driver.diana.oos@example.com",
        phone="+919876544004",
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
def operator_station(db_session: Session, operator_a: User) -> Station:
    station = Station(
        operator_id=operator_a.id,
        name="North Gateway Superstation",
        address="10 Airport Road, Bangalore",
        latitude=13.1986,
        longitude=77.7066,
        amenities=["Restroom", "Cafe", "Lounge"],
        operating_hours="24 hours",
        contact_phone="+919876544002",
        contact_email="airport@northchargers.com",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def test_charger(db_session: Session, operator_station: Station) -> Charger:
    charger = Charger(
        station_id=operator_station.id,
        name="DC Fast Unit 01",
        power_kw=150.0,
        current_type=CurrentType.DC,
        gateway_id="OCPP-BLR-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    conn1 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    conn2 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CHADEMO,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add_all([conn1, conn2])
    db_session.commit()
    db_session.refresh(charger)
    return charger


# ==============================================================================
# TC-F2-05: Unit & Integration Tests (REQ-F2-05 / CS19-031)
# ==============================================================================

def test_tc_f2_05_operator_mark_charger_out_of_service_success(
    client: TestClient, operator_a: User, test_charger: Charger, db_session: Session
):
    """
    TC-F2-05-01: Operator marks charger out of service with mandatory reason and expected return time (REQ-F2-05).
    Verifies child connectors are set to Offline and audit log is created.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    return_time = datetime.now(timezone.utc) + timedelta(days=2, hours=3)

    payload = {
        "reason": "Scheduled inverter capacitor replacement and firmware upgrade.",
        "expected_return_time": return_time.isoformat(),
    }
    response = client.patch(f"/api/v1/chargers/{test_charger.id}/out-of-service", json=payload, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["is_out_of_service"] is True
    assert data["out_of_service_reason"] == payload["reason"]
    assert data["expected_return_time"] is not None
    assert data["affected_connectors_count"] == 2
    assert "marked out of service" in data["message"]

    # Verify database state
    db_session.refresh(test_charger)
    assert test_charger.is_out_of_service is True
    assert test_charger.out_of_service_reason == payload["reason"]
    assert test_charger.out_of_service_at is not None
    for conn in test_charger.connectors:
        assert conn.status == ConnectorStatus.OFFLINE

    # Verify audit log
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "CHARGER_MARKED_OUT_OF_SERVICE", AuditLog.resource == f"Charger:{test_charger.id}")
        .first()
    )
    assert log is not None
    assert log.user_id == operator_a.id
    assert "inverter capacitor replacement" in log.details


def test_tc_f2_05_operator_return_charger_to_service_success(
    client: TestClient, operator_a: User, test_charger: Charger, db_session: Session
):
    """
    TC-F2-05-02: Operator returns an out-of-service charger back to operational service (REQ-F2-05).
    Verifies child connectors are restored to Available and audit log is created.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}

    # First mark out of service
    return_time = datetime.now(timezone.utc) + timedelta(hours=5)
    client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service",
        json={"reason": "Cable maintenance", "expected_return_time": return_time.isoformat()},
        headers=headers,
    )

    # Return to service
    restore_res = client.patch(
        f"/api/v1/chargers/{test_charger.id}/return-to-service",
        json={"note": "New cables installed and safety tested."},
        headers=headers,
    )
    assert restore_res.status_code == 200
    data = restore_res.json()
    assert data["is_out_of_service"] is False
    assert data["out_of_service_reason"] is None
    assert data["expected_return_time"] is None
    assert data["out_of_service_at"] is None
    assert "returned to active service" in data["message"]

    # Verify database connectors restored
    db_session.refresh(test_charger)
    for conn in test_charger.connectors:
        assert conn.status == ConnectorStatus.AVAILABLE

    # Verify audit log
    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "CHARGER_RETURNED_TO_SERVICE", AuditLog.resource == f"Charger:{test_charger.id}")
        .first()
    )
    assert log is not None
    assert "safety tested" in log.details


def test_tc_f2_05_past_expected_return_time_rejected(
    client: TestClient, operator_a: User, test_charger: Charger
):
    """
    TC-F2-05-03: Marking out of service with a past expected return time is rejected with 422 (REQ-F2-05).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    past_time = datetime.now(timezone.utc) - timedelta(hours=2)

    payload = {
        "reason": "Routine diagnostics",
        "expected_return_time": past_time.isoformat(),
    }
    response = client.patch(f"/api/v1/chargers/{test_charger.id}/out-of-service", json=payload, headers=headers)
    assert response.status_code == 422
    assert "future timestamp" in response.json()["detail"]


def test_tc_f2_05_empty_or_too_short_reason_rejected(
    client: TestClient, operator_a: User, test_charger: Charger
):
    """
    TC-F2-05-04: Out-of-service reason must be non-empty and at least 3 characters (REQ-F2-05).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    future_time = datetime.now(timezone.utc) + timedelta(days=1)

    # Empty whitespace reason
    res_empty = client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service",
        json={"reason": "   ", "expected_return_time": future_time.isoformat()},
        headers=headers,
    )
    assert res_empty.status_code == 422

    # Too short (< 3 chars)
    res_short = client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service",
        json={"reason": "ab", "expected_return_time": future_time.isoformat()},
        headers=headers,
    )
    assert res_short.status_code == 422


def test_tc_f2_05_foreign_operator_forbidden(
    client: TestClient, operator_b: User, test_charger: Charger
):
    """
    TC-F2-05-05: Operator B cannot mark Operator A's charger out of service (403 Forbidden / REQ-F1-12).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_b)}"}
    future_time = datetime.now(timezone.utc) + timedelta(days=1)

    payload = {
        "reason": "Hostile takeover maintenance",
        "expected_return_time": future_time.isoformat(),
    }
    response = client.patch(f"/api/v1/chargers/{test_charger.id}/out-of-service", json=payload, headers=headers)
    assert response.status_code == 403
    assert "restricted to their own stations" in response.json()["detail"]


def test_tc_f2_05_driver_and_unauthenticated_forbidden(
    client: TestClient, driver_user: User, test_charger: Charger
):
    """
    TC-F2-05-06: Drivers and unauthenticated users cannot manage out-of-service marking (403/401).
    """
    driver_headers = {"Authorization": f"Bearer {make_token(driver_user)}"}
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    payload = {"reason": "Driver meddling", "expected_return_time": future_time.isoformat()}

    # Driver forbidden
    assert client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service", json=payload, headers=driver_headers
    ).status_code == 403

    # Unauthenticated rejected
    assert client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service", json=payload
    ).status_code == 401


def test_tc_f2_05_admin_can_mark_and_return_service(
    client: TestClient, admin_user: User, test_charger: Charger
):
    """
    TC-F2-05-07: Administrator has global scope to mark any charger out of service and restore it.
    """
    admin_headers = {"Authorization": f"Bearer {make_token(admin_user)}"}
    future_time = datetime.now(timezone.utc) + timedelta(hours=6)

    # Admin marks out of service
    res1 = client.patch(
        f"/api/v1/chargers/{test_charger.id}/out-of-service",
        json={"reason": "Grid safety compliance inspection by Admin", "expected_return_time": future_time.isoformat()},
        headers=admin_headers,
    )
    assert res1.status_code == 200
    assert res1.json()["is_out_of_service"] is True

    # Admin restores to service
    res2 = client.patch(
        f"/api/v1/chargers/{test_charger.id}/return-to-service",
        json={"note": "Inspection cleared by Admin."},
        headers=admin_headers,
    )
    assert res2.status_code == 200
    assert res2.json()["is_out_of_service"] is False


def test_tc_f2_05_architecture_route_out_of_service_marking(
    client: TestClient, operator_a: User, test_charger: Charger
):
    """
    TC-F2-05-08: Verifies SW Architecture route PATCH & GET /api/v1/stations/out-of-service-marking (Page 6).
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    future_time = datetime.now(timezone.utc) + timedelta(days=3)

    # 1. SW Architecture PATCH to mark out of service
    patch_payload = {
        "charger_id": test_charger.id,
        "is_out_of_service": True,
        "reason": "Emergency transformer cooldown",
        "expected_return_time": future_time.isoformat(),
    }
    patch_res = client.patch("/api/v1/stations/out-of-service-marking", json=patch_payload, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["is_out_of_service"] is True
    assert patch_res.json()["out_of_service_reason"] == "Emergency transformer cooldown"

    # 2. SW Architecture GET to inspect status
    get_res = client.get(
        f"/api/v1/stations/out-of-service-marking?charger_id={test_charger.id}", headers=headers
    )
    assert get_res.status_code == 200
    assert get_res.json()["is_out_of_service"] is True

    # 3. SW Architecture PATCH to return to service
    patch_restore = {
        "charger_id": test_charger.id,
        "is_out_of_service": False,
        "reason": "Cooldown complete.",
    }
    restore_res = client.patch("/api/v1/stations/out-of-service-marking", json=patch_restore, headers=headers)
    assert restore_res.status_code == 200
    assert restore_res.json()["is_out_of_service"] is False


def test_tc_f2_05_get_out_of_service_status_endpoint(
    client: TestClient, operator_a: User, test_charger: Charger
):
    """
    TC-F2-05-09: Direct inspection via GET /api/v1/chargers/{charger_id}/out-of-service.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    res = client.get(f"/api/v1/chargers/{test_charger.id}/out-of-service", headers=headers)
    assert res.status_code == 200
    assert res.json()["charger_id"] == test_charger.id
    assert res.json()["is_out_of_service"] is False
    assert "in active operational service" in res.json()["message"]


def test_tc_f2_05_nonexistent_charger_returns_404(
    client: TestClient, operator_a: User
):
    """
    TC-F2-05-10: Attempting to mark a nonexistent charger returns 404 Not Found.
    """
    headers = {"Authorization": f"Bearer {make_token(operator_a)}"}
    future_time = datetime.now(timezone.utc) + timedelta(days=1)
    payload = {"reason": "Nonexistent", "expected_return_time": future_time.isoformat()}
    assert client.patch("/api/v1/chargers/999999/out-of-service", json=payload, headers=headers).status_code == 404
    assert client.patch("/api/v1/chargers/999999/return-to-service", headers=headers).status_code == 404


def test_tc_f2_05_direct_service_unit_tests(
    db_session: Session, operator_a: User, operator_b: User, test_charger: Charger
):
    """
    TC-F2-05-11: Direct unit tests for ChargerService out-of-service methods and edge cases.
    """
    future_time = datetime.now(timezone.utc) + timedelta(hours=4)

    # 1. Foreign operator unit exception
    with pytest.raises(Exception) as exc1:
        ChargerService.mark_out_of_service(
            db=db_session,
            user=operator_b,
            charger_id=test_charger.id,
            reason="Illegal",
            expected_return_time=future_time,
        )
    assert exc1.value.status_code == 403

    # 2. Nonexistent charger unit exception
    with pytest.raises(Exception) as exc2:
        ChargerService.mark_out_of_service(
            db=db_session,
            user=operator_a,
            charger_id=999999,
            reason="Illegal",
            expected_return_time=future_time,
        )
    assert exc2.value.status_code == 404

    # 3. Successful unit mark and return
    c, aff = ChargerService.mark_out_of_service(
        db=db_session,
        user=operator_a,
        charger_id=test_charger.id,
        reason="Unit test servicing",
        expected_return_time=future_time,
    )
    assert c.is_out_of_service is True
    assert aff == 2

    c2, aff2 = ChargerService.return_to_service(
        db=db_session,
        user=operator_a,
        charger_id=test_charger.id,
        note="Unit restore",
    )
    assert c2.is_out_of_service is False
    assert aff2 == 2
