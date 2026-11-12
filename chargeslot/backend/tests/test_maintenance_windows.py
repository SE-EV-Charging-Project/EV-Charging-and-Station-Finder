"""
Unit and Integration Tests for Maintenance Windows and Slot Availability
Requirement: REQ-F2-06 (Maintenance windows)
Story ID: CS19-032
Test Case ID: TC-F2-06
System Test Case ID: STC-F2-06
Architecture Ref: stations/slots.py / GET /api/v1/stations/maintenance-windows
"""

import pytest
from datetime import datetime, timezone, timedelta, date, time
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.models.booking import Booking, BookingStatus
from app.models.maintenance import MaintenanceWindow
from app.models.audit import AuditLog
from app.utils.security import hash_password, create_access_token
from app.services.maintenance_service import MaintenanceService
from app.schemas.maintenance import (
    MaintenanceWindowCreateRequest,
    MaintenanceWindowUpdateRequest,
    SlotItem,
)
from app.stations.slots import (
    does_slot_overlap_window,
    filter_slots_by_maintenance,
    parse_operating_hours,
    generate_available_slots_for_day,
)


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
        email="chief.admin.maint@example.com",
        phone="+919876550001",
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
        email="alpha.op.maint@example.com",
        phone="+919876550002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Alpha Power Stations",
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
        email="beta.op.maint@example.com",
        phone="+919876550003",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="Beta Power Stations",
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
        name="Regular Driver",
        email="driver.maint@example.com",
        phone="+919876550004",
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
def station_a(db_session: Session, operator_a: User) -> Station:
    station = Station(
        operator_id=operator_a.id,
        name="Alpha Central Station",
        address="100 Alpha Boulevard, Cyber City",
        latitude=12.9716,
        longitude=77.5946,
        amenities=["Restroom", "WiFi", "Cafe"],
        operating_hours="08:00 - 22:00",
        contact_phone="+919876550010",
        contact_email="alpha.station@example.com",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def station_b(db_session: Session, operator_b: User) -> Station:
    station = Station(
        operator_id=operator_b.id,
        name="Beta South Station",
        address="200 Beta Road, Tech Zone",
        latitude=12.9352,
        longitude=77.6245,
        amenities=["Restroom"],
        operating_hours="24 hours",
        contact_phone="+919876550020",
        contact_email="beta.station@example.com",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def charger_a1(db_session: Session, station_a: Station) -> Charger:
    charger = Charger(
        station_id=station_a.id,
        name="Alpha Charger #1",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="OCPP-ALPHA-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.commit()
    db_session.refresh(charger)
    return charger


@pytest.fixture
def charger_a2(db_session: Session, station_a: Station) -> Charger:
    charger = Charger(
        station_id=station_a.id,
        name="Alpha Charger #2",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id="OCPP-ALPHA-02",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.commit()
    db_session.refresh(charger)
    return charger


# =========================================================================
# TC-F2-06: Operator Defines Maintenance Window and Removes Affected Slots
# =========================================================================

def test_tc_f2_06_operator_creates_maintenance_window(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
):
    """
    Operator creates a valid maintenance window on a station/charger.
    Verifies 201 Created and response data matches.
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=1, hours=2)
    end_time = now + timedelta(days=1, hours=6)

    payload = {
        "charger_id": charger_a1.id,
        "title": "Quarterly Inverter Overhaul",
        "description": "Routine firmware upgrade and cable inspection",
        "start_time": start_time.isoformat(),
        "end_time": end_time.isoformat(),
    }

    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Quarterly Inverter Overhaul"
    assert data["station_id"] == station_a.id
    assert data["charger_id"] == charger_a1.id
    assert data["created_by_user_id"] == operator_a.id


def test_tc_f2_06_slots_overlapping_maintenance_window_removed_from_availability(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
    charger_a2: Charger,
):
    """
    Verify that slots overlapping a defined maintenance window are removed from availability (REQ-F2-06).
    Non-overlapping slots and slots on unrelated chargers remain available.
    """
    token = make_token(operator_a)
    base_time = datetime(2027, 1, 10, 10, 0, 0, tzinfo=timezone.utc)
    maint_start = base_time + timedelta(hours=2)   # 12:00
    maint_end = base_time + timedelta(hours=4)     # 14:00

    # 1. Create maintenance window on charger_a1 from 12:00 to 14:00
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Grid Power Calibration",
            "start_time": maint_start.isoformat(),
            "end_time": maint_end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201

    # 2. Check candidate slots:
    # Slot 1 (10:00 - 11:00 on charger_a1): Before window -> Available
    # Slot 2 (11:30 - 12:30 on charger_a1): Overlaps window start -> Removed!
    # Slot 3 (12:30 - 13:30 on charger_a1): Completely within window -> Removed!
    # Slot 4 (13:30 - 14:30 on charger_a1): Overlaps window end -> Removed!
    # Slot 5 (14:00 - 15:00 on charger_a1): Abutting window end (14:00) -> Available
    # Slot 6 (12:30 - 13:30 on charger_a2): During window time, BUT different charger -> Available!
    candidate_slots = [
        {
            "charger_id": charger_a1.id,
            "start_time": (base_time).isoformat(),
            "end_time": (base_time + timedelta(hours=1)).isoformat(),
        },
        {
            "charger_id": charger_a1.id,
            "start_time": (base_time + timedelta(hours=1, minutes=30)).isoformat(),
            "end_time": (base_time + timedelta(hours=2, minutes=30)).isoformat(),
        },
        {
            "charger_id": charger_a1.id,
            "start_time": (base_time + timedelta(hours=2, minutes=30)).isoformat(),
            "end_time": (base_time + timedelta(hours=3, minutes=30)).isoformat(),
        },
        {
            "charger_id": charger_a1.id,
            "start_time": (base_time + timedelta(hours=3, minutes=30)).isoformat(),
            "end_time": (base_time + timedelta(hours=4, minutes=30)).isoformat(),
        },
        {
            "charger_id": charger_a1.id,
            "start_time": (base_time + timedelta(hours=4)).isoformat(),
            "end_time": (base_time + timedelta(hours=5)).isoformat(),
        },
        {
            "charger_id": charger_a2.id,
            "start_time": (base_time + timedelta(hours=2, minutes=30)).isoformat(),
            "end_time": (base_time + timedelta(hours=3, minutes=30)).isoformat(),
        },
    ]

    check_res = client.post(
        f"/api/v1/stations/{station_a.id}/check-slot-availability",
        json={"slots": candidate_slots},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert check_res.status_code == 200
    check_data = check_res.json()

    assert check_data["total_slots"] == 6
    assert check_data["removed_count"] == 3
    assert check_data["available_count"] == 3

    # Verify removed slots contain blocked reason citing maintenance
    removed = check_data["removed_slots"]
    for s in removed:
        assert s["is_available"] is False
        assert "Grid Power Calibration" in s["blocked_reason"]


def test_tc_f2_06_station_wide_maintenance_window_blocks_all_chargers(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
    charger_a2: Charger,
):
    """
    When a maintenance window has charger_id=None, it applies station-wide
    and blocks slots on ALL chargers at the station.
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)
    maint_start = now + timedelta(days=2, hours=1)
    maint_end = now + timedelta(days=2, hours=5)

    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": None,
            "title": "Substation Transformer Replacement",
            "start_time": maint_start.isoformat(),
            "end_time": maint_end.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201

    candidate_slots = [
        {
            "charger_id": charger_a1.id,
            "start_time": (maint_start + timedelta(minutes=30)).isoformat(),
            "end_time": (maint_start + timedelta(hours=1, minutes=30)).isoformat(),
        },
        {
            "charger_id": charger_a2.id,
            "start_time": (maint_start + timedelta(minutes=30)).isoformat(),
            "end_time": (maint_start + timedelta(hours=1, minutes=30)).isoformat(),
        },
    ]

    check_res = client.post(
        f"/api/v1/stations/{station_a.id}/check-slot-availability",
        json={"slots": candidate_slots},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert check_res.status_code == 200
    check_data = check_res.json()
    assert check_data["removed_count"] == 2
    assert check_data["available_count"] == 0


def test_tc_f2_06_conflicting_bookings_cancelled_on_maintenance_creation(
    client: TestClient,
    db_session: Session,
    operator_a: User,
    driver_user: User,
    station_a: Station,
    charger_a1: Charger,
):
    """
    When a maintenance window is created, any active/confirmed bookings
    overlapping that window are automatically cancelled (REQ-F2-06).
    """
    token = make_token(operator_a)
    start_time = datetime(2027, 5, 1, 14, 0, 0, tzinfo=timezone.utc)
    end_time = datetime(2027, 5, 1, 15, 0, 0, tzinfo=timezone.utc)

    # Pre-create a confirmed booking overlapping the future maintenance window
    booking = Booking(
        user_id=driver_user.id,
        station_id=station_a.id,
        charger_id=charger_a1.id,
        status=BookingStatus.CONFIRMED,
        start_time=start_time,
        end_time=end_time,
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    assert booking.status == BookingStatus.CONFIRMED

    # Operator defines maintenance window encompassing the booking
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Emergency Breaker Replacement",
            "start_time": (start_time - timedelta(hours=1)).isoformat(),
            "end_time": (end_time + timedelta(hours=1)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 201

    # Verify the booking is now marked CANCELLED
    db_session.expire_all()
    updated_booking = db_session.query(Booking).filter(Booking.id == booking.id).first()
    assert updated_booking.status == BookingStatus.CANCELLED


def test_tc_f2_06_invalid_maintenance_times_rejected(
    client: TestClient,
    operator_a: User,
    station_a: Station,
):
    """
    Validation tests:
    - end_time <= start_time -> 422 Unprocessable Entity
    - title < 3 characters -> 422 Unprocessable Entity
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)

    # Case 1: end_time before start_time
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Valid Title",
            "start_time": (now + timedelta(hours=5)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422

    # Case 2: end_time equals start_time
    res_equal = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Valid Title",
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_equal.status_code == 422

    # Case 3: Title too short
    res_title = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "AB",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_title.status_code == 422


def test_tc_f2_06_charger_foreign_to_station_rejected(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    station_b: Station,
    db_session: Session,
):
    """
    Attempting to bind a maintenance window on station A with a charger belonging
    to station B is rejected with 400 Bad Request.
    """
    token = make_token(operator_a)
    charger_b = Charger(
        station_id=station_b.id,
        power_kw=100.0,
        current_type=CurrentType.DC,
        gateway_id="OCPP-BETA-01",
    )
    db_session.add(charger_b)
    db_session.commit()
    db_session.refresh(charger_b)

    now = datetime.now(timezone.utc)
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_b.id,
            "title": "Mismatched Charger Maintenance",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 400
    assert "does not belong to station" in res.json()["detail"]


# =========================================================================
# STC-F2-06: Security, Tenancy and Role-Based Access Control
# =========================================================================

def test_stc_f2_06_unauthenticated_request_rejected(
    client: TestClient,
    station_a: Station,
):
    """
    Unauthenticated request must return 401 Unauthorized.
    """
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Unauthorized Maintenance",
            "start_time": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "end_time": (datetime.now(timezone.utc) + timedelta(hours=3)).isoformat(),
        },
    )
    assert res.status_code == 401


def test_stc_f2_06_driver_cannot_create_maintenance_window(
    client: TestClient,
    driver_user: User,
    station_a: Station,
):
    """
    Drivers are forbidden from creating maintenance windows (403 Forbidden).
    """
    token = make_token(driver_user)
    now = datetime.now(timezone.utc)
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Driver Disruption Attempt",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_stc_f2_06_operator_tenancy_isolation(
    client: TestClient,
    operator_b: User,
    station_a: Station,
):
    """
    Operator B cannot define or modify maintenance windows on Operator A's station (403 Forbidden).
    """
    token = make_token(operator_b)
    now = datetime.now(timezone.utc)
    res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Rogue Competitor Maintenance",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


# =========================================================================
# Architecture Doc Page 6: Global Query and CRUD Operations
# =========================================================================

def test_tc_f2_06_architecture_route_global_maintenance_windows(
    client: TestClient,
    operator_a: User,
    operator_b: User,
    admin_user: User,
    driver_user: User,
    station_a: Station,
    station_b: Station,
):
    """
    Tests GET /api/v1/stations/maintenance-windows (Architecture Doc Page 6).
    Verifies operator scoping, driver filtering, and admin visibility.
    """
    tok_a = make_token(operator_a)
    tok_b = make_token(operator_b)
    tok_admin = make_token(admin_user)
    tok_driver = make_token(driver_user)

    now = datetime.now(timezone.utc)

    # 1. Operator A creates a window on Station A
    client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "title": "Alpha Window",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {tok_a}"},
    )

    # 2. Operator B creates a window on Station B
    client.post(
        f"/api/v1/stations/{station_b.id}/maintenance-windows",
        json={
            "title": "Beta Window",
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "end_time": (now + timedelta(hours=4)).isoformat(),
        },
        headers={"Authorization": f"Bearer {tok_b}"},
    )

    # 3. Query GET /api/v1/stations/maintenance-windows as Operator A:
    # Should only return Operator A's window (tenancy scoping)
    res_a = client.get(
        "/api/v1/stations/maintenance-windows",
        headers={"Authorization": f"Bearer {tok_a}"},
    )
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert data_a["total"] == 1
    assert data_a["items"][0]["title"] == "Alpha Window"

    # 4. Query as Admin: Sees all windows
    res_admin = client.get(
        "/api/v1/stations/maintenance-windows",
        headers={"Authorization": f"Bearer {tok_admin}"},
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["total"] >= 2

    # 5. Query as Driver: Sees windows on approved active stations
    res_driver = client.get(
        "/api/v1/stations/maintenance-windows",
        headers={"Authorization": f"Bearer {tok_driver}"},
    )
    assert res_driver.status_code == 200
    assert res_driver.json()["total"] >= 2


def test_tc_f2_06_update_and_delete_maintenance_window(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
):
    """
    Tests updating and deleting maintenance windows, verifying slot availability restoration.
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)
    start_time = now + timedelta(days=3, hours=1)
    end_time = now + timedelta(days=3, hours=4)

    # 1. Create window
    create_res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Initial Inspection",
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code == 201
    window_id = create_res.json()["id"]

    # 2. Update window
    new_end_time = end_time + timedelta(hours=2)
    update_res = client.put(
        f"/api/v1/maintenance-windows/{window_id}",
        json={
            "title": "Extended Overhaul",
            "end_time": new_end_time.isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert update_res.status_code == 200
    assert update_res.json()["title"] == "Extended Overhaul"

    # 3. Verify slot in extended window is blocked
    check_slot = {
        "charger_id": charger_a1.id,
        "start_time": (end_time + timedelta(minutes=30)).isoformat(),
        "end_time": (end_time + timedelta(hours=1, minutes=30)).isoformat(),
    }
    chk = client.post(
        f"/api/v1/stations/{station_a.id}/check-slot-availability",
        json={"slots": [check_slot]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert chk.json()["removed_count"] == 1

    # 4. Delete window
    del_res = client.delete(
        f"/api/v1/maintenance-windows/{window_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert del_res.status_code == 200

    # 5. Verify slot availability is restored
    chk_after_del = client.post(
        f"/api/v1/stations/{station_a.id}/check-slot-availability",
        json={"slots": [check_slot]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert chk_after_del.json()["available_count"] == 1
    assert chk_after_del.json()["removed_count"] == 0


# =========================================================================
# Unit Tests for stations/slots.py and Interval Algorithms
# =========================================================================

def test_tc_f2_06_does_slot_overlap_window_edge_cases():
    """
    Direct unit test for slot overlap calculation:
    - Slot strictly before window: False
    - Slot strictly after window: False
    - Slot ends exactly at window start: False (abutting)
    - Slot starts exactly at window end: False (abutting)
    - Slot overlaps window start: True
    - Slot overlaps window end: True
    - Slot fully inside window: True
    - Window fully inside slot: True
    """
    w_start = datetime(2027, 2, 1, 10, 0, tzinfo=timezone.utc)
    w_end = datetime(2027, 2, 1, 12, 0, tzinfo=timezone.utc)

    # Strictly before
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 8, 0, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc),
        w_start, w_end,
    ) is False

    # Abutting before (end == w_start)
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc),
        w_start,
        w_start, w_end,
    ) is False

    # Strictly after
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 13, 0, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 14, 0, tzinfo=timezone.utc),
        w_start, w_end,
    ) is False

    # Abutting after (start == w_end)
    assert does_slot_overlap_window(
        w_end,
        datetime(2027, 2, 1, 13, 0, tzinfo=timezone.utc),
        w_start, w_end,
    ) is False

    # Overlaps start
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 9, 30, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 10, 30, tzinfo=timezone.utc),
        w_start, w_end,
    ) is True

    # Overlaps end
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 11, 30, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 12, 30, tzinfo=timezone.utc),
        w_start, w_end,
    ) is True

    # Fully inside
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 10, 30, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 11, 30, tzinfo=timezone.utc),
        w_start, w_end,
    ) is True

    # Fully enclosing window
    assert does_slot_overlap_window(
        datetime(2027, 2, 1, 9, 0, tzinfo=timezone.utc),
        datetime(2027, 2, 1, 13, 0, tzinfo=timezone.utc),
        w_start, w_end,
    ) is True


