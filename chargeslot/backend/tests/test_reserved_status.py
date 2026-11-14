"""
Test Suite for Connector Reserved Status Display (REQ-F2-21 / TC-F2-21 / STC-F2-21 / CS19-047).
Verifies that connectors display Reserved status when an active confirmed booking starts within 15 minutes.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.dashboard.state import (
    DEFAULT_RESERVATION_WINDOW_MINUTES,
    find_confirmed_booking_for_connector,
    get_reserved_status_display,
    resolve_connector_reserved_status,
    validate_reserved_status_params,
)
from app.dashboard.views import get_live_connector_status_display
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
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


def _seed_reservation_test_station(
    db_session,
    operator: User,
    *,
    name: str = "Reservation Test Hub",
    status_val: StationStatus = StationStatus.APPROVED,
) -> tuple[Station, Charger, list[Connector]]:
    station = Station(
        operator_id=operator.id,
        name=name,
        address="100 Tech Park, Whitefield, Bengaluru",
        latitude=12.9840,
        longitude=77.7490,
        amenities=["WiFi", "Cafe"],
        operating_hours="24x7",
        contact_phone="+919876543210",
        contact_email="reservations@chargeslot.example",
        price_per_kwh=15.0,
        status=status_val,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="Fast Unit 1",
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id="GW-RES-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    c1 = Connector(
        charger_id=charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime.now(timezone.utc),
    )
    c2 = Connector(
        charger_id=charger.id,
        connector_type="CHAdeMO",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime.now(timezone.utc),
    )
    db_session.add_all([c1, c2])
    db_session.commit()
    db_session.refresh(station)
    db_session.refresh(charger)
    db_session.refresh(c1)
    db_session.refresh(c2)
    return station, charger, [c1, c2]


def test_tc_f2_21_exact_15_minute_boundary(db_session):
    """
    REQ-F2-21: Confirmed booking starting within 15 minutes displays Reserved.
    Boundary tests: 10m (in), exactly 15m (in), 16m (out), and ongoing.
    """
    operator = _make_user(
        db_session,
        name="Op Boundary",
        email="op_boundary@example.com",
        phone="+919999900001",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Boundary",
        email="drv_boundary@example.com",
        phone="+919999900002",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    conn = conns[0]
    now = datetime.now(timezone.utc)

    # 1. 16 minutes in future -> NOT reserved
    b_16m = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn.id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=16),
        end_time=now + timedelta(minutes=76),
    )
    db_session.add(b_16m)
    db_session.commit()

    is_res, b, diff = find_confirmed_booking_for_connector(
        db_session, conn, charger, now_utc=now, window_minutes=15
    )
    assert not is_res
    assert b is None

    # 2. Exactly 15 minutes in future -> RESERVED
    b_16m.start_time = now + timedelta(minutes=15)
    db_session.commit()

    is_res, b, diff = find_confirmed_booking_for_connector(
        db_session, conn, charger, now_utc=now, window_minutes=15
    )
    assert is_res
    assert b.id == b_16m.id
    assert diff == pytest.approx(15.0, abs=0.2)

    # 3. 10 minutes in future -> RESERVED
    b_16m.start_time = now + timedelta(minutes=10)
    db_session.commit()

    is_res, b, diff = find_confirmed_booking_for_connector(
        db_session, conn, charger, now_utc=now, window_minutes=15
    )
    assert is_res
    assert diff == pytest.approx(10.0, abs=0.2)

    # 4. Currently ongoing slot -> RESERVED
    b_16m.start_time = now - timedelta(minutes=5)
    b_16m.end_time = now + timedelta(minutes=55)
    db_session.commit()

    is_res, b, diff = find_confirmed_booking_for_connector(
        db_session, conn, charger, now_utc=now, window_minutes=15
    )
    assert is_res
    assert diff == 0.0


def test_tc_f2_21_booking_status_filtering(db_session):
    """
    REQ-F2-21: Only CONFIRMED bookings trigger Reserved status.
    HELD, CANCELLED, COMPLETED, NO_SHOW, EXPIRED do NOT trigger Reserved.
    """
    operator = _make_user(
        db_session,
        name="Op Status",
        email="op_status@example.com",
        phone="+919999900003",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Status",
        email="drv_status@example.com",
        phone="+919999900004",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    conn = conns[0]
    now = datetime.now(timezone.utc)

    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn.id,
        status=BookingStatus.HELD,
        start_time=now + timedelta(minutes=5),
        end_time=now + timedelta(minutes=65),
    )
    db_session.add(booking)
    db_session.commit()

    # HELD does not reserve connector
    is_res, _, _ = find_confirmed_booking_for_connector(db_session, conn, charger, now_utc=now)
    assert not is_res

    # Test all non-confirmed statuses
    for non_confirmed in [
        BookingStatus.CANCELLED,
        BookingStatus.COMPLETED,
        BookingStatus.NO_SHOW,
        BookingStatus.EXPIRED,
    ]:
        booking.status = non_confirmed
        db_session.commit()
        is_res, _, _ = find_confirmed_booking_for_connector(db_session, conn, charger, now_utc=now)
        assert not is_res, f"Expected {non_confirmed} not to trigger Reserved"

    # CONFIRMED triggers Reserved
    booking.status = BookingStatus.CONFIRMED
    db_session.commit()
    is_res, b, _ = find_confirmed_booking_for_connector(db_session, conn, charger, now_utc=now)
    assert is_res
    assert b.id == booking.id


def test_tc_f2_21_direct_and_vehicle_matching(db_session):
    """
    REQ-F2-21: Supports both explicit connector_id and charger_id + vehicle connector_type matching.
    """
    operator = _make_user(
        db_session,
        name="Op Matching",
        email="op_match@example.com",
        phone="+919999900005",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Matching",
        email="drv_match@example.com",
        phone="+919999900006",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    c_ccs2 = conns[0]  # CCS2
    c_chademo = conns[1]  # CHAdeMO

    vehicle = Vehicle(
        user_id=driver.id,
        make="Hyundai",
        model="Kona Electric",
        battery_kwh=64.0,
        max_ac_kw=11.0,
        max_dc_kw=100.0,
        consumption_kwh_100km=15.0,
        connector_type="CCS2",
        is_default=True,
    )
    db_session.add(vehicle)
    db_session.commit()

    now = datetime.now(timezone.utc)

    # Booking on charger without connector_id, but linked to CCS2 vehicle
    b_charger = Booking(
        user_id=driver.id,
        vehicle_id=vehicle.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=None,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=8),
        end_time=now + timedelta(minutes=68),
    )
    db_session.add(b_charger)
    db_session.commit()

    # CCS2 connector should be RESERVED
    is_res_ccs, _, _ = find_confirmed_booking_for_connector(
        db_session, c_ccs2, charger, now_utc=now
    )
    assert is_res_ccs

    # CHAdeMO connector should NOT be reserved
    is_res_cha, _, _ = find_confirmed_booking_for_connector(
        db_session, c_chademo, charger, now_utc=now
    )
    assert not is_res_cha


def test_tc_f2_21_hardware_overrides(db_session):
    """
    REQ-F2-21: Out of service and hardware faults/offline take precedence.
    """
    operator = _make_user(
        db_session,
        name="Op Override",
        email="op_over@example.com",
        phone="+919999900007",
        role=UserRole.OPERATOR,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    conn = conns[0]

    # Normal available + reserved -> Reserved
    st = resolve_connector_reserved_status(conn, charger, is_reserved=True)
    assert st == ConnectorStatus.RESERVED.value

    # Charger Out of service -> Offline
    charger.is_out_of_service = True
    st_oos = resolve_connector_reserved_status(conn, charger, is_reserved=True)
    assert st_oos == ConnectorStatus.OFFLINE.value

    # Reset charger OOS
    charger.is_out_of_service = False

    # Connector Faulted -> Faulted
    conn.status = ConnectorStatus.FAULTED
    st_fault = resolve_connector_reserved_status(conn, charger, is_reserved=True)
    assert st_fault == ConnectorStatus.FAULTED.value

    # Connector Offline -> Offline
    conn.status = ConnectorStatus.OFFLINE
    st_off = resolve_connector_reserved_status(conn, charger, is_reserved=True)
    assert st_off == ConnectorStatus.OFFLINE.value


def test_tc_f2_21_api_reserved_status_endpoint(client, db_session):
    """
    REQ-F2-21: GET /api/v1/stations/reserved-status (SW Architecture Route).
    """
    operator = _make_user(
        db_session,
        name="Op API",
        email="op_api@example.com",
        phone="+919999900008",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv API",
        email="drv_api@example.com",
        phone="+919999900009",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    now = datetime.now(timezone.utc)

    # Add confirmed booking on connector 0 starting in 5m
    b = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conns[0].id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=5),
        end_time=now + timedelta(minutes=65),
    )
    db_session.add(b)
    db_session.commit()

    # Query endpoint
    res = client.get(
        f"/api/v1/stations/reserved-status?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["station_id"] == station.id
    assert data["total_connectors"] == 2
    assert data["reserved_connectors"] == 1
    assert data["available_connectors"] == 1

    conn_items = {item["connector_id"]: item for item in data["connectors"]}
    assert conn_items[conns[0].id]["is_reserved"] is True
    assert conn_items[conns[0].id]["status"] == "Reserved"
    assert conn_items[conns[0].id]["booking_id"] == b.id
    assert conn_items[conns[1].id]["is_reserved"] is False
    assert conn_items[conns[1].id]["status"] == "Available"

    # Query with reserved_only=true
    res_filtered = client.get(
        f"/api/v1/stations/reserved-status?station_id={station.id}&reserved_only=true",
        headers=_auth_header(driver),
    )
    assert res_filtered.status_code == 200
    filtered_data = res_filtered.json()
    assert len(filtered_data["connectors"]) == 1
    assert filtered_data["connectors"][0]["connector_id"] == conns[0].id


def test_tc_f2_21_path_aliases(client, db_session):
    """
    REQ-F2-21: Test path routes for station and connector reserved status.
    """
    operator = _make_user(
        db_session,
        name="Op Path",
        email="op_path@example.com",
        phone="+919999900010",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Path",
        email="drv_path@example.com",
        phone="+919999900011",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    now = datetime.now(timezone.utc)

    b = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conns[0].id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=12),
        end_time=now + timedelta(minutes=72),
    )
    db_session.add(b)
    db_session.commit()

    # 1. /stations/{station_id}/reserved-status
    r1 = client.get(
        f"/api/v1/stations/{station.id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert r1.status_code == 200
    assert r1.json()["reserved_connectors"] == 1

    # 2. /connectors/{connector_id}/reserved-status
    r2 = client.get(
        f"/api/v1/connectors/{conns[0].id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert r2.status_code == 200
    assert len(r2.json()["connectors"]) == 1
    assert r2.json()["connectors"][0]["status"] == "Reserved"

    # 3. Nested path alias
    r3 = client.get(
        f"/api/v1/stations/{station.id}/chargers/{charger.id}/connectors/{conns[0].id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert r3.status_code == 200
    assert r3.json()["connectors"][0]["status"] == "Reserved"


def test_tc_f2_21_integration_with_live_status_display(client, db_session):
    """
    REQ-F2-21 & REQ-F2-18: Live connector status display automatically reflects Reserved.
    """
    operator = _make_user(
        db_session,
        name="Op Live",
        email="op_live@example.com",
        phone="+919999900012",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Live",
        email="drv_live@example.com",
        phone="+919999900013",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    now = datetime.now(timezone.utc)

    # Before booking: both connectors Available
    r_before = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert r_before.status_code == 200
    assert r_before.json()["available_connectors"] == 2
    assert r_before.json()["reserved_connectors"] == 0

    # Create confirmed booking in 7 minutes
    b = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conns[0].id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=7),
        end_time=now + timedelta(minutes=67),
    )
    db_session.add(b)
    db_session.commit()

    # After booking: live-status-display shows Reserved
    r_after = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert r_after.status_code == 200
    data = r_after.json()
    assert data["available_connectors"] == 1
    assert data["reserved_connectors"] == 1
    conn0 = next(c for c in data["connectors"] if c["connector_id"] == conns[0].id)
    assert conn0["status"] == "Reserved"

    # Filter by status=Reserved
    r_filtered = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}&status=Reserved",
        headers=_auth_header(driver),
    )
    assert r_filtered.status_code == 200
    assert len(r_filtered.json()["connectors"]) == 1
    assert r_filtered.json()["connectors"][0]["connector_id"] == conns[0].id


def test_tc_f2_21_parameter_validation_and_errors(client, db_session):
    """
    REQ-F2-21: Parameter validation returns 422 for malformed input and 404 for missing resources.
    """
    operator = _make_user(
        db_session,
        name="Op Val",
        email="op_val@example.com",
        phone="+919999900014",
        role=UserRole.OPERATOR,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    headers = _auth_header(operator)

    # 1. Neither station_id nor connector_id -> 422
    r_none = client.get("/api/v1/stations/reserved-status", headers=headers)
    assert r_none.status_code == 422

    # 2. Negative station_id -> 422
    r_neg_station = client.get(
        "/api/v1/stations/reserved-status?station_id=-1", headers=headers
    )
    assert r_neg_station.status_code == 422

    # 3. Negative connector_id -> 422
    r_neg_conn = client.get(
        "/api/v1/stations/reserved-status?connector_id=-5", headers=headers
    )
    assert r_neg_conn.status_code == 422

    # 4. Out-of-range window_minutes (< 1 or > 120) -> 422
    r_zero_win = client.get(
        f"/api/v1/stations/reserved-status?station_id={station.id}&window_minutes=0",
        headers=headers,
    )
    assert r_zero_win.status_code == 422

    r_high_win = client.get(
        f"/api/v1/stations/reserved-status?station_id={station.id}&window_minutes=121",
        headers=headers,
    )
    assert r_high_win.status_code == 422

    # 5. Non-existent station -> 404
    r_not_found = client.get(
        "/api/v1/stations/reserved-status?station_id=999999", headers=headers
    )
    assert r_not_found.status_code == 404

    # 6. Non-existent connector -> 404
    r_conn_not_found = client.get(
        "/api/v1/stations/reserved-status?connector_id=999999", headers=headers
    )
    assert r_conn_not_found.status_code == 404

    # 7. Unit validation function
    with pytest.raises(HTTPException) as exc:
        validate_reserved_status_params(None, None)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        validate_reserved_status_params(station_id=-2)
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        validate_reserved_status_params(station_id=1, window_minutes=200)
    assert exc.value.status_code == 422


def test_tc_f2_21_rbac_and_tenancy_isolation(client, db_session):
    """
    REQ-F2-21: Unauthenticated -> 401, Driver -> 404 for unapproved station,
    Operator -> 403 for foreign station, Admin -> unrestricted access.
    """
    op1 = _make_user(
        db_session,
        name="Op Tenancy 1",
        email="op_tenancy1@example.com",
        phone="+919999900015",
        role=UserRole.OPERATOR,
    )
    op2 = _make_user(
        db_session,
        name="Op Tenancy 2",
        email="op_tenancy2@example.com",
        phone="+919999900016",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Tenancy",
        email="drv_tenancy@example.com",
        phone="+919999900017",
        role=UserRole.DRIVER,
    )
    admin = _make_user(
        db_session,
        name="Admin Tenancy",
        email="admin_tenancy@example.com",
        phone="+919999900018",
        role=UserRole.ADMIN,
    )

    station1, _, _ = _seed_reservation_test_station(
        db_session, op1, name="Approved Station", status_val=StationStatus.APPROVED
    )
    pending_station, _, _ = _seed_reservation_test_station(
        db_session, op1, name="Pending Station", status_val=StationStatus.PENDING
    )

    # 1. Unauthenticated -> 401
    r_unauth = client.get(f"/api/v1/stations/reserved-status?station_id={station1.id}")
    assert r_unauth.status_code == 401

    # 2. Driver sees approved station (200), but gets 404 for pending station
    r_drv_appr = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(driver),
    )
    assert r_drv_appr.status_code == 200

    r_drv_pend = client.get(
        f"/api/v1/stations/reserved-status?station_id={pending_station.id}",
        headers=_auth_header(driver),
    )
    assert r_drv_pend.status_code == 404

    # 3. Foreign operator accessing Station 1 -> 403 Forbidden
    r_op2_denied = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(op2),
    )
    assert r_op2_denied.status_code == 403

    # 4. Owner operator accessing Station 1 -> 200 OK
    r_op1_ok = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(op1),
    )
    assert r_op1_ok.status_code == 200

    # 5. Admin has unrestricted access -> 200 OK
    r_admin_ok = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(admin),
    )
    assert r_admin_ok.status_code == 200

    # 6. Inactive charger hidden from driver but visible to operator
    inactive_charger = Charger(
        station_id=station1.id,
        name="Inactive Unit",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-INACTIVE",
        is_active=False,
    )
    db_session.add(inactive_charger)
    db_session.flush()
    c_inact = Connector(
        charger_id=inactive_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime.now(timezone.utc),
    )
    db_session.add(c_inact)
    db_session.commit()

    r_drv_inact = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(driver),
    )
    assert r_drv_inact.status_code == 200
    assert all(c["charger_id"] != inactive_charger.id for c in r_drv_inact.json()["connectors"])

    r_op_inact = client.get(
        f"/api/v1/stations/reserved-status?station_id={station1.id}",
        headers=_auth_header(op1),
    )
    assert r_op_inact.status_code == 200
    assert any(c["charger_id"] == inactive_charger.id for c in r_op_inact.json()["connectors"])


def test_stc_f2_21_system_workflow_lifecycle(client, db_session):
    """
    STC-F2-21: Full end-to-end lifecycle verification.
    1. Seed station and available connector.
    2. Check initial status is Available.
    3. Confirmed booking created starting in 14 minutes.
    4. Reserved status verified across endpoints.
    5. Booking cancelled -> connector immediately reverts to Available.
    """
    operator = _make_user(
        db_session,
        name="Op Lifecycle",
        email="op_life@example.com",
        phone="+919999900019",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Drv Lifecycle",
        email="drv_life@example.com",
        phone="+919999900020",
        role=UserRole.DRIVER,
    )
    station, charger, conns = _seed_reservation_test_station(db_session, operator)
    target_conn = conns[0]
    now = datetime.now(timezone.utc)

    # Step 1: Initial state is Available
    init_res = client.get(
        f"/api/v1/stations/{station.id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert init_res.status_code == 200
    assert init_res.json()["reserved_connectors"] == 0
    assert init_res.json()["connectors"][0]["status"] == "Available"

    # Step 2: Create confirmed booking starting in 14m
    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=target_conn.id,
        status=BookingStatus.CONFIRMED,
        start_time=now + timedelta(minutes=14),
        end_time=now + timedelta(minutes=74),
    )
    db_session.add(booking)
    db_session.commit()

    # Step 3: Verify Reserved status
    reserved_res = client.get(
        f"/api/v1/stations/{station.id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert reserved_res.status_code == 200
    data = reserved_res.json()
    assert data["reserved_connectors"] == 1
    c_item = next(c for c in data["connectors"] if c["connector_id"] == target_conn.id)
    assert c_item["status"] == "Reserved"
    assert c_item["is_reserved"] is True
    assert c_item["booking_id"] == booking.id
    assert c_item["minutes_until_booking"] == pytest.approx(14.0, abs=0.2)

    # Step 4: Cancel booking -> reverts to Available
    booking.status = BookingStatus.CANCELLED
    db_session.commit()

    after_cancel = client.get(
        f"/api/v1/stations/{station.id}/reserved-status",
        headers=_auth_header(driver),
    )
    assert after_cancel.status_code == 200
    assert after_cancel.json()["reserved_connectors"] == 0
    c_item_cancel = next(
        c for c in after_cancel.json()["connectors"] if c["connector_id"] == target_conn.id
    )
    assert c_item_cancel["status"] == "Available"
    assert c_item_cancel["is_reserved"] is False
