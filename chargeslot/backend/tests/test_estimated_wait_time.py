"""
Test Suite for Estimated Wait Time (REQ-F2-24 / TC-F2-24 / STC-F2-24 / CS19-050).

Requirements Under Test:
- REQ-F2-24: "The system shall display an estimated wait time when all compatible
  connectors at a station are occupied, calculated from the expected end of the active sessions."
- Immediate availability (0 mins) when at least one compatible connector is free.
- Earliest completion calculation across occupied compatible connectors.
- Vehicle compatibility filtering (CCS2, Type 2, CHAdeMO, GB/T).
- Faulted, offline, and maintenance connectors excluded from availability and wait estimation.
- RBAC and tenancy enforcement.
- SW Architecture routes: /api/v1/stations/estimated-wait-time and path aliases.
"""

from datetime import datetime, time, timedelta, timezone
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.dashboard.wait import (
    calculate_connector_remaining_minutes,
    get_station_estimated_wait_time,
    normalize_connector_type,
    validate_wait_time_params,
)
from app.models.booking import Booking, BookingStatus
from app.models.charger import (
    Charger,
    Connector,
    ConnectorStatus,
    ConnectorType,
    CurrentType,
)
from app.models.connector_status_event import ConnectorStatusEvent
from app.models.maintenance import MaintenanceWindow
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
# Unit Tests for Parameter Validation & Calculations (TC-F2-24)
# ---------------------------------------------------------------------------


def test_validate_wait_time_params_valid():
    """Valid station_id and connector_type pass validation."""
    s_id, conn_type = validate_wait_time_params(station_id=1, connector_type="CCS2")
    assert s_id == 1
    assert conn_type == "CCS2"


def test_validate_wait_time_params_invalid_station():
    """Invalid station_id raises 422."""
    with pytest.raises(HTTPException) as exc_none:
        validate_wait_time_params(station_id=None)
    assert exc_none.value.status_code == 422

    with pytest.raises(HTTPException) as exc_zero:
        validate_wait_time_params(station_id=0)
    assert exc_zero.value.status_code == 422


def test_normalize_connector_type_variants():
    """Normalize connector type handles casing and punctuation variants."""
    assert normalize_connector_type("ccs2") == "CCS2"
    assert normalize_connector_type("Type 2") == "Type 2"
    assert normalize_connector_type("TYPE_2") == "Type 2"
    assert normalize_connector_type("chademo") == "CHAdeMO"
    assert normalize_connector_type("gbt") == "GB/T"

    with pytest.raises(HTTPException) as exc_invalid:
        normalize_connector_type("TeslaSupercharger")
    assert exc_invalid.value.status_code == 422
    assert "Invalid connector_type" in exc_invalid.value.detail


def test_calculate_connector_remaining_minutes():
    """Verify remaining minutes calculation from active booking vs fallback."""
    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    end_time = datetime(2026, 11, 14, 12, 25, tzinfo=timezone.utc)

    # 1. With active booking of 25 minutes remaining
    booking = Booking(
        id=42,
        user_id=1,
        station_id=1,
        charger_id=1,
        connector_id=1,
        start_time=datetime(2026, 11, 14, 11, 45, tzinfo=timezone.utc),
        end_time=end_time,
        status=BookingStatus.ACTIVE,
    )
    exp_end, rem_mins, b_id = calculate_connector_remaining_minutes(
        connector_id=1,
        charger_id=1,
        connector_type_str="CCS2",
        active_bookings=[booking],
        latest_event=None,
        ref_now=ref_now,
    )
    assert exp_end == end_time
    assert rem_mins == 25.0
    assert b_id == 42

    # 2. Fallback when no active booking exists
    exp_fallback, rem_fallback, b_none = calculate_connector_remaining_minutes(
        connector_id=2,
        charger_id=1,
        connector_type_str="CCS2",
        active_bookings=[],
        latest_event=None,
        ref_now=ref_now,
        default_session_minutes=30,
    )
    assert rem_fallback == 30.0
    assert b_none is None


# ---------------------------------------------------------------------------
# Integration Tests: Estimated Wait Time (TC-F2-24)
# ---------------------------------------------------------------------------