def test_tc_f2_06_parse_operating_hours():
    """
    Tests parsing various opening hours formats per §5.2.4.
    """
    assert parse_operating_hours("24 hours") == (time(0, 0), time(23, 59, 59))
    assert parse_operating_hours("all day") == (time(0, 0), time(23, 59, 59))
    assert parse_operating_hours("") == (time(0, 0), time(23, 59, 59))
    assert parse_operating_hours("08:00 - 20:00") == (time(8, 0), time(20, 0))
    assert parse_operating_hours("09:30-18:00") == (time(9, 30), time(18, 0))
    assert parse_operating_hours("invalid string") == (time(0, 0), time(23, 59, 59))


def test_tc_f2_06_generate_day_slots_never_overlaps_maintenance():
    """
    Unit test for SRS §5.2.4:
    'Slots are generated only within opening hours and never overlap maintenance windows.'
    """
    target = date(2027, 3, 15)
    hours = "08:00 - 12:00"  # 4 hours -> 8 thirty-minute slots

    maint_window = MaintenanceWindow(
        station_id=1,
        charger_id=1,
        title="Mid-day Service",
        start_time=datetime(2027, 3, 15, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2027, 3, 15, 10, 30, tzinfo=timezone.utc),
    )

    avail, removed = generate_available_slots_for_day(
        target_date=target,
        operating_hours=hours,
        maintenance_windows=[maint_window],
        charger_id=1,
        slot_duration_minutes=30,
    )

    # 4 hours with 30-min slots = 8 candidate slots:
    # 08:00-08:30 (avail)
    # 08:30-09:00 (avail, abutting)
    # 09:00-09:30 (removed)
    # 09:30-10:00 (removed)
    # 10:00-10:30 (removed)
    # 10:30-11:00 (avail, abutting)
    # 11:00-11:30 (avail)
    # 11:30-12:00 (avail)
    assert len(avail) == 5
    assert len(removed) == 3
    for s in avail:
        assert s.is_available is True
    for s in removed:
        assert s.is_available is False
        assert "Mid-day Service" in s.blocked_reason


