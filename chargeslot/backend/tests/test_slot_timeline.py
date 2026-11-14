"""
Test Suite for Slot Timeline View (REQ-F2-23 / TC-F2-23 / STC-F2-23 / CS19-049).

Requirements Under Test:
- REQ-F2-23: "The system shall display, for a selected station and date, a slot timeline
  per connector in which each slot is shown as Free, Booked, Blocked or Past."
- 15-minute interval slot breakdown across operating hours.
- State resolution precedence: Past > Blocked (OOS, Faulted, Maintenance) > Booked > Free.
- Target date boundary enforcement (up to 7 days ahead; >7 days rejected with 422).
- Status filtering by Free, Booked, Blocked, Past.
- Role-based scoping: Drivers view approved stations; Operators view own stations; Admins view all.
- SW Architecture endpoints: /api/v1/stations/slot-timeline and path aliases.
"""

from datetime import date, datetime, time, timedelta, timezone
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.dashboard.timeline import (
    get_station_slot_timeline,
    resolve_slot_timeline_state,
    validate_slot_timeline_params,
)
from app.models.booking import Booking, BookingStatus
from app.models.charger import (
    Charger,
    Connector,
    ConnectorStatus,
    ConnectorType,
    CurrentType,
)
from app.models.maintenance import MaintenanceWindow
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.schemas.dashboard import TimelineSlotState
from app.stations.slots import BOOKABLE_SLOT_INTERVAL_MINUTES, MAX_SLOT_DAYS_AHEAD
from app.utils.security import create_access_token, hash_password


def _make_user(
    db_session,
    *,
    name: str,
    email: str,
    phone: str,
    role: UserRole,
) -> User:
    user = User(
        name=name,
        email=email,
        phone=phone,
        hashed_password=hash_password("StrongPass!1"),
        role=role,
        is_active=True,
        is_verified=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def _auth_header(user: User) -> dict[str, str]:
    token = create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
    )
    return {"Authorization": f"Bearer {token}"}


