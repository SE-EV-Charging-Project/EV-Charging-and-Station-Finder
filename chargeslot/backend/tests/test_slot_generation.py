"""
Test Suite for Bookable Slot Generation (REQ-F2-22 / TC-F2-22 / STC-F2-22 / CS19-048).

Requirements Under Test:
- REQ-F2-22: "The system shall generate bookable slots of 15 minutes for every connector for up to 7 days ahead."
- Operating hours boundary enforcement.
- Out-of-service, inactive, faulted, maintenance, and booked slot collision handling.
- Up to 7 days ahead horizon validation (1..7 days allowed; >7 or past dates rejected with 422).
- RBAC scoping: Drivers see approved stations, Operators see own stations, Admins see all.
"""

from datetime import date, datetime, time, timedelta, timezone
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
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
from app.stations.slots import (
    BOOKABLE_SLOT_INTERVAL_MINUTES,
    MAX_SLOT_DAYS_AHEAD,
    MIN_SLOT_DAYS_AHEAD,
    generate_station_bookable_slots,
    validate_slot_generation_params,
)
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
# Unit Tests for Parameter Validation
# ---------------------------------------------------------------------------


def test_validate_slot_generation_params_valid():
    """Valid parameters within 1..7 days pass validation."""
    s_date, e_date, days = validate_slot_generation_params(
        station_id=1,
        connector_id=None,
        days_ahead=7,
        target_date=None,
    )
    assert days == 7
    assert (e_date - s_date).days == 6  # 7 days inclusive: today + 6 days


def test_validate_slot_generation_params_requires_id():
    """At least station_id or connector_id must be provided."""
    with pytest.raises(HTTPException) as exc_info:
        validate_slot_generation_params(
            station_id=None,
            connector_id=None,
            days_ahead=3,
        )
    assert exc_info.value.status_code == 422
    assert "Must provide station_id or connector_id" in exc_info.value.detail


def test_validate_slot_generation_params_days_ahead_bounds():
    """days_ahead must be between 1 and 7."""
    with pytest.raises(HTTPException) as exc_low:
        validate_slot_generation_params(station_id=1, connector_id=None, days_ahead=0)
    assert exc_low.value.status_code == 422

    with pytest.raises(HTTPException) as exc_high:
        validate_slot_generation_params(station_id=1, connector_id=None, days_ahead=8)
    assert exc_high.value.status_code == 422
    assert "between 1 and 7" in exc_high.value.detail


def test_validate_slot_generation_params_target_date_bounds():
    """target_date cannot be in the past or beyond 7 days ahead."""
    today = datetime.now(timezone.utc).date()
    yesterday = today - timedelta(days=1)
    far_future = today + timedelta(days=8)

    with pytest.raises(HTTPException) as exc_past:
        validate_slot_generation_params(station_id=1, connector_id=None, target_date=yesterday)
    assert exc_past.value.status_code == 422
    assert "cannot be in the past" in exc_past.value.detail

    with pytest.raises(HTTPException) as exc_future:
        validate_slot_generation_params(station_id=1, connector_id=None, target_date=far_future)
    assert exc_future.value.status_code == 422
    assert "cannot be more than 7 days ahead" in exc_future.value.detail


# ---------------------------------------------------------------------------
# Core Slot Generation & Interval Verification (TC-F2-22)
# ---------------------------------------------------------------------------


def test_slot_interval_exact_15_minutes_and_operating_hours(db_session):
    """
    TC-F2-22: Verify generated slots are exactly 15 minutes each,
    strictly bounded within station operating hours (08:00 - 20:00 = 12h = 48 slots/day per connector).
    """
    operator = _make_user(db_session, name="Op 1", email="op1@test.com", phone="9000000001", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 1", email="dr1@test.com", phone="9000000002", role=UserRole.DRIVER)

    station, charger, conn1, conn2 = _seed_test_station(
        db_session, operator, operating_hours="08:00 - 20:00"
    )

    # Use a future target date so no slots are marked past
    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    result = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        days_ahead=1,
        target_date=future_date,
    )

    assert result.station_id == station.id
    assert result.slot_interval_minutes == 15
    assert len(result.connectors) == 2

    # Operating hours: 08:00 to 20:00 -> 12 hours -> 12 * 4 = 48 slots per connector
    for conn_summary in result.connectors:
        assert conn_summary.total_slots == 48
        for slot in conn_summary.slots:
            assert slot.duration_minutes == 15
            duration = (slot.end_time - slot.start_time).total_seconds() / 60
            assert duration == 15
            assert slot.start_time.time() >= time(8, 0)
            assert slot.end_time.time() <= time(20, 0)
            assert slot.is_available is True
            assert slot.is_bookable is True