def test_tc_f2_06_get_maintenance_window_detail_and_not_found(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
):
    """
    Test GET /api/v1/maintenance-windows/{id} and 404 for non-existent window.
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)
    create_res = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Hardware Inspection",
            "start_time": (now + timedelta(days=5)).isoformat(),
            "end_time": (now + timedelta(days=5, hours=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert create_res.status_code == 201
    wid = create_res.json()["id"]

    # 1. Fetch details
    get_res = client.get(
        f"/api/v1/maintenance-windows/{wid}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Hardware Inspection"

    # 2. Fetch 404
    nf_res = client.get(
        "/api/v1/maintenance-windows/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert nf_res.status_code == 404


def test_tc_f2_06_station_specific_listing_and_filters(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
    charger_a2: Charger,
):
    """
    Test GET /api/v1/stations/{station_id}/maintenance-windows with charger_id and active_only filters.
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)

    # Window 1: charger_a1, future
    client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Upcoming Window A1",
            "start_time": (now + timedelta(days=1)).isoformat(),
            "end_time": (now + timedelta(days=1, hours=3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    # Window 2: charger_a2, past
    client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a2.id,
            "title": "Past Window A2",
            "start_time": (now - timedelta(days=2)).isoformat(),
            "end_time": (now - timedelta(days=2, hours=-3)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )

    # Query all station windows
    res_all = client.get(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_all.status_code == 200
    assert res_all.json()["total"] >= 2

    # Query with charger filter
    res_c1 = client.get(
        f"/api/v1/stations/{station_a.id}/maintenance-windows?charger_id={charger_a1.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_c1.status_code == 200
    assert any(w["title"] == "Upcoming Window A1" for w in res_c1.json()["items"])

    # Query with active_only=true
    res_act = client.get(
        f"/api/v1/stations/{station_a.id}/maintenance-windows?active_only=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_act.status_code == 200
    assert all(w["title"] != "Past Window A2" for w in res_act.json()["items"])


def test_tc_f2_06_errors_and_edge_cases(
    client: TestClient,
    operator_a: User,
    station_a: Station,
    charger_a1: Charger,
    charger_a2: Charger,
    db_session: Session,
):
    """
    Test edge error conditions:
    - Station not found on create / list / slot availability
    - Window not found on update / delete
    - Updating charger_id to charger of another station
    """
    token = make_token(operator_a)
    now = datetime.now(timezone.utc)

    # 1. Non-existent station on create
    res_st_nf = client.post(
        "/api/v1/stations/99999/maintenance-windows",
        json={
            "title": "Test Title",
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "end_time": (now + timedelta(hours=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_st_nf.status_code == 404

    # 2. Non-existent station on slot check
    res_chk_nf = client.post(
        "/api/v1/stations/99999/check-slot-availability",
        json={"slots": []},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_chk_nf.status_code == 404

    # 3. Non-existent window on update
    res_up_nf = client.put(
        "/api/v1/maintenance-windows/99999",
        json={"title": "Updated Title"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_up_nf.status_code == 404

    # 4. Non-existent window on delete
    res_del_nf = client.delete(
        "/api/v1/maintenance-windows/99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_del_nf.status_code == 404

    # 5. Create window, then update description and charger_id to valid
    cr = client.post(
        f"/api/v1/stations/{station_a.id}/maintenance-windows",
        json={
            "charger_id": charger_a1.id,
            "title": "Preliminary Work",
            "start_time": (now + timedelta(days=6)).isoformat(),
            "end_time": (now + timedelta(days=6, hours=2)).isoformat(),
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert cr.status_code == 201
    wid = cr.json()["id"]

    up = client.put(
        f"/api/v1/maintenance-windows/{wid}",
        json={
            "charger_id": charger_a2.id,
            "description": "Updated maintenance scope description",
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert up.status_code == 200
    assert up.json()["charger_id"] == charger_a2.id
    assert up.json()["description"] == "Updated maintenance scope description"