def _seed_test_station(
    db_session,
    operator: User,
    *,
    name: str = "Central Fast Charging Hub",
    status: StationStatus = StationStatus.APPROVED,
    operating_hours: str = "08:00 - 20:00",
) -> tuple[Station, Charger, Connector, Connector]:
    station = Station(
        name=name,
        address="100 Innovation Way, Tech Park",
        latitude=12.9716,
        longitude=77.5946,
        contact_phone="9876543210",
        contact_email="hub@chargeslot.com",
        operating_hours=operating_hours,
        status=status,
        is_active=True,
        operator_id=operator.id,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    charger = Charger(
        name="Charger Alpha",
        station_id=station.id,
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id=f"gw-{station.id}",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.commit()
    db_session.refresh(charger)

    conn1 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    conn2 = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.TYPE_2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add_all([conn1, conn2])
    db_session.commit()
    db_session.refresh(conn1)
    db_session.refresh(conn2)

    return station, charger, conn1, conn2


# ---------------------------------------------------------------------------
# Unit Tests for Parameter Validation & State Resolution (TC-F2-23)
# ---------------------------------------------------------------------------


def test_validate_slot_timeline_params_valid():
    """Valid target_date within 7 days and valid status_filter pass validation."""
    today = datetime.now(timezone.utc).date()
    target = today + timedelta(days=3)

    eff_date, p_filter = validate_slot_timeline_params(
        station_id=1,
        connector_id=None,
        target_date=target,
        status_filter="Free",
    )
    assert eff_date == target
    assert p_filter == TimelineSlotState.FREE


def test_validate_slot_timeline_params_requires_id():
    """At least station_id or connector_id must be provided."""
    with pytest.raises(HTTPException) as exc_info:
        validate_slot_timeline_params(station_id=None, connector_id=None)
    assert exc_info.value.status_code == 422
    assert "Must provide station_id or connector_id" in exc_info.value.detail


def test_validate_slot_timeline_params_target_date_exceeds_horizon():
    """target_date cannot exceed 7 days ahead."""
    today = datetime.now(timezone.utc).date()
    future_8_days = today + timedelta(days=8)

    with pytest.raises(HTTPException) as exc_info:
        validate_slot_timeline_params(station_id=1, target_date=future_8_days)
    assert exc_info.value.status_code == 422
    assert "cannot be more than 7 days ahead" in exc_info.value.detail


def test_validate_slot_timeline_params_invalid_status_filter():
    """Invalid status_filter value is rejected with 422."""
    with pytest.raises(HTTPException) as exc_info:
        validate_slot_timeline_params(station_id=1, status_filter="UnknownStatus")
    assert exc_info.value.status_code == 422
    assert "Invalid status filter" in exc_info.value.detail


def test_resolve_slot_timeline_state_precedence():
    """
    Verify state resolution precedence:
    Past > Out of Service > Faulted > Maintenance > Booked > Free.
    """
    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    # 1. Past slot
    past_start = datetime(2026, 11, 14, 11, 0, tzinfo=timezone.utc)
    past_end = datetime(2026, 11, 14, 11, 15, tzinfo=timezone.utc)
    state, reason, _, _ = resolve_slot_timeline_state(
        slot_start=past_start,
        slot_end=past_end,
        ref_now=ref_now,
        is_charger_oos=False,
        oos_reason=None,
        is_charger_active=True,
        is_connector_faulted_or_offline=False,
        connector_status_str="Available",
        maintenance_windows=[],
        bookings=[],
        charger_id=1,
        connector_id=1,
        connector_type_str="CCS2",
    )
    assert state == TimelineSlotState.PAST
    assert reason == "Past slot"

    # 2. Future slot with OOS charger
    future_start = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
    future_end = datetime(2026, 11, 14, 14, 15, tzinfo=timezone.utc)
    state, reason, _, _ = resolve_slot_timeline_state(
        slot_start=future_start,
        slot_end=future_end,
        ref_now=ref_now,
        is_charger_oos=True,
        oos_reason="Transformer replacement",
        is_charger_active=True,
        is_connector_faulted_or_offline=False,
        connector_status_str="Available",
        maintenance_windows=[],
        bookings=[],
        charger_id=1,
        connector_id=1,
        connector_type_str="CCS2",
    )
    assert state == TimelineSlotState.BLOCKED
    assert "Out of service: Transformer replacement" in reason

    # 3. Future slot with Faulted connector
    state, reason, _, _ = resolve_slot_timeline_state(
        slot_start=future_start,
        slot_end=future_end,
        ref_now=ref_now,
        is_charger_oos=False,
        oos_reason=None,
        is_charger_active=True,
        is_connector_faulted_or_offline=True,
        connector_status_str="Faulted",
        maintenance_windows=[],
        bookings=[],
        charger_id=1,
        connector_id=1,
        connector_type_str="CCS2",
    )
    assert state == TimelineSlotState.BLOCKED
    assert "Connector Faulted" in reason

    # 4. Clean future slot -> Free
    state, reason, _, _ = resolve_slot_timeline_state(
        slot_start=future_start,
        slot_end=future_end,
        ref_now=ref_now,
        is_charger_oos=False,
        oos_reason=None,
        is_charger_active=True,
        is_connector_faulted_or_offline=False,
        connector_status_str="Available",
        maintenance_windows=[],
        bookings=[],
        charger_id=1,
        connector_id=1,
        connector_type_str="CCS2",
    )
    assert state == TimelineSlotState.FREE
    assert reason is None


# ---------------------------------------------------------------------------
# Integration Tests: Station Slot Timeline Generation (TC-F2-23)
# ---------------------------------------------------------------------------


def test_station_slot_timeline_15_min_intervals_and_operating_hours(db_session):
    """
    TC-F2-23: Verify that the timeline generates exact 15-minute slots
    strictly bounded within operating hours (08:00 - 20:00 = 48 slots per connector).
    """
    operator = _make_user(db_session, name="Op 1", email="op1@timeline.test", phone="9000000101", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 1", email="dr1@timeline.test", phone="9000000102", role=UserRole.DRIVER)

    station, charger, conn1, conn2 = _seed_test_station(
        db_session, operator, operating_hours="08:00 - 20:00"
    )

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    result = get_station_slot_timeline(
        db=db_session,
        user=driver,
        station_id=station.id,
        target_date=future_date,
    )

    assert result.station_id == station.id
    assert result.slot_interval_minutes == 15
    assert result.target_date == future_date.isoformat()
    assert result.total_connectors == 2

    # Each connector has 48 slots across 12 hours (08:00 to 20:00)
    for c in result.connectors:
        assert c.total_slots == 48
        assert c.free_slots == 48
        assert c.booked_slots == 0
        assert c.blocked_slots == 0
        assert c.past_slots == 0
        for slot in c.slots:
            assert slot.status == TimelineSlotState.FREE
            assert slot.is_available is True
            assert (slot.end_time - slot.start_time).total_seconds() / 60 == 15


def test_station_slot_timeline_four_states_coexistence(db_session):
    """
    REQ-F2-23: Verify that a connector's timeline can simultaneously contain
    Past, Blocked, Booked, and Free slots on the current day.
    """
    operator = _make_user(db_session, name="Op 2", email="op2@timeline.test", phone="9000000103", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 2", email="dr2@timeline.test", phone="9000000104", role=UserRole.DRIVER)

    station, charger, conn1, _ = _seed_test_station(
        db_session, operator, operating_hours="08:00 - 20:00"
    )

    today = date(2026, 11, 14)
    # Simulate current time at 12:00 UTC
    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    # 1. Maintenance window from 13:00 to 14:00 (overlaps four 15-min slots: 13:00, 13:15, 13:30, 13:45)
    mw_start = datetime(2026, 11, 14, 13, 0, tzinfo=timezone.utc)
    mw_end = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
    mw = MaintenanceWindow(
        station_id=station.id,
        charger_id=charger.id,
        title="Cable Safety Audit",
        start_time=mw_start,
        end_time=mw_end,
        created_by_user_id=operator.id,
    )
    db_session.add(mw)

    # 2. Confirmed booking from 15:00 to 16:00 (four 15-min slots: 15:00, 15:15, 15:30, 15:45)
    veh = Vehicle(
        user_id=driver.id,
        make="Hyundai",
        model="Kona",
        battery_kwh=39.2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=14.0,
        registration_no="DL01AA1111",
        connector_type=ConnectorType.CCS2,
        is_default=True,
    )
    db_session.add(veh)
    db_session.commit()

    b_start = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)
    b_end = datetime(2026, 11, 14, 16, 0, tzinfo=timezone.utc)
    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn1.id,
        vehicle_id=veh.id,
        start_time=b_start,
        end_time=b_end,
        status=BookingStatus.CONFIRMED,
    )
    db_session.add(booking)
    db_session.commit()

    result = get_station_slot_timeline(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        target_date=today,
        now_utc=ref_now,
    )

    summary = result.connectors[0]

    # Slots breakdown (08:00 - 20:00 = 48 slots total):
    # - Past slots (08:00 to 12:00 = 4 hours * 4 = 16 slots)
    # - Blocked slots (13:00 to 14:00 = 1 hour * 4 = 4 slots)
    # - Booked slots (15:00 to 16:00 = 1 hour * 4 = 4 slots)
    # - Free slots: 48 - 16 - 4 - 4 = 24 slots
    assert summary.total_slots == 48
    assert summary.past_slots == 16
    assert summary.blocked_slots == 4
    assert summary.booked_slots == 4
    assert summary.free_slots == 24

    # Verify each state is properly labeled
    past_items = [s for s in summary.slots if s.status == TimelineSlotState.PAST]
    blocked_items = [s for s in summary.slots if s.status == TimelineSlotState.BLOCKED]
    booked_items = [s for s in summary.slots if s.status == TimelineSlotState.BOOKED]
    free_items = [s for s in summary.slots if s.status == TimelineSlotState.FREE]

    assert len(past_items) == 16
    assert len(blocked_items) == 4
    assert len(booked_items) == 4
    assert len(free_items) == 24

    assert all(s.blocked_reason == "Past slot" for s in past_items)
    assert all("Maintenance: Cable Safety Audit" in s.blocked_reason for s in blocked_items)
    assert all(s.booking_id == booking.id for s in booked_items)
    assert all(s.is_available is True for s in free_items)


def test_station_slot_timeline_status_filtering(db_session):
    """Status filter parameter returns only slots matching that status."""
    operator = _make_user(db_session, name="Op 3", email="op3@timeline.test", phone="9000000105", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 3", email="dr3@timeline.test", phone="9000000106", role=UserRole.DRIVER)

    station, charger, conn1, _ = _seed_test_station(
        db_session, operator, operating_hours="08:00 - 20:00"
    )

    today = date(2026, 11, 14)
    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    # Filter for 'Past' only
    res_past = get_station_slot_timeline(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        target_date=today,
        status_filter="Past",
        now_utc=ref_now,
    )
    c_past = res_past.connectors[0]
    assert len(c_past.slots) == 16
    assert all(s.status == TimelineSlotState.PAST for s in c_past.slots)

    # Filter for 'Free' only
    res_free = get_station_slot_timeline(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        target_date=today,
        status_filter="Free",
        now_utc=ref_now,
    )
    c_free = res_free.connectors[0]
    assert len(c_free.slots) == 32
    assert all(s.status == TimelineSlotState.FREE for s in c_free.slots)


# ---------------------------------------------------------------------------
# RBAC & Scoping Tests
# ---------------------------------------------------------------------------


def test_driver_cannot_view_pending_station_timeline(db_session):
    """Drivers receive 404 when querying slot timeline for an unapproved station."""
    operator = _make_user(db_session, name="Op 4", email="op4@timeline.test", phone="9000000107", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 4", email="dr4@timeline.test", phone="9000000108", role=UserRole.DRIVER)

    station, _, conn1, _ = _seed_test_station(
        db_session, operator, status=StationStatus.PENDING
    )

    with pytest.raises(HTTPException) as exc_info:
        get_station_slot_timeline(
            db=db_session,
            user=driver,
            station_id=station.id,
        )
    assert exc_info.value.status_code == 404


def test_operator_foreign_station_timeline_forbidden(db_session):
    """Operators receive 403 when querying slot timeline for another operator's station."""
    op1 = _make_user(db_session, name="Op 5", email="op5@timeline.test", phone="9000000109", role=UserRole.OPERATOR)
    op2 = _make_user(db_session, name="Op 6", email="op6@timeline.test", phone="9000000110", role=UserRole.OPERATOR)

    station, _, conn1, _ = _seed_test_station(db_session, op1)

    with pytest.raises(HTTPException) as exc_info:
        get_station_slot_timeline(
            db=db_session,
            user=op2,
            station_id=station.id,
        )
    assert exc_info.value.status_code == 403


def test_admin_can_view_any_station_timeline(db_session):
    """Administrators can view slot timelines for any station, even pending."""
    op = _make_user(db_session, name="Op 7", email="op7@timeline.test", phone="9000000111", role=UserRole.OPERATOR)
    admin = _make_user(db_session, name="Admin", email="admin@timeline.test", phone="9000000112", role=UserRole.ADMIN)

    station, _, conn1, _ = _seed_test_station(
        db_session, op, status=StationStatus.PENDING
    )

    res = get_station_slot_timeline(
        db=db_session,
        user=admin,
        station_id=station.id,
    )
    assert res.station_id == station.id


# ---------------------------------------------------------------------------
# API Route Endpoint Tests
# ---------------------------------------------------------------------------


def test_api_slot_timeline_query_route(client: TestClient, db_session):
    """GET /api/v1/stations/slot-timeline (SW Architecture route)."""
    operator = _make_user(db_session, name="Op 8", email="op8@timeline.test", phone="9000000113", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 8", email="dr8@timeline.test", phone="9000000114", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/slot-timeline?station_id={station.id}&target_date={future_date.isoformat()}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_id"] == station.id
    assert data["target_date"] == future_date.isoformat()
    assert data["total_connectors"] == 2
    assert len(data["connectors"]) == 2


def test_api_slot_timeline_path_route(client: TestClient, db_session):
    """GET /api/v1/stations/{station_id}/slot-timeline and alias /timeline."""
    operator = _make_user(db_session, name="Op 9", email="op9@timeline.test", phone="9000000115", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 9", email="dr9@timeline.test", phone="9000000116", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/{station.id}/slot-timeline",
        headers=headers,
    )
    assert resp.status_code == 200

    resp_alias = client.get(
        f"/api/v1/stations/{station.id}/timeline",
        headers=headers,
    )
    assert resp_alias.status_code == 200


def test_api_slot_timeline_connector_path_route(client: TestClient, db_session):
    """GET /api/v1/stations/{station_id}/connectors/{connector_id}/timeline."""
    operator = _make_user(db_session, name="Op 10", email="op10@timeline.test", phone="9000000117", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 10", email="dr10@timeline.test", phone="9000000118", role=UserRole.DRIVER)
    station, _, conn1, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/{station.id}/connectors/{conn1.id}/timeline",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["connectors"]) == 1
    assert data["connectors"][0]["connector_id"] == conn1.id


def test_api_slot_timeline_dashboard_route(client: TestClient, db_session):
    """GET /api/v1/stations/slot-timeline via dashboard endpoints."""
    operator = _make_user(db_session, name="Op 11", email="op11@timeline.test", phone="9000000119", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 11", email="dr11@timeline.test", phone="9000000120", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/slot-timeline?station_id={station.id}",
        headers=headers,
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# System Test: STC-F2-23 (Full Timeline Lifecycle)
# ---------------------------------------------------------------------------


def test_stc_f2_23_full_timeline_lifecycle(client: TestClient, db_session):
    """
    STC-F2-23: End-to-end system test verifying slot timeline lifecycle:
    1. Seed multi-connector station with opening hours.
    2. Add scheduled maintenance on connector 1.
    3. Add active booking on connector 2.
    4. Simulate evaluation timestamp mid-day.
    5. Query timeline and verify each slot correctly presents Free, Booked, Blocked, or Past.
    6. Verify total metric consistency across connectors.
    """
    operator = _make_user(db_session, name="Op Lifecycle", email="oplc@timeline.test", phone="9000000121", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver Lifecycle", email="drlc@timeline.test", phone="9000000122", role=UserRole.DRIVER)

    station, charger, conn1, conn2 = _seed_test_station(
        db_session, operator, name="EcoHub Timeline Station", operating_hours="08:00 - 20:00"
    )

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    # 1. Maintenance on conn1 from 10:00 to 11:00 UTC (4 slots)
    mw_start = datetime.combine(future_date, time(10, 0), tzinfo=timezone.utc)
    mw_end = datetime.combine(future_date, time(11, 0), tzinfo=timezone.utc)
    mw = MaintenanceWindow(
        station_id=station.id,
        charger_id=charger.id,
        title="Inverter Servicing",
        start_time=mw_start,
        end_time=mw_end,
        created_by_user_id=operator.id,
    )
    db_session.add(mw)

    # 2. Booking on conn2 from 14:00 to 15:30 UTC (6 slots: 14:00, 14:15, 14:30, 14:45, 15:00, 15:15)
    veh = Vehicle(
        user_id=driver.id,
        make="MG",
        model="ZS EV",
        battery_kwh=50.3,
        max_ac_kw=7.4,
        max_dc_kw=50.0,
        consumption_kwh_100km=16.0,
        registration_no="KA05MG1234",
        connector_type=ConnectorType.TYPE_2,
        is_default=True,
    )
    db_session.add(veh)
    db_session.commit()

    b_start = datetime.combine(future_date, time(14, 0), tzinfo=timezone.utc)
    b_end = datetime.combine(future_date, time(15, 30), tzinfo=timezone.utc)
    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn2.id,
        vehicle_id=veh.id,
        start_time=b_start,
        end_time=b_end,
        status=BookingStatus.CONFIRMED,
    )
    db_session.add(booking)
    db_session.commit()

    headers = _auth_header(driver)

    # Query timeline for that date
    resp = client.get(
        f"/api/v1/stations/{station.id}/slot-timeline?target_date={future_date.isoformat()}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["station_id"] == station.id
    assert data["target_date"] == future_date.isoformat()
    assert data["total_connectors"] == 2
    assert data["total_slots"] == 96  # 48 * 2

    c1 = next(c for c in data["connectors"] if c["connector_id"] == conn1.id)
    c2 = next(c for c in data["connectors"] if c["connector_id"] == conn2.id)

    # Maintenance affects charger, so both connectors are blocked during 10:00-11:00 (4 slots)
    assert c1["blocked_slots"] == 4
    assert c1["booked_slots"] == 0
    assert c1["free_slots"] == 44

    # c2 has 4 blocked slots + 6 booked slots = 10 unavailable -> 38 free slots
    assert c2["blocked_slots"] == 4
    assert c2["booked_slots"] == 6
    assert c2["free_slots"] == 38

    # Query with status=Booked filter
    resp_booked = client.get(
        f"/api/v1/stations/{station.id}/slot-timeline?target_date={future_date.isoformat()}&status=Booked",
        headers=headers,
    )
    assert resp_booked.status_code == 200
    b_data = resp_booked.json()
    assert b_data["total_slots"] == 6
    assert all(s["status"] == "Booked" for c in b_data["connectors"] for s in c["slots"])
