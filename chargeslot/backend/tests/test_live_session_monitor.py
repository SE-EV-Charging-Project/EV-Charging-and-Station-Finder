from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
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
def active_session(db_session):
    driver = _create_user(
        db_session, "Session Driver", "session.driver@example.com", "+919800000101",
        UserRole.DRIVER,
    )
    other_driver = _create_user(
        db_session, "Other Driver", "other.driver@example.com", "+919800000102",
        UserRole.DRIVER,
    )
    operator = _create_user(
        db_session, "Session Operator", "session.operator@example.com", "+919800000103",
        UserRole.OPERATOR,
    )
    other_operator = _create_user(
        db_session, "Other Operator", "other.operator@example.com", "+919800000104",
        UserRole.OPERATOR,
    )

    station = Station(
        operator_id=operator.id,
        name="Session Monitor Station",
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
        name="Session Charger",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-SESSION-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.OCCUPIED,
    )
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
    db_session.add_all([connector, vehicle])
    db_session.flush()

    now = datetime.now(timezone.utc)
    booking = Booking(
        user_id=driver.id,
        vehicle_id=vehicle.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=connector.id,
        start_soc=40,
        target_soc=80,
        status=BookingStatus.ACTIVE,
        start_time=now - timedelta(minutes=5),
        end_time=now + timedelta(minutes=55),
    )
    db_session.add(booking)
    db_session.commit()
    db_session.refresh(booking)
    return {
        "driver": driver,
        "other_driver": other_driver,
        "operator": operator,
        "other_operator": other_operator,
        "station": station,
        "charger": charger,
        "connector": connector,
        "booking": booking,
    }


def _ingest_meter_value(
    client,
    session,
    *,
    observed_at: datetime,
    energy_meter_kwh: float,
    power_kw: float = 7.5,
    message_id: str | None = None,
):
    payload = {
        "gateway_id": session["charger"].gateway_id,
        "connector_index": 1,
        "power_kw": power_kw,
        "energy_meter_kwh": energy_meter_kwh,
        "observed_at": observed_at.isoformat(),
    }
    if message_id:
        payload["messageId"] = message_id
    return client.post(
        "/api/v1/gateway/ocpp/1.6j/meter-values",
        json=payload,
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )


def test_live_monitor_reports_measured_energy_soc_cost_and_elapsed_time(
    client, active_session
):
    now = datetime.now(timezone.utc)
    _ingest_meter_value(
        client,
        active_session,
        observed_at=now - timedelta(seconds=35),
        energy_meter_kwh=100.0,
        message_id="meter-start",
    )
    _ingest_meter_value(
        client,
        active_session,
        observed_at=now - timedelta(seconds=5),
        energy_meter_kwh=102.0,
        power_kw=8.5,
        message_id="meter-latest",
    )

    response = client.get(
        f"/api/v1/bookings/{active_session['booking'].id}/live-monitor",
        headers=_auth_header(active_session["driver"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["has_telemetry"] is True
    assert body["connector_id"] == active_session["connector"].id
    assert body["power_kw"] == 8.5
    assert body["energy_kwh"] == 2.0
    assert body["estimated_soc_pct"] == 43.0
    assert body["estimated_cost_inr"] == 10.0
    assert body["cost_available"] is True
    assert body["elapsed_seconds"] >= 30
    assert body["is_stale"] is False
    assert body["refresh_interval_seconds"] == 30


def test_monitor_reports_missing_and_stale_telemetry_without_fake_values(
    client, active_session
):
    monitor_url = f"/api/v1/bookings/{active_session['booking'].id}/live-monitor"
    headers = _auth_header(active_session["driver"])

    missing = client.get(monitor_url, headers=headers)
    assert missing.status_code == 200
    assert missing.json()["has_telemetry"] is False
    assert missing.json()["connector_id"] == active_session["connector"].id
    assert missing.json()["power_kw"] is None
    assert missing.json()["is_stale"] is True

    _ingest_meter_value(
        client,
        active_session,
        observed_at=datetime.now(timezone.utc) - timedelta(seconds=31),
        energy_meter_kwh=15.0,
    )
    stale = client.get(monitor_url, headers=headers)
    assert stale.status_code == 200
    assert stale.json()["has_telemetry"] is True
    assert stale.json()["is_stale"] is True


def test_meter_ingestion_rejects_power_outside_charger_rating(client, active_session):
    response = _ingest_meter_value(
        client,
        active_session,
        observed_at=datetime.now(timezone.utc),
        energy_meter_kwh=1.0,
        power_kw=60.0,
    )

    assert response.status_code == 422
    assert "rated power" in response.json()["detail"]


def test_meter_ingestion_rejects_decreasing_energy_and_accepts_replay(
    client, active_session
):
    observed = datetime.now(timezone.utc)
    first = _ingest_meter_value(
        client,
        active_session,
        observed_at=observed,
        energy_meter_kwh=12.0,
        message_id="meter-idempotent",
    )
    assert first.status_code == 200

    replay = _ingest_meter_value(
        client,
        active_session,
        observed_at=observed + timedelta(seconds=1),
        energy_meter_kwh=13.0,
        message_id="meter-idempotent",
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    decreasing = _ingest_meter_value(
        client,
        active_session,
        observed_at=observed + timedelta(seconds=2),
        energy_meter_kwh=11.0,
    )
    assert decreasing.status_code == 422
    assert "must not decrease" in decreasing.json()["detail"]


def test_meter_ingestion_rejects_missing_active_booking(client, active_session, db_session):
    active_session["booking"].status = BookingStatus.COMPLETED
    db_session.commit()

    response = _ingest_meter_value(
        client,
        active_session,
        observed_at=datetime.now(timezone.utc),
        energy_meter_kwh=5.0,
    )

    assert response.status_code == 409


def test_live_monitor_denies_foreign_driver_and_unscoped_operator(
    client, active_session
):
    url = f"/api/v1/bookings/{active_session['booking'].id}/live-monitor"

    owner_operator = client.get(
        url,
        headers=_auth_header(active_session["operator"]),
    )
    assert owner_operator.status_code == 200

    foreign_driver = client.get(
        url,
        headers=_auth_header(active_session["other_driver"]),
    )
    assert foreign_driver.status_code == 404

    foreign_operator = client.get(
        url,
        headers=_auth_header(active_session["other_operator"]),
    )
    assert foreign_operator.status_code == 403


def test_meter_ingestion_rejects_non_finite_global_range(client, active_session):
    response = _ingest_meter_value(
        client,
        active_session,
        observed_at=datetime.now(timezone.utc),
        energy_meter_kwh=1.0,
        power_kw=1001.0,
    )

    assert response.status_code == 422