def test_24_hour_station_generates_96_slots_per_day(db_session):
    """A 24-hour station generates 96 slots of 15 minutes per day per connector."""
    operator = _make_user(db_session, name="Op 2", email="op2@test.com", phone="9000000003", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 2", email="dr2@test.com", phone="9000000004", role=UserRole.DRIVER)

    station, charger, conn1, _ = _seed_test_station(
        db_session, operator, operating_hours="24 hours"
    )

    future_date = datetime.now(timezone.utc).date() + timedelta(days=3)

    result = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=1,
        target_date=future_date,
    )

    assert len(result.connectors) == 1
    summary = result.connectors[0]
    # 24 hours * 4 slots/hour = 96 slots
    assert summary.total_slots == 96
    assert summary.available_slots == 96


def test_up_to_7_days_generation(db_session):
    """
    REQ-F2-22: Verify generation for up to 7 days ahead.
    7 days * 48 slots = 336 slots per connector.
    """
    operator = _make_user(db_session, name="Op 3", email="op3@test.com", phone="9000000005", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 3", email="dr3@test.com", phone="9000000006", role=UserRole.DRIVER)

    station, charger, conn1, _ = _seed_test_station(
        db_session, operator, operating_hours="08:00 - 20:00"
    )

    result = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=7,
    )

    assert result.days_ahead == 7
    summary = result.connectors[0]
    # 7 days * 48 slots = 336 total slots
    assert summary.total_slots == 336


# ---------------------------------------------------------------------------
# Collision & Blocking Tests
# ---------------------------------------------------------------------------


def test_charger_out_of_service_blocks_slots(db_session):
    """When a charger is marked out-of-service, all its slots become unavailable."""
    operator = _make_user(db_session, name="Op 4", email="op4@test.com", phone="9000000007", role=UserRole.OPERATOR)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)

    charger.is_out_of_service = True
    charger.out_of_service_reason = "Grid line maintenance"
    db_session.commit()

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    result = generate_station_bookable_slots(
        db=db_session,
        user=operator,
        station_id=station.id,
        days_ahead=1,
        target_date=future_date,
    )

    for conn in result.connectors:
        assert conn.is_operational is False
        assert conn.available_slots == 0
        assert conn.blocked_slots == conn.total_slots
        for slot in conn.slots:
            assert slot.is_available is False
            assert "Out of service: Grid line maintenance" in slot.blocked_reason


def test_connector_faulted_blocks_slots(db_session):
    """When one connector is Faulted, its slots are blocked while the other remains available."""
    operator = _make_user(db_session, name="Op 5", email="op5@test.com", phone="9000000008", role=UserRole.OPERATOR)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)

    conn1.status = ConnectorStatus.FAULTED
    db_session.commit()

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    result = generate_station_bookable_slots(
        db=db_session,
        user=operator,
        station_id=station.id,
        days_ahead=1,
        target_date=future_date,
    )

    c1_summary = next(c for c in result.connectors if c.connector_id == conn1.id)
    c2_summary = next(c for c in result.connectors if c.connector_id == conn2.id)

    assert c1_summary.is_operational is False
    assert c1_summary.available_slots == 0
    assert c1_summary.slots[0].blocked_reason == "Connector Faulted"

    assert c2_summary.is_operational is True
    assert c2_summary.available_slots == c2_summary.total_slots


