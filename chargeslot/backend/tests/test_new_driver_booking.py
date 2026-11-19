"""
Test Suite: New Driver Auto-Provisioning & Slot Booking Capability.
Verifies that whenever a new driver registers an account, an EV vehicle is automatically
provisioned so they can immediately book a station slot without manual prerequisite steps.
"""

from datetime import datetime, timedelta, timezone
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.booking import BookingStatus


@pytest.fixture
def active_charging_station(db_session: Session) -> tuple[Station, Charger]:
    """Sets up an approved station with an operational CCS2 charger."""
    operator = User(
        name="Station Operator",
        email="operator_station@example.com",
        phone="+919111122222",
        hashed_password="hash",
        role=UserRole.OPERATOR,
        is_verified=True,
        is_active=True,
    )
    db_session.add(operator)
    db_session.flush()

    station = Station(
        operator_id=operator.id,
        name="Indiranagar Fast Hub",
        address="100 Feet Road, Indiranagar, Bangalore",
        latitude=12.9716,
        longitude=77.6412,
        contact_phone="+919888877777",
        price_per_kwh=18.5,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="CH-01",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(station)
    db_session.refresh(charger)
    return station, charger


def test_new_driver_registration_auto_provisions_vehicle(client: TestClient, db_session: Session):
    """
    When a new driver registers, a default EV vehicle is automatically provisioned
    with valid battery SoC and CCS2 connector specifications.
    """
    reg_payload = {
        "name": "Arjun Driver",
        "email": "arjun.new@example.com",
        "phone": "+919871100223",
        "password": "SecurePassword123!",
    }
    resp = client.post("/api/v1/auth/register", json=reg_payload)
    assert resp.status_code == 201
    user_data = resp.json()
    user_id = user_data["id"]

    # Verify vehicle was auto-created in database
    vehicles = db_session.query(Vehicle).filter(Vehicle.user_id == user_id).all()
    assert len(vehicles) == 1
    v = vehicles[0]
    assert v.make == "Tata"
    assert v.model == "Nexon EV Long Range"
    assert v.connector_type == ConnectorType.CCS2
    assert v.is_default is True
    assert v.current_soc == 45
    assert v.target_soc == 80


def test_new_driver_can_immediately_book_station_slot(
    client: TestClient,
    db_session: Session,
    active_charging_station: tuple[Station, Charger],
):
    """
    A newly registered driver can immediately reserve a station slot
    without hitting 403 or 404 missing vehicle errors.
    """
    station, charger = active_charging_station

    # 1. Register new driver
    reg_payload = {
        "name": "Priya Driver",
        "email": "priya.new@example.com",
        "phone": "+919872200334",
        "password": "SecurePassword123!",
    }
    reg_resp = client.post("/api/v1/auth/register", json=reg_payload)
    assert reg_resp.status_code == 201

    # 2. Login to get JWT access token
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": "priya.new@example.com", "password": "SecurePassword123!"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Check vehicles endpoint returns the driver's vehicle
    v_resp = client.get("/api/v1/vehicles", headers=headers)
    assert v_resp.status_code == 200
    v_data = v_resp.json()
    assert v_data["total"] >= 1
    vehicle_id = v_data["items"][0]["id"]

    # 4. Book a slot for tomorrow 14:00 UTC
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    slot_start = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)

    booking_payload = {
        "station_id": station.id,
        "charger_id": charger.id,
        "vehicle_id": vehicle_id,
        "start_time": slot_start.isoformat(),
        "target_soc": 80,
    }

    book_resp = client.post(
        "/api/v1/bookings/manual-slot",
        json=booking_payload,
        headers=headers,
    )
    assert book_resp.status_code == 201
    booking_data = book_resp.json()
    assert booking_data["booking_id"] > 0
    assert booking_data["status"] == BookingStatus.HELD.value
    assert booking_data["station_id"] == station.id
    assert booking_data["vehicle_id"] == vehicle_id


def test_new_driver_slot_booking_foreign_or_missing_vehicle_id_fallback(
    client: TestClient,
    db_session: Session,
    active_charging_station: tuple[Station, Charger],
):
    """
    If the UI or frontend submits a fallback or foreign vehicle_id, the system
    safely falls back to the driver's own vehicle rather than throwing 403 Forbidden.
    """
    station, charger = active_charging_station

    # 1. Register driver
    reg_payload = {
        "name": "Rohan Driver",
        "email": "rohan.new@example.com",
        "phone": "+919873300445",
        "password": "SecurePassword123!",
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    # 2. Login
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"identifier": "rohan.new@example.com", "password": "SecurePassword123!"},
    )
    token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Book sending vehicle_id = 99999 (non-existent/foreign)
    tomorrow = datetime.now(timezone.utc) + timedelta(days=1)
    slot_start = tomorrow.replace(hour=16, minute=0, second=0, microsecond=0)

    booking_payload = {
        "station_id": station.id,
        "charger_id": charger.id,
        "vehicle_id": 99999,  # Foreign/preset ID
        "start_time": slot_start.isoformat(),
        "target_soc": 80,
    }

    book_resp = client.post(
        "/api/v1/bookings/manual-slot",
        json=booking_payload,
        headers=headers,
    )
    assert book_resp.status_code == 201
    booking_data = book_resp.json()
    assert booking_data["booking_id"] > 0
    assert booking_data["status"] == BookingStatus.HELD.value