def test_wait_time_zero_when_compatible_connector_available(db_session):
    """
    REQ-F2-24: If at least one compatible connector is Available,
    estimated wait time is 0.0 minutes and all_compatible_occupied is False.
    """
    operator = _make_user(db_session, name="Op 1", email="op1@wait.test", phone="9000000201", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 1", email="dr1@wait.test", phone="9000000202", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)

    # Both connectors are AVAILABLE
    result = get_station_estimated_wait_time(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_type="CCS2",
    )

    assert result.station_id == station.id
    assert result.total_compatible_connectors == 1
    assert result.available_compatible_connectors == 1
    assert result.occupied_compatible_connectors == 0
    assert result.all_compatible_occupied is False
    assert result.estimated_wait_minutes == 0.0
    assert "No wait time required" in result.message


def test_wait_time_when_all_compatible_occupied(db_session):
    """
    REQ-F2-24: When all compatible connectors at a station are occupied,
    the system calculates estimated wait time from the expected end of active sessions.
    """
    operator = _make_user(db_session, name="Op 2", email="op2@wait.test", phone="9000000203", role=UserRole.OPERATOR)
    driver1 = _make_user(db_session, name="Driver 2A", email="dr2a@wait.test", phone="9000000204", role=UserRole.DRIVER)
    driver2 = _make_user(db_session, name="Driver 2B", email="dr2b@wait.test", phone="9000000205", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)

    # Both connectors are CCS2
    conn2.connector_type = ConnectorType.CCS2
    conn1.status = ConnectorStatus.OCCUPIED
    conn2.status = ConnectorStatus.OCCUPIED
    db_session.commit()

    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)

    # Active session on conn1 ending at 12:40 (40 mins remaining)
    b1 = Booking(
        user_id=driver1.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn1.id,
        start_time=datetime(2026, 11, 14, 11, 40, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 14, 12, 40, tzinfo=timezone.utc),
        status=BookingStatus.ACTIVE,
    )
    # Active session on conn2 ending at 12:15 (15 mins remaining)
    b2 = Booking(
        user_id=driver2.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn2.id,
        start_time=datetime(2026, 11, 14, 11, 30, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 14, 12, 15, tzinfo=timezone.utc),
        status=BookingStatus.ACTIVE,
    )
    db_session.add_all([b1, b2])
    db_session.commit()

    result = get_station_estimated_wait_time(
        db=db_session,
        user=driver1,
        station_id=station.id,
        connector_type="CCS2",
        now_utc=ref_now,
    )

    assert result.total_compatible_connectors == 2
    assert result.available_compatible_connectors == 0
    assert result.occupied_compatible_connectors == 2
    assert result.all_compatible_occupied is True

    # Earliest to free up is conn2 (15 minutes remaining)
    assert result.estimated_wait_minutes == 15.0
    assert result.earliest_free_connector_id == conn2.id
    assert result.expected_available_at == datetime(2026, 11, 14, 12, 15, tzinfo=timezone.utc)
    assert "Estimated wait time: 15 minute(s)" in result.message


def test_wait_time_compatibility_with_vehicle(db_session):
    """
    Wait time evaluates compatibility based on vehicle's connector type:
    If driver has a CCS2 vehicle, only CCS2 connectors are considered.
    Even if Type 2 is available, wait time reflects occupied CCS2 connector.
    """
    operator = _make_user(db_session, name="Op 3", email="op3@wait.test", phone="9000000206", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 3", email="dr3@wait.test", phone="9000000207", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)
    # conn1: CCS2, conn2: Type 2

    # Driver vehicle has CCS2 connector
    veh = Vehicle(
        user_id=driver.id,
        make="Kia",
        model="EV6",
        battery_kwh=77.4,
        max_ac_kw=11.0,
        max_dc_kw=240.0,
        consumption_kwh_100km=18.0,
        registration_no="MH02CD3456",
        connector_type=ConnectorType.CCS2,
        is_default=True,
    )
    db_session.add(veh)

    # conn1 (CCS2) is occupied with 20 mins remaining
    conn1.status = ConnectorStatus.OCCUPIED
    # conn2 (Type 2) is Available
    conn2.status = ConnectorStatus.AVAILABLE

    ref_now = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)
    b = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn1.id,
        vehicle_id=veh.id,
        start_time=datetime(2026, 11, 14, 11, 50, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 14, 12, 20, tzinfo=timezone.utc),
        status=BookingStatus.ACTIVE,
    )
    db_session.add(b)
    db_session.commit()

    # Query with vehicle_id
    result = get_station_estimated_wait_time(
        db=db_session,
        user=driver,
        station_id=station.id,
        vehicle_id=veh.id,
        now_utc=ref_now,
    )

    # Only 1 compatible connector (conn1 CCS2), and it is occupied!
    assert result.total_compatible_connectors == 1
    assert result.vehicle_connector_type == "CCS2"
    assert result.available_compatible_connectors == 0
    assert result.occupied_compatible_connectors == 1
    assert result.all_compatible_occupied is True
    assert result.estimated_wait_minutes == 20.0
    assert result.earliest_free_connector_id == conn1.id