def test_maintenance_window_overlap_blocks_slot(db_session):
    """A maintenance window marks overlapping 15-min slots as is_maintenance=True and unavailable."""
    operator = _make_user(db_session, name="Op 6", email="op6@test.com", phone="9000000009", role=UserRole.OPERATOR)
    station, charger, conn1, _ = _seed_test_station(db_session, operator, operating_hours="08:00 - 20:00")

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)
    # Maintenance window from 10:00 to 11:00 UTC (overlaps four 15-min slots: 10:00, 10:15, 10:30, 10:45)
    mw_start = datetime.combine(future_date, time(10, 0), tzinfo=timezone.utc)
    mw_end = datetime.combine(future_date, time(11, 0), tzinfo=timezone.utc)

    mw = MaintenanceWindow(
        station_id=station.id,
        charger_id=charger.id,
        title="Routine Inverter Inspection",
        description="Quarterly checkup",
        start_time=mw_start,
        end_time=mw_end,
        created_by_user_id=operator.id,
    )
    db_session.add(mw)
    db_session.commit()

    result = generate_station_bookable_slots(
        db=db_session,
        user=operator,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=1,
        target_date=future_date,
    )

    conn_summary = result.connectors[0]
    maintenance_slots = [s for s in conn_summary.slots if s.is_maintenance]
    assert len(maintenance_slots) == 4  # 4 slots in 1 hour

    for slot in maintenance_slots:
        assert slot.is_available is False
        assert "Maintenance: Routine Inverter Inspection" in slot.blocked_reason


def test_booking_overlap_blocks_slot(db_session):
    """An active booking on a connector blocks overlapping slots with is_booked=True."""
    operator = _make_user(db_session, name="Op 7", email="op7@test.com", phone="9000000010", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 7", email="dr7@test.com", phone="9000000011", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator, operating_hours="08:00 - 20:00")

    vehicle = Vehicle(
        user_id=driver.id,
        make="Hyundai",
        model="Ioniq 5",
        battery_kwh=72.6,
        max_ac_kw=11.0,
        max_dc_kw=220.0,
        consumption_kwh_100km=18.0,
        registration_no="KA01EF1234",
        connector_type=ConnectorType.CCS2,
        is_default=True,
    )
    db_session.add(vehicle)
    db_session.commit()

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)
    # Booking from 14:00 to 14:30 (2 slots: 14:00 and 14:15)
    b_start = datetime.combine(future_date, time(14, 0), tzinfo=timezone.utc)
    b_end = datetime.combine(future_date, time(14, 30), tzinfo=timezone.utc)

    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn1.id,
        vehicle_id=vehicle.id,
        start_time=b_start,
        end_time=b_end,
        status=BookingStatus.CONFIRMED,
    )
    db_session.add(booking)
    db_session.commit()

    result = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        days_ahead=1,
        target_date=future_date,
    )

    c1 = next(c for c in result.connectors if c.connector_id == conn1.id)
    c2 = next(c for c in result.connectors if c.connector_id == conn2.id)

    booked_slots = [s for s in c1.slots if s.is_booked]
    assert len(booked_slots) == 2
    for s in booked_slots:
        assert s.is_available is False
        assert s.booking_id == booking.id
        assert s.booking_status in ("Confirmed", "confirmed")

    # conn2 was not booked, so all its slots should be free
    assert c2.booked_slots == 0


def test_available_only_filter(db_session):
    """available_only=True filters out blocked, booked, and past slots."""
    operator = _make_user(db_session, name="Op 8", email="op8@test.com", phone="9000000012", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 8", email="dr8@test.com", phone="9000000013", role=UserRole.DRIVER)
    station, charger, conn1, _ = _seed_test_station(db_session, operator, operating_hours="08:00 - 20:00")

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)
    # Add a maintenance window blocking 4 slots
    mw_start = datetime.combine(future_date, time(10, 0), tzinfo=timezone.utc)
    mw_end = datetime.combine(future_date, time(11, 0), tzinfo=timezone.utc)

    mw = MaintenanceWindow(
        station_id=station.id,
        charger_id=charger.id,
        title="Checkup",
        start_time=mw_start,
        end_time=mw_end,
        created_by_user_id=operator.id,
    )
    db_session.add(mw)
    db_session.commit()

    result_all = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=1,
        target_date=future_date,
        available_only=False,
    )
    assert result_all.connectors[0].total_slots == 48

    result_avail = generate_station_bookable_slots(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=1,
        target_date=future_date,
        available_only=True,
    )
    # 48 - 4 blocked = 44 available slots returned
    assert result_avail.connectors[0].total_slots == 44
    assert all(s.is_available for s in result_avail.connectors[0].slots)


