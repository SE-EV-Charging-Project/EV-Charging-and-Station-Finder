from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.charging_session_reading import ChargingSessionReading
from app.models.in_app_notification import InAppNotification
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.models.vehicle import ConnectorType, Vehicle
from app.utils.security import create_access_token, hash_password


def _create_user(db_session, name: str, email: str, phone: str, role: UserRole) -> User:
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
        {"sub": str(user.id), "email": user.email, "role": user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def ready_booking(db_session):
    driver = _create_user(
        db_session, "Start Driver", "start.driver@example.com", "+919800000201",
        UserRole.DRIVER,
    )
    other_driver = _create_user(
        db_session, "Other Driver", "start.other@example.com", "+919800000202",
        UserRole.DRIVER,
    )
    operator = _create_user(
        db_session, "Start Operator", "start.operator@example.com", "+919800000203",
        UserRole.OPERATOR,
    )
    station = Station(
        operator_id=operator.id,
        name="Remote Start Station",
        address="42 Residency Road, Bengaluru",
        latitude=12.9718,
        longitude=77.6012,
        amenities=[],
        operating_hours="24x7",
        contact_phone="+919876500099",
        price_per_kwh=5.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()
    charger = Charger(
        station_id=station.id,
        name="Remote Start Charger",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-START-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()
    connectors = [
        Connector(
            charger_id=charger.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
        for _ in range(2)
    ]
    vehicle = Vehicle(
        user_id=driver.id,
        make="Tata",
        model="Nexon EV",
        battery_kwh=60.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        current_soc=40,
        target_soc=80,
    )
    db_session.add_all([*connectors, vehicle])
    db_session.flush()
    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=driver.id,
        vehicle_id=vehicle.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=connectors[0].id,
        status=BookingStatus.CONFIRMED,
        checked_in_at=now,
        start_time=now,
        end_time=now + timedelta(hours=1),
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    return {
        "driver": driver,
        "other_driver": other_driver,
        "charger": charger,
        "station": station,
        "connectors": connectors,
        "booking": booking,
    }


def _gateway_headers() -> dict[str, str]:
    return {"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET}


def test_checkin_accepts_valid_qr_and_enforces_booking_owner(client, ready_booking):
    from app.booking.qr import make_checkin_qr_payload

    booking = ready_booking["booking"]
    checkin_url = f"/api/v1/bookings/{booking.id}/check-in"
    response = client.post(
        checkin_url,
        json={"qr_code_payload": make_checkin_qr_payload(booking.id, booking.user_id)},
        headers=_auth_header(ready_booking["driver"]),
    )
    assert response.status_code == 200
    assert response.json()["booking_id"] == booking.id
    assert response.json()["checked_in_at"]

    replay = client.post(
        checkin_url,
        json={"qr_code_payload": "malformed-on-purpose"},
        headers=_auth_header(ready_booking["driver"]),
    )
    assert replay.status_code == 200
    assert replay.json()["message"] == "Booking check-in was already recorded."

    foreign = client.post(
        checkin_url,
        json={"qr_code_payload": make_checkin_qr_payload(booking.id, booking.user_id)},
        headers=_auth_header(ready_booking["other_driver"]),
    )
    assert foreign.status_code == 404


def test_checkin_accepts_location_within_300m_and_rejects_far_location(
    client, db_session, ready_booking
):
    booking = ready_booking["booking"]
    booking.checked_in_at = None
    db_session.commit()
    url = f"/api/v1/bookings/{booking.id}/check-in"
    headers = _auth_header(ready_booking["driver"])
    far = client.post(
        url,
        json={"latitude": 13.0, "longitude": 77.6012},
        headers=headers,
    )
    assert far.status_code == 403
    invalid_qr = client.post(
        url,
        json={"qr_code_payload": "chargeslot://check-in/invalid?signature=bad"},
        headers=headers,
    )
    assert invalid_qr.status_code == 403

    near = client.post(
        url,
        json={"latitude": 12.9730, "longitude": 77.6012},
        headers=headers,
    )
    assert near.status_code == 200


def test_remote_start_requires_checkin_and_booking_owner(client, db_session, ready_booking):
    booking = ready_booking["booking"]
    booking.checked_in_at = None
    db_session.commit()
    url = f"/api/v1/bookings/{booking.id}/start-session"

    unchecked = client.post(
        url,
        json={},
        headers=_auth_header(ready_booking["driver"]),
    )
    assert unchecked.status_code == 409

    foreign = client.post(
        url,
        json={},
        headers=_auth_header(ready_booking["other_driver"]),
    )
    assert foreign.status_code == 404


def test_remote_start_rejection_offers_alternative_and_start_is_idempotent(
    client, db_session, ready_booking
):
    booking = ready_booking["booking"]
    driver_headers = _auth_header(ready_booking["driver"])
    start_url = f"/api/v1/bookings/{booking.id}/start-session"
    queued = client.post(start_url, json={}, headers=driver_headers)
    assert queued.status_code == 202
    command = queued.json()
    assert command["connector_id"] == ready_booking["connectors"][0].id
    duplicate_request = client.post(start_url, json={}, headers=driver_headers)
    assert duplicate_request.status_code == 202
    assert duplicate_request.json()["command_id"] == command["command_id"]

    polled = client.get(
        "/api/v1/gateway/ocpp/1.6j/start-commands",
        params={"gateway_id": ready_booking["charger"].gateway_id},
        headers=_gateway_headers(),
    )
    assert polled.status_code == 200
    assert [item["command_id"] for item in polled.json()["commands"]] == [
        command["command_id"]
    ]

    rejected = client.post(
        f"/api/v1/gateway/ocpp/1.6j/start-commands/{command['command_id']}/result",
        json={"gateway_id": ready_booking["charger"].gateway_id, "result": "Rejected"},
        headers=_gateway_headers(),
    )
    assert rejected.status_code == 200
    assert rejected.json()["retry_available"] is True
    assert rejected.json()["alternative_connector_ids"] == [
        ready_booking["connectors"][1].id
    ]

    retry = client.post(
        start_url,
        json={"connector_id": ready_booking["connectors"][1].id},
        headers=driver_headers,
    )
    assert retry.status_code == 202
    retry_command = retry.json()
    assert retry_command["connector_id"] == ready_booking["connectors"][1].id

    accepted = client.post(
        f"/api/v1/gateway/ocpp/1.6j/start-commands/{retry_command['command_id']}/result",
        json={"gateway_id": ready_booking["charger"].gateway_id, "result": "Accepted"},
        headers=_gateway_headers(),
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "Accepted"

    transaction_payload = {
        "gateway_id": ready_booking["charger"].gateway_id,
        "command_id": retry_command["command_id"],
        "transaction_id": 12345,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": "start-event-12345",
    }
    started = client.post(
        "/api/v1/gateway/ocpp/1.6j/start-transaction",
        json=transaction_payload,
        headers=_gateway_headers(),
    )
    assert started.status_code == 200
    assert started.json()["status"] == "Active"
    assert started.json()["applied"] is True
    assert (
        db_session.query(InAppNotification)
        .filter_by(dedupe_key=f"session-started:{booking.id}")
        .count()
        == 1
    )

    replay = client.post(
        "/api/v1/gateway/ocpp/1.6j/start-transaction",
        json=transaction_payload,
        headers=_gateway_headers(),
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    db_session.add(
        ChargingSessionReading(
            booking_id=booking.id,
            charger_id=ready_booking["charger"].id,
            connector_id=ready_booking["connectors"][1].id,
            transaction_id=12345,
            power_kw=50.0,
            energy_meter_kwh=20.0,
            observed_at=datetime.now(timezone.utc),
        )
    )
    db_session.commit()
    stopped = client.post(
        "/api/v1/gateway/ocpp/1.6j/stop-transaction",
        json={
            "gateway_id": ready_booking["charger"].gateway_id,
            "transaction_id": 12345,
            "meter_stop_wh": 20000,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "stop-event-12345",
        },
        headers=_gateway_headers(),
    )
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "Completed"
    assert (
        db_session.query(InAppNotification)
        .filter_by(dedupe_key=f"session-completed:{booking.id}")
        .count()
        == 1
    )