def test_wait_time_all_compatible_faulted_or_offline(db_session):
    """
    If all compatible connectors are Faulted or Offline,
    they cannot free up from an active session, so wait estimate is None.
    """
    operator = _make_user(db_session, name="Op 4", email="op4@wait.test", phone="9000000208", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 4", email="dr4@wait.test", phone="9000000209", role=UserRole.DRIVER)
    station, charger, conn1, _ = _seed_test_station(db_session, operator)

    conn1.status = ConnectorStatus.FAULTED
    db_session.commit()

    result = get_station_estimated_wait_time(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_type="CCS2",
    )

    assert result.total_compatible_connectors == 1
    assert result.available_compatible_connectors == 0
    assert result.occupied_compatible_connectors == 0
    assert result.all_compatible_occupied is False
    assert result.estimated_wait_minutes is None
    assert "No wait estimate available" in result.message


# ---------------------------------------------------------------------------
# RBAC & Tenancy Tests
# ---------------------------------------------------------------------------


def test_driver_cannot_view_wait_time_for_pending_station(db_session):
    """Drivers receive 404 when querying wait time for a pending station."""
    operator = _make_user(db_session, name="Op 5", email="op5@wait.test", phone="9000000210", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 5", email="dr5@wait.test", phone="9000000211", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(
        db_session, operator, status=StationStatus.PENDING
    )

    with pytest.raises(HTTPException) as exc_info:
        get_station_estimated_wait_time(
            db=db_session,
            user=driver,
            station_id=station.id,
        )
    assert exc_info.value.status_code == 404


def test_driver_foreign_vehicle_forbidden(db_session):
    """Drivers cannot query wait time using another driver's vehicle (403)."""
    operator = _make_user(db_session, name="Op 6", email="op6@wait.test", phone="9000000212", role=UserRole.OPERATOR)
    driver1 = _make_user(db_session, name="Driver 6A", email="dr6a@wait.test", phone="9000000213", role=UserRole.DRIVER)
    driver2 = _make_user(db_session, name="Driver 6B", email="dr6b@wait.test", phone="9000000214", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    veh = Vehicle(
        user_id=driver2.id,
        make="Tata",
        model="Tigor EV",
        battery_kwh=26.0,
        max_ac_kw=3.3,
        max_dc_kw=25.0,
        consumption_kwh_100km=13.0,
        registration_no="DL04EF5678",
        connector_type=ConnectorType.CCS2,
        is_default=True,
    )
    db_session.add(veh)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        get_station_estimated_wait_time(
            db=db_session,
            user=driver1,
            station_id=station.id,
            vehicle_id=veh.id,
        )
    assert exc_info.value.status_code == 403


def test_operator_foreign_station_wait_time_forbidden(db_session):
    """Operators receive 403 when requesting wait time for another operator's station."""
    op1 = _make_user(db_session, name="Op 7A", email="op7a@wait.test", phone="9000000215", role=UserRole.OPERATOR)
    op2 = _make_user(db_session, name="Op 7B", email="op7b@wait.test", phone="9000000216", role=UserRole.OPERATOR)
    station, _, _, _ = _seed_test_station(db_session, op1)

    with pytest.raises(HTTPException) as exc_info:
        get_station_estimated_wait_time(
            db=db_session,
            user=op2,
            station_id=station.id,
        )
    assert exc_info.value.status_code == 403


def test_admin_can_view_any_station_wait_time(db_session):
    """Administrators can view estimated wait time for any station."""
    op = _make_user(db_session, name="Op 8", email="op8@wait.test", phone="9000000217", role=UserRole.OPERATOR)
    admin = _make_user(db_session, name="Admin", email="admin@wait.test", phone="9000000218", role=UserRole.ADMIN)
    station, _, _, _ = _seed_test_station(
        db_session, op, status=StationStatus.PENDING
    )

    result = get_station_estimated_wait_time(
        db=db_session,
        user=admin,
        station_id=station.id,
    )
    assert result.station_id == station.id


# ---------------------------------------------------------------------------
# API Route Tests
# ---------------------------------------------------------------------------


def test_api_estimated_wait_time_query_route(client: TestClient, db_session):
    """GET /api/v1/stations/estimated-wait-time (SW Architecture Route)."""
    operator = _make_user(db_session, name="Op 9", email="op9@wait.test", phone="9000000219", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 9", email="dr9@wait.test", phone="9000000220", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/estimated-wait-time?station_id={station.id}&connector_type=CCS2",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["station_id"] == station.id
    assert data["available_compatible_connectors"] == 1
    assert data["estimated_wait_minutes"] == 0.0


def test_api_estimated_wait_time_path_route(client: TestClient, db_session):
    """GET /api/v1/stations/{station_id}/estimated-wait-time and alias /wait-time."""
    operator = _make_user(db_session, name="Op 10", email="op10@wait.test", phone="9000000221", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver 10", email="dr10@wait.test", phone="9000000222", role=UserRole.DRIVER)
    station, _, _, _ = _seed_test_station(db_session, operator)

    headers = _auth_header(driver)
    resp = client.get(
        f"/api/v1/stations/{station.id}/estimated-wait-time",
        headers=headers,
    )
    assert resp.status_code == 200

    resp_alias = client.get(
        f"/api/v1/stations/{station.id}/wait-time",
        headers=headers,
    )
    assert resp_alias.status_code == 200


# ---------------------------------------------------------------------------
# System Test: STC-F2-24 (Full Wait Time Estimation Lifecycle)
# ---------------------------------------------------------------------------


def test_stc_f2_24_full_wait_time_lifecycle(client: TestClient, db_session):
    """
    STC-F2-24: End-to-end system test verifying estimated wait time lifecycle:
    1. Seed station with 2 CCS2 connectors.
    2. Connector 1 occupied with active session ending in 30 minutes.
    3. Connector 2 occupied with active session ending in 10 minutes.
    4. Driver queries wait time with CCS2 vehicle: all compatible connectors are occupied.
    5. Verify estimated wait time is 10 minutes (matching earliest session end).
    6. Complete session on Connector 2 -> Connector 2 becomes Available.
    7. Query wait time again: returns 0.0 minutes (immediate availability).
    """
    operator = _make_user(db_session, name="Op STC", email="opstc@wait.test", phone="9000000223", role=UserRole.OPERATOR)
    driver = _make_user(db_session, name="Driver STC", email="drstc@wait.test", phone="9000000224", role=UserRole.DRIVER)
    station, charger, conn1, conn2 = _seed_test_station(db_session, operator)

    conn2.connector_type = ConnectorType.CCS2
    conn1.status = ConnectorStatus.OCCUPIED
    conn2.status = ConnectorStatus.OCCUPIED
    db_session.commit()

    ref_now = datetime(2026, 11, 14, 15, 0, tzinfo=timezone.utc)

    # Active session on conn1 ending at 15:30 (30 mins remaining)
    b1 = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn1.id,
        start_time=datetime(2026, 11, 14, 14, 50, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 14, 15, 30, tzinfo=timezone.utc),
        status=BookingStatus.ACTIVE,
    )
    # Active session on conn2 ending at 15:10 (10 mins remaining)
    b2 = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=conn2.id,
        start_time=datetime(2026, 11, 14, 14, 40, tzinfo=timezone.utc),
        end_time=datetime(2026, 11, 14, 15, 10, tzinfo=timezone.utc),
        status=BookingStatus.ACTIVE,
    )
    db_session.add_all([b1, b2])
    db_session.commit()

    # Step 1: All occupied -> 10 mins wait
    result_busy = get_station_estimated_wait_time(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_type="CCS2",
        now_utc=ref_now,
    )
    assert result_busy.all_compatible_occupied is True
    assert result_busy.estimated_wait_minutes == 10.0
    assert result_busy.earliest_free_connector_id == conn2.id
    assert result_busy.expected_available_at == datetime(2026, 11, 14, 15, 10, tzinfo=timezone.utc)

    # Step 2: Complete session on conn2
    b2.status = BookingStatus.COMPLETED
    conn2.status = ConnectorStatus.AVAILABLE
    db_session.commit()

    # Step 3: Available connector -> 0 mins wait
    result_free = get_station_estimated_wait_time(
        db=db_session,
        user=driver,
        station_id=station.id,
        connector_type="CCS2",
        now_utc=ref_now,
    )
    assert result_free.all_compatible_occupied is False
    assert result_free.available_compatible_connectors == 1
    assert result_free.estimated_wait_minutes == 0.0