# ---------------------------------------------------------------------------
# RBAC & Scoping Tests
# ---------------------------------------------------------------------------


def test_driver_cannot_view_pending_station_slots(db_session):
    """A driver receives 404 when requesting slots for a pending/unapproved station."""
    operator = _make_user(db_session, name="Op 9", email="op9@test.com", phone="9000000014", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 9", email="dr9@test.com", phone="9000000015", role=UserRole.DRIVER)
    station, _, conn1, _ = _seed_test_station(
        db_session, operator, status=StationStatus.PENDING
    )

    with pytest.raises(HTTPException) as exc_info:
        generate_station_bookable_slots(
            db=db_session,
            user=driver,
            station_id=station.id,
            connector_id=conn1.id,
        )
    assert exc_info.value.status_code == 404


def test_operator_foreign_station_forbidden(db_session):
    """An operator receives 403 when requesting slots for a station owned by another operator."""
    op1 = _make_user(db_session, name="Op 10", email="op10@test.com", phone="9000000016", role=UserRole.OPERATOR)
    op2 = _make_user(db_session, name="Op 11", email="op11@test.com", phone="9000000017", role=UserRole.OPERATOR)
    station, _, conn1, _ = _seed_test_station(db_session, op1)

    with pytest.raises(HTTPException) as exc_info:
        generate_station_bookable_slots(
            db=db_session,
            user=op2,
            station_id=station.id,
            connector_id=conn1.id,
        )
    assert exc_info.value.status_code == 403


def test_admin_can_view_any_station(db_session):
    """An administrator can view slots for any station, even pending."""
    op = _make_user(db_session, name="Op 12", email="op12@test.com", phone="9000000018", role=UserRole.OPERATOR)
    admin = _make_user(db_session, name="Admin 1", email="admin1@test.com", phone="9000000019", role=UserRole.ADMIN)
    station, _, conn1, _ = _seed_test_station(
        db_session, op, status=StationStatus.PENDING
    )

    result = generate_station_bookable_slots(
        db=db_session,
        user=admin,
        station_id=station.id,
        connector_id=conn1.id,
        days_ahead=1,
    )
    assert result.station_id == station.id
    assert len(result.connectors) == 1


# ---------------------------------------------------------------------------
# API Endpoint Integration Tests
# ---------------------------------------------------------------------------


def test_api_endpoint_query_route(client: TestClient, db_session):
    """Test GET /api/v1/stations/slot-generation with query parameters."""
    operator = _make_user(db_session, name="Op 13", email="op13@test.com", phone="9000000020", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 13", email="dr13@test.com", phone="9000000021", role=UserRole.DRIVER)
    station, _, conn1, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/slot-generation?station_id={station.id}&days_ahead=3",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_id"] == station.id
    assert data["slot_interval_minutes"] == 15
    assert data["days_ahead"] == 3
    assert len(data["connectors"]) == 2


def test_api_endpoint_path_route(client: TestClient, db_session):
    """Test GET /api/v1/stations/{station_id}/slots."""
    operator = _make_user(db_session, name="Op 14", email="op14@test.com", phone="9000000022", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 14", email="dr14@test.com", phone="9000000023", role=UserRole.DRIVER)
    station, _, conn1, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/{station.id}/slots?days_ahead=2",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_id"] == station.id
    assert data["days_ahead"] == 2


def test_api_endpoint_connector_path_route(client: TestClient, db_session):
    """Test GET /api/v1/stations/{station_id}/connectors/{connector_id}/slots."""
    operator = _make_user(db_session, name="Op 15", email="op15@test.com", phone="9000000024", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 15", email="dr15@test.com", phone="9000000025", role=UserRole.DRIVER)
    station, _, conn1, conn2 = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/{station.id}/connectors/{conn1.id}/slots?days_ahead=1",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["connectors"]) == 1
    assert data["connectors"][0]["connector_id"] == conn1.id


def test_api_endpoint_days_ahead_validation(client: TestClient, db_session):
    """API endpoint rejects days_ahead > 7 with 422."""
    operator = _make_user(db_session, name="Op 16", email="op16@test.com", phone="9000000026", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 16", email="dr16@test.com", phone="9000000027", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/slot-generation?station_id={station.id}&days_ahead=8",
        headers=headers,
    )
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# System Test: STC-F2-22 (Full Lifecycle)
# ---------------------------------------------------------------------------


def test_stc_f2_22_full_lifecycle(client: TestClient, db_session):
    """
    STC-F2-22: System test covering complete slot generation lifecycle:
    1. Station with 2 connectors and 08:00 - 20:00 operating hours.
    2. Add maintenance window on connector 1.
    3. Add active booking on connector 2.
    4. Verify both collision sources reflect accurately across the 7-day schedule.
    5. Query with available_only=true and verify only bookable slots are returned.
    """
    operator = _make_user(db_session, name="Op System", email="opsys@test.com", phone="9000000028", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver System", email="drsys@test.com", phone="9000000029", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(
        db_session, operator, name="Metro Supercharge", operating_hours="08:00 - 20:00"
    )

    future_date = datetime.now(timezone.utc).date() + timedelta(days=2)

    # 1. Maintenance on charger from 09:00 to 10:00
    mw_start = datetime.combine(future_date, time(9, 0), tzinfo=timezone.utc)
    mw_end = datetime.combine(future_date, time(10, 0), tzinfo=timezone.utc)
    mw = MaintenanceWindow(
        station_id=station.id,
        charger_id=charger.id,
        title="Scheduled Maintenance",
        start_time=mw_start,
        end_time=mw_end,
        created_by_user_id=operator.id,
    )
    db_session.add(mw)

    # 2. Booking on conn2 from 15:00 to 16:00
    veh = Vehicle(
        user_id=driver.id,
        make="Tata",
        model="Nexon EV",
        battery_kwh=40.5,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        registration_no="MH12AB9999",
        connector_type=ConnectorType.TYPE_2,
        is_default=True,
    )
    db_session.add(veh)
    db_session.commit()

    b_start = datetime.combine(future_date, time(15, 0), tzinfo=timezone.utc)
    b_end = datetime.combine(future_date, time(16, 0), tzinfo=timezone.utc)
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

    # Query full schedule for that target date
    resp = client.get(
        f"/api/v1/stations/{station.id}/slots?target_date={future_date.isoformat()}",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()

    assert data["station_id"] == station.id
    assert data["total_connectors"] == 2
    # Each connector has 48 slots (12 hours * 4) -> 96 total
    assert data["total_slots"] == 96

    c1_data = next(c for c in data["connectors"] if c["connector_id"] == conn1.id)
    c2_data = next(c for c in data["connectors"] if c["connector_id"] == conn2.id)

    # In c1: 4 maintenance slots, 0 booked slots
    assert c1_data["blocked_slots"] == 4
    assert c1_data["booked_slots"] == 0
    assert c1_data["available_slots"] == 44

    # In c2: 4 maintenance slots (since MW affects whole charger), 4 booked slots
    assert c2_data["booked_slots"] == 4
    assert c2_data["blocked_slots"] == 4
    assert c2_data["available_slots"] == 40

    # Query with available_only=true
    resp_avail = client.get(
        f"/api/v1/stations/{station.id}/slots?target_date={future_date.isoformat()}&available_only=true",
        headers=headers,
    )
    assert resp_avail.status_code == 200
    avail_data = resp_avail.json()
    assert avail_data["total_slots"] == (44 + 40)
    for c in avail_data["connectors"]:
        assert all(s["is_available"] for s in c["slots"])
