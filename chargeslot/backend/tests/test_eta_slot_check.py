"""
Test Suite for ETA versus Slot Check (REQ-F2-27 / TC-F2-27 / STC-F2-27 / CS19-053).

Requirements Under Test:
- REQ-F2-27: "The system shall, for a confirmed booking, compare the driver's estimated
  arrival time with the slot start time, and shall warn the driver and offer to reschedule,
  extend or cancel when the projected arrival is later than the slot start plus the grace period."
- Grace period: default 15 minutes (BR-06 / REQ-F3-25).
- Timeliness statuses: 'on_time', 'late_within_grace', 'late_beyond_grace'.
- Warning messages and available action options ('reschedule', 'extend', 'cancel').
- Reschedule options offering alternative slots later at the same station.
- Inactive booking rejection (Cancelled, Completed, No-Show).
- RBAC and data scope enforcement:
  - Driver can only check their own bookings (403 for foreign booking).
  - Operator can only check bookings at their own stations.
  - Admin has full access.
- SW Architecture endpoints:
  - GET /api/v1/stations/eta-versus-slot-check
  - GET /api/v1/stations/{station_id}/eta-versus-slot-check
  - GET /api/v1/navigation/eta-versus-slot-check
  - GET /api/v1/navigation/bookings/{booking_id}/eta-check
- System lifecycle test (STC-F2-27).
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, ConnectorType, CurrentType
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.eta import (
    DEFAULT_GRACE_PERIOD_MINUTES,
    check_driver_eta_versus_slot,
)
from app.schemas.navigation import ETASlotStatus
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
        hashed_password=hash_password("SecurePass123!"),
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


def _seed_station_and_booking(
    db_session,
    operator: User,
    driver: User,
    *,
    station_lat: float = 12.9716,
    station_lon: float = 77.5946,
    slot_start: datetime,
    slot_duration_minutes: int = 60,
    booking_status: BookingStatus = BookingStatus.CONFIRMED,
) -> tuple[Station, Booking]:
    station = Station(
        name=f"Station for Booking {driver.name}",
        address="Koramangala 5th Block, Bangalore",
        latitude=station_lat,
        longitude=station_lon,
        contact_phone="9876543210",
        contact_email="koramangala@chargeslot.com",
        operating_hours="24 hours",
        status=StationStatus.APPROVED,
        is_active=True,
        operator_id=operator.id,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)

    charger = Charger(
        station_id=station.id,
        name="Charger 1",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id=f"gw-charger-{driver.id}-{operator.id}",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.commit()
    db_session.refresh(charger)

    connector = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)

    slot_end = slot_start + timedelta(minutes=slot_duration_minutes)
    booking = Booking(
        user_id=driver.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=connector.id,
        start_time=slot_start,
        end_time=slot_end,
        status=booking_status,
        booking_type="manual",
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)

    return station, booking


# ===========================================================================
# TC-F2-27: Unit & Service Logic Tests
# ===========================================================================


class TestETASlotCheckServiceLogic:
    def test_on_time_arrival(self, db_session):
        operator = _make_user(db_session, name="Op ETA1", email="opeta1@test.com", phone="9000000201", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver ETA1", email="dreta1@test.com", phone="9000000202", role=UserRole.DRIVER)

        now = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        # Slot starts at 15:00 (1 hour from now)
        slot_start = now + timedelta(hours=1)
        station, booking = _seed_station_and_booking(db_session, operator, driver, slot_start=slot_start)

        # Driver is 5 km away (~10-15 mins travel time)
        driver_lat = station.latitude - 0.04
        driver_lon = station.longitude - 0.04

        resp = check_driver_eta_versus_slot(
            db=db_session,
            user=driver,
            booking_id=booking.id,
            driver_latitude=driver_lat,
            driver_longitude=driver_lon,
            current_time=now,
        )

        assert resp.booking_id == booking.id
        assert resp.status == ETASlotStatus.ON_TIME.value
        assert resp.is_late is False
        assert resp.projected_late_beyond_grace is False
        assert resp.delay_minutes == 0.0
        assert resp.warning_message is None
        assert resp.action_options == []

    def test_late_within_grace_period(self, db_session):
        operator = _make_user(db_session, name="Op ETA2", email="opeta2@test.com", phone="9000000203", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver ETA2", email="dreta2@test.com", phone="9000000204", role=UserRole.DRIVER)

        now = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        # Slot starts at 14:15 (15 minutes from now)
        slot_start = now + timedelta(minutes=15)
        station, booking = _seed_station_and_booking(db_session, operator, driver, slot_start=slot_start)

        # Driver is ~10 km away (~17 mins travel time, arrives ~14:17, which is 7 mins late, <= 15 min grace)
        driver_lat = station.latitude - 0.08
        driver_lon = station.longitude - 0.08

        resp = check_driver_eta_versus_slot(
            db=db_session,
            user=driver,
            booking_id=booking.id,
            driver_latitude=driver_lat,
            driver_longitude=driver_lon,
            current_time=now,
            traffic_condition="normal",
        )

        assert resp.status == ETASlotStatus.LATE_WITHIN_GRACE.value
        assert resp.is_late is True
        assert resp.projected_late_beyond_grace is False
        assert resp.delay_minutes > 0
        assert resp.warning_message is not None
        assert "grace period" in resp.warning_message.lower()
        assert "reschedule" in resp.action_options
        assert "extend" in resp.action_options
        assert "cancel" in resp.action_options
        assert len(resp.reschedule_options) > 0

    def test_late_beyond_grace_period(self, db_session):
        operator = _make_user(db_session, name="Op ETA3", email="opeta3@test.com", phone="9000000205", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver ETA3", email="dreta3@test.com", phone="9000000206", role=UserRole.DRIVER)

        now = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        # Slot starts right now at 14:00 (deadline 14:15)
        slot_start = now
        station, booking = _seed_station_and_booking(db_session, operator, driver, slot_start=slot_start)

        # Driver is 25 km away (~40 mins travel time under normal traffic, arrives ~14:40 > 14:15)
        driver_lat = station.latitude - 0.20
        driver_lon = station.longitude - 0.20

        resp = check_driver_eta_versus_slot(
            db=db_session,
            user=driver,
            booking_id=booking.id,
            driver_latitude=driver_lat,
            driver_longitude=driver_lon,
            current_time=now,
            traffic_condition="heavy",
        )

        assert resp.status == ETASlotStatus.LATE_BEYOND_GRACE.value
        assert resp.is_late is True
        assert resp.projected_late_beyond_grace is True
        assert resp.delay_minutes > DEFAULT_GRACE_PERIOD_MINUTES
        assert resp.warning_message is not None
        assert "exceeding" in resp.warning_message.lower() or "no-show" in resp.warning_message.lower()
        assert resp.can_reschedule is True
        assert resp.can_extend is True
        assert resp.can_cancel is True
        assert len(resp.reschedule_options) > 0

    def test_configurable_grace_period(self, db_session):
        operator = _make_user(db_session, name="Op ETA4", email="opeta4@test.com", phone="9000000207", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver ETA4", email="dreta4@test.com", phone="9000000208", role=UserRole.DRIVER)

        now = datetime(2026, 11, 14, 14, 0, tzinfo=timezone.utc)
        slot_start = now + timedelta(minutes=5)
        station, booking = _seed_station_and_booking(db_session, operator, driver, slot_start=slot_start)

        # 12 min travel time -> arrives 14:12 (7 mins after slot start)
        # With grace_period=15: late_within_grace
        # With grace_period=5: late_beyond_grace
        driver_lat = station.latitude - 0.06
        driver_lon = station.longitude - 0.06

        resp_15 = check_driver_eta_versus_slot(
            db=db_session,
            user=driver,
            booking_id=booking.id,
            driver_latitude=driver_lat,
            driver_longitude=driver_lon,
            current_time=now,
            grace_period_minutes=15,
        )
        assert resp_15.status == ETASlotStatus.LATE_WITHIN_GRACE.value

        resp_5 = check_driver_eta_versus_slot(
            db=db_session,
            user=driver,
            booking_id=booking.id,
            driver_latitude=driver_lat,
            driver_longitude=driver_lon,
            current_time=now,
            grace_period_minutes=5,
        )
        assert resp_5.status == ETASlotStatus.LATE_BEYOND_GRACE.value

    def test_inactive_booking_rejected(self, db_session):
        operator = _make_user(db_session, name="Op InactB", email="opinactb@test.com", phone="9000000209", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver InactB", email="drinactb@test.com", phone="9000000210", role=UserRole.DRIVER)
        now = datetime.now(timezone.utc)
        _, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=now,
            booking_status=BookingStatus.CANCELLED,
        )

        with pytest.raises(HTTPException) as exc_info:
            check_driver_eta_versus_slot(db_session, driver, booking.id, 12.9, 77.5)
        assert exc_info.value.status_code == 400
        assert "inactive status" in exc_info.value.detail.lower()


# ===========================================================================
# TC-F2-27: RBAC and Booking Isolation
# ===========================================================================


class TestETASlotCheckRBAC:
    def test_driver_cannot_check_foreign_booking(self, db_session):
        operator = _make_user(db_session, name="Op RBAC B1", email="oprbacb1@test.com", phone="9000000220", role=UserRole.OPERATOR)
        driver_a = _make_user(db_session, name="Driver A", email="dra@test.com", phone="9000000221", role=UserRole.DRIVER)
        driver_b = _make_user(db_session, name="Driver B", email="drb@test.com", phone="9000000222", role=UserRole.DRIVER)

        _, booking_a = _seed_station_and_booking(
            db_session,
            operator,
            driver_a,
            slot_start=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        with pytest.raises(HTTPException) as exc_info:
            check_driver_eta_versus_slot(db_session, driver_b, booking_a.id, 12.9, 77.5)
        assert exc_info.value.status_code == 403
        assert "Permission denied" in exc_info.value.detail

    def test_operator_cannot_check_foreign_station_booking(self, db_session):
        operator_a = _make_user(db_session, name="Op St A", email="opsta@test.com", phone="9000000223", role=UserRole.OPERATOR)
        operator_b = _make_user(db_session, name="Op St B", email="opstb@test.com", phone="9000000224", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver C", email="drc@test.com", phone="9000000225", role=UserRole.DRIVER)

        _, booking_a = _seed_station_and_booking(
            db_session,
            operator_a,
            driver,
            slot_start=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        with pytest.raises(HTTPException) as exc_info:
            check_driver_eta_versus_slot(db_session, operator_b, booking_a.id, 12.9, 77.5)
        assert exc_info.value.status_code == 403

    def test_operator_and_admin_can_check_applicable_bookings(self, db_session):
        operator = _make_user(db_session, name="Op Own St", email="opownst@test.com", phone="9000000226", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver D", email="drd@test.com", phone="9000000227", role=UserRole.DRIVER)
        admin = _make_user(db_session, name="Super Admin ETA", email="admineta@test.com", phone="9000000228", role=UserRole.ADMIN)

        _, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=datetime.now(timezone.utc) + timedelta(hours=1),
        )

        # Operator of the station has access
        resp_op = check_driver_eta_versus_slot(db_session, operator, booking.id, 12.9, 77.5)
        assert resp_op.booking_id == booking.id

        # Admin has access
        resp_adm = check_driver_eta_versus_slot(db_session, admin, booking.id, 12.9, 77.5)
        assert resp_adm.booking_id == booking.id


# ===========================================================================
# TC-F2-27: HTTP Endpoints Integration Tests
# ===========================================================================


class TestETASlotCheckEndpoints:
    def test_sw_architecture_eta_query(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op EndETA1", email="opendeta1@test.com", phone="9000000230", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver EndETA1", email="drendeta1@test.com", phone="9000000231", role=UserRole.DRIVER)
        station, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=datetime.now(timezone.utc) + timedelta(minutes=45),
        )

        response = client.get(
            "/api/v1/stations/eta-versus-slot-check",
            params={
                "booking_id": booking.id,
                "latitude": 12.9200,
                "longitude": 77.5800,
                "traffic_condition": "normal",
            },
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["booking_id"] == booking.id
        assert data["station_id"] == station.id
        assert "status" in data
        assert "estimated_arrival_time" in data
        assert "delay_minutes" in data

    def test_station_path_eta_check(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op EndETA2", email="opendeta2@test.com", phone="9000000232", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver EndETA2", email="drendeta2@test.com", phone="9000000233", role=UserRole.DRIVER)
        station, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=datetime.now(timezone.utc) + timedelta(minutes=30),
        )

        response = client.get(
            f"/api/v1/stations/{station.id}/eta-versus-slot-check",
            params={
                "booking_id": booking.id,
                "latitude": 12.9300,
                "longitude": 77.5900,
            },
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["booking_id"] == booking.id

    def test_navigation_module_endpoints(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op NavETA", email="opnaveta@test.com", phone="9000000234", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver NavETA", email="drnaveta@test.com", phone="9000000235", role=UserRole.DRIVER)
        _, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=datetime.now(timezone.utc) + timedelta(minutes=60),
        )

        # GET /api/v1/navigation/eta-versus-slot-check
        resp1 = client.get(
            "/api/v1/navigation/eta-versus-slot-check",
            params={
                "booking_id": booking.id,
                "latitude": 12.9100,
                "longitude": 77.5700,
            },
            headers=_auth_header(driver),
        )
        assert resp1.status_code == 200

        # GET /api/v1/navigation/bookings/{booking_id}/eta-check
        resp2 = client.get(
            f"/api/v1/navigation/bookings/{booking.id}/eta-check",
            params={
                "latitude": 12.9100,
                "longitude": 77.5700,
            },
            headers=_auth_header(driver),
        )
        assert resp2.status_code == 200
        assert resp2.json()["booking_id"] == booking.id


# ===========================================================================
# STC-F2-27: System Integration & Lifecycle Test
# ===========================================================================


class TestETASlotCheckSystemLifecycle:
    def test_system_eta_versus_slot_check_lifecycle(self, client: TestClient, db_session):
        """
        STC-F2-27 Lifecycle Test:
        1. Driver has a confirmed booking starting at 14:00.
        2. At 13:40, driver checks ETA from 5 km away -> on time (status: on_time, no warnings).
        3. At 14:00, driver is still 15 km away with heavy traffic -> projected arrival at 14:25.
        4. System detects projected arrival exceeds slot start + 15 min grace (14:15 deadline).
        5. Warning is raised with impending No-Show consequence; offers reschedule, extend, cancel.
        6. Candidate reschedule slots are returned for driver to rebook.
        """
        operator = _make_user(db_session, name="Sys Op ETA", email="sysopeta@chargeslot.com", phone="9555555551", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Sys Driver ETA", email="sysdreta@chargeslot.com", phone="9555555552", role=UserRole.DRIVER)

        now = datetime.now(timezone.utc)
        slot_start = now + timedelta(minutes=45)
        station, booking = _seed_station_and_booking(
            db_session,
            operator,
            driver,
            slot_start=slot_start,
        )

        # 2. Check from close by (on-time)
        driver_lat_near = station.latitude - 0.01
        driver_lon_near = station.longitude - 0.01

        resp_ontime = client.get(
            "/api/v1/stations/eta-versus-slot-check",
            params={
                "booking_id": booking.id,
                "latitude": driver_lat_near,
                "longitude": driver_lon_near,
                "traffic_condition": "low",
            },
            headers=_auth_header(driver),
        )
        assert resp_ontime.status_code == 200
        data_ontime = resp_ontime.json()
        assert data_ontime["status"] == "on_time"
        assert data_ontime["is_late"] is False

        # 3. Check from very far away under severe traffic (delayed beyond grace)
        driver_lat_far = station.latitude - 0.40
        driver_lon_far = station.longitude - 0.40

        resp_late = client.get(
            "/api/v1/stations/eta-versus-slot-check",
            params={
                "booking_id": booking.id,
                "latitude": driver_lat_far,
                "longitude": driver_lon_far,
                "traffic_condition": "severe",
            },
            headers=_auth_header(driver),
        )
        assert resp_late.status_code == 200
        data_late = resp_late.json()

        # 4 & 5. Verify late beyond grace and warning
        assert data_late["status"] == "late_beyond_grace"
        assert data_late["is_late"] is True
        assert data_late["projected_late_beyond_grace"] is True
        assert data_late["warning_message"] is not None
        assert "no-show" in data_late["warning_message"].lower() or "exceeding" in data_late["warning_message"].lower()

        # 6. Verify action options and reschedule slots
        assert "reschedule" in data_late["action_options"]
        assert "extend" in data_late["action_options"]
        assert "cancel" in data_late["action_options"]
        assert len(data_late["reschedule_options"]) > 0
        assert data_late["reschedule_options"][0]["available"] is True
