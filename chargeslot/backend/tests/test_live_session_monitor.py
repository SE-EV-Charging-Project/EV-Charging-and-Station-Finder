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
    transaction_id: int | None = None,
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
    if transaction_id is not None:
        payload["transactionId"] = transaction_id
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


def test_driver_stop_is_queued_until_gateway_confirms_stop_transaction(
    client, active_session, db_session
):
    observed_at = datetime.now(timezone.utc)
    meter_response = _ingest_meter_value(
        client,
        active_session,
        observed_at=observed_at,
        energy_meter_kwh=50.0,
        transaction_id=731,
    )
    assert meter_response.status_code == 200

    stop_url = f"/api/v1/bookings/{active_session['booking'].id}/stop-session"
    stop_response = client.post(
        stop_url,
        headers=_auth_header(active_session["driver"]),
    )
    assert stop_response.status_code == 202
    command = stop_response.json()
    assert command["status"] == "Pending"
    assert command["trigger"] == "driver"

    repeated_stop = client.post(
        stop_url,
        headers=_auth_header(active_session["driver"]),
    )
    assert repeated_stop.status_code == 202
    assert repeated_stop.json()["command_id"] == command["command_id"]
    assert repeated_stop.json()["already_requested"] is True

    poll_response = client.get(
        "/api/v1/gateway/ocpp/1.6j/commands",
        params={"gateway_id": active_session["charger"].gateway_id},
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert poll_response.status_code == 200
    queued = poll_response.json()["commands"]
    assert len(queued) == 1
    assert queued[0]["action"] == "RemoteStopTransaction"
    assert queued[0]["transaction_id"] == 731

    result_response = client.post(
        f"/api/v1/gateway/ocpp/1.6j/commands/{command['command_id']}/result",
        json={"gateway_id": active_session["charger"].gateway_id, "result": "Accepted"},
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert result_response.status_code == 200
    assert result_response.json()["status"] == "Accepted"
    db_session.refresh(active_session["booking"])
    assert active_session["booking"].status == BookingStatus.ACTIVE

    stop_transaction_payload = {
        "gateway_id": active_session["charger"].gateway_id,
        "transaction_id": 731,
        "meter_stop_wh": 51_250,
        "observed_at": (observed_at + timedelta(seconds=5)).isoformat(),
        "idempotency_key": "stop-event-731",
    }
    confirmation = client.post(
        "/api/v1/gateway/ocpp/1.6j/stop-transaction",
        json=stop_transaction_payload,
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert confirmation.status_code == 200
    assert confirmation.json()["status"] == "Completed"
    assert confirmation.json()["applied"] is True
    db_session.refresh(active_session["booking"])
    assert active_session["booking"].status == BookingStatus.COMPLETED
    assert active_session["booking"].meter_stop_wh == 51_250

    replay = client.post(
        "/api/v1/gateway/ocpp/1.6j/stop-transaction",
        json=stop_transaction_payload,
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True


def test_stop_request_enforces_booking_ownership_and_active_transaction(
    client, active_session
):
    stop_url = f"/api/v1/bookings/{active_session['booking'].id}/stop-session"
    foreign_driver = client.post(
        stop_url,
        headers=_auth_header(active_session["other_driver"]),
    )
    assert foreign_driver.status_code == 404

    no_transaction = client.post(
        stop_url,
        headers=_auth_header(active_session["driver"]),
    )
    assert no_transaction.status_code == 409
    assert "transaction ID" in no_transaction.json()["detail"]


def test_target_energy_queues_one_stop_command(client, active_session, db_session):
    active_session["booking"].est_energy_kwh = 1.0
    db_session.commit()
    start = datetime.now(timezone.utc)

    first = _ingest_meter_value(
        client,
        active_session,
        observed_at=start,
        energy_meter_kwh=100.0,
        transaction_id=812,
    )
    assert first.status_code == 200
    reached = _ingest_meter_value(
        client,
        active_session,
        observed_at=start + timedelta(seconds=30),
        energy_meter_kwh=101.2,
        message_id="target-meter-value",
        transaction_id=812,
    )
    assert reached.status_code == 200
    assert reached.json()["target_energy_reached"] is True
    command_id = reached.json()["auto_stop_command_id"]
    assert command_id is not None
    assert reached.json()["auto_stop_status"] == "Pending"

    replay = _ingest_meter_value(
        client,
        active_session,
        observed_at=start + timedelta(seconds=35),
        energy_meter_kwh=101.2,
        message_id="target-meter-value",
        transaction_id=812,
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["auto_stop_command_id"] == command_id
    assert replay.json()["auto_stop_status"] == "Pending"

    subsequent = _ingest_meter_value(
        client,
        active_session,
        observed_at=start + timedelta(seconds=60),
        energy_meter_kwh=101.4,
        transaction_id=812,
    )
    assert subsequent.status_code == 200
    assert subsequent.json()["auto_stop_command_id"] == command_id

    poll_response = client.get(
        "/api/v1/gateway/ocpp/1.6j/commands",
        params={"gateway_id": active_session["charger"].gateway_id},
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert len(poll_response.json()["commands"]) == 1
    assert poll_response.json()["commands"][0]["trigger"] == "target_energy"


def test_target_energy_reached_without_transaction_is_reported_not_faked(
    client, active_session, db_session
):
    active_session["booking"].est_energy_kwh = 0.5
    db_session.commit()
    start = datetime.now(timezone.utc)
    _ingest_meter_value(
        client,
        active_session,
        observed_at=start,
        energy_meter_kwh=10.0,
    )
    reached = _ingest_meter_value(
        client,
        active_session,
        observed_at=start + timedelta(seconds=30),
        energy_meter_kwh=10.6,
    )

    assert reached.status_code == 200
    assert reached.json()["target_energy_reached"] is True
    assert reached.json()["auto_stop_command_id"] is None
    assert "no OCPP transaction ID" in reached.json()["auto_stop_warning"]


def test_rejected_stop_command_can_be_retried(client, active_session):
    observed_at = datetime.now(timezone.utc)
    _ingest_meter_value(
        client,
        active_session,
        observed_at=observed_at,
        energy_meter_kwh=20.0,
        transaction_id=913,
    )
    stop_url = f"/api/v1/bookings/{active_session['booking'].id}/stop-session"
    initial = client.post(
        stop_url,
        headers=_auth_header(active_session["driver"]),
    )
    assert initial.status_code == 202
    command_id = initial.json()["command_id"]

    rejected = client.post(
        f"/api/v1/gateway/ocpp/1.6j/commands/{command_id}/result",
        json={
            "gateway_id": active_session["charger"].gateway_id,
            "result": "Rejected",
            "error_code": "NotImplemented",
        },
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "Rejected"

    retried = client.post(
        stop_url,
        headers=_auth_header(active_session["driver"]),
    )
    assert retried.status_code == 202
    assert retried.json()["status"] == "Pending"
    assert retried.json()["command_id"] != command_id
