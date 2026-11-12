from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.gateway.ingest import (
    ingest_status,
    normalize_connector_status,
    validate_observed_at,
)
from app.models.audit import AuditLog
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.connector_status_event import ConnectorStatusEvent
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
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


def _gateway_header(secret: str | None = None) -> dict[str, str]:
    return {"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET if secret is None else secret}


def _seed_station_connectors(
    db_session,
    operator: User,
    *,
    gateway_id: str = "GW-OCPP-001",
) -> tuple[Station, Charger, Connector, Connector]:
    station = Station(
        operator_id=operator.id,
        name="Gateway Telemetry Hub",
        address="42 Residency Road, Bengaluru",
        latitude=12.9718,
        longitude=77.6012,
        amenities=["WiFi"],
        operating_hours="24x7",
        contact_phone="+919876500099",
        contact_email="telemetry@chargeslot.example",
        price_per_kwh=18.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="DC Unit A",
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id=gateway_id,
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    c1 = Connector(
        charger_id=charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
    )
    c2 = Connector(
        charger_id=charger.id,
        connector_type="CHAdeMO",
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add_all([c1, c2])
    db_session.commit()
    db_session.refresh(c1)
    db_session.refresh(c2)
    return station, charger, c1, c2


# ==============================================================================
# Unit Tests: TC-F2-17 & TC-F2-17-V4
# ==============================================================================


@pytest.mark.parametrize(
    "raw_value,expected",
    [
        ("Available", ConnectorStatus.AVAILABLE),
        ("available", ConnectorStatus.AVAILABLE),
        ("  Occupied ", ConnectorStatus.OCCUPIED),
        ("Reserved", ConnectorStatus.RESERVED),
        ("Faulted", ConnectorStatus.FAULTED),
        ("Offline", ConnectorStatus.OFFLINE),
        # OCPP 1.6J StatusNotification aliases
        ("Preparing", ConnectorStatus.OCCUPIED),
        ("Charging", ConnectorStatus.OCCUPIED),
        ("SuspendedEVSE", ConnectorStatus.OCCUPIED),
        ("SuspendedEV", ConnectorStatus.OCCUPIED),
        ("Finishing", ConnectorStatus.OCCUPIED),
        ("Unavailable", ConnectorStatus.OFFLINE),
    ],
)
def test_normalize_connector_status_valid_and_ocpp_aliases(raw_value, expected):
    assert normalize_connector_status(raw_value) == expected


@pytest.mark.parametrize("bad_value", ["", "   ", "Broken", "12345", "UnknownState"])
def test_normalize_connector_status_rejects_malformed_input(bad_value):
    with pytest.raises(HTTPException) as exc:
        normalize_connector_status(bad_value)
    assert exc.value.status_code == 422


def test_validate_observed_at_normalizes_utc_and_rejects_far_future():
    defaulted = validate_observed_at(None)
    assert defaulted.tzinfo == timezone.utc

    naive = datetime(2026, 5, 1, 9, 30, 0)
    normalized_naive = validate_observed_at(naive)
    assert normalized_naive == datetime(2026, 5, 1, 9, 30, 0, tzinfo=timezone.utc)

    ist = timezone(timedelta(hours=5, minutes=30))
    aware_ist = datetime(2026, 5, 1, 15, 0, 0, tzinfo=ist)
    assert validate_observed_at(aware_ist) == datetime(2026, 5, 1, 9, 30, 0, tzinfo=timezone.utc)

    far_future = datetime.now(timezone.utc) + timedelta(minutes=15)
    with pytest.raises(HTTPException) as exc:
        validate_observed_at(far_future)
    assert exc.value.status_code == 422


def test_ingest_status_unit_updates_connector_records_event_and_audit(db_session):
    operator = _make_user(
        db_session,
        name="Op Telemetry",
        email="op.tel@example.com",
        phone="+919800000001",
        role=UserRole.OPERATOR,
    )
    station, charger, c1, _ = _seed_station_connectors(db_session, operator)

    observed = datetime(2026, 5, 2, 8, 15, 0, tzinfo=timezone.utc)
    result = ingest_status(
        db_session,
        c1.id,
        "Charging",
        observed,
        error_code="NoError",
        idempotency_key="msg-unit-001",
    )

    assert result.applied is True
    assert result.idempotent_replay is False
    assert result.connector_id == c1.id
    assert result.charger_id == charger.id
    assert result.station_id == station.id
    assert result.previous_status == ConnectorStatus.AVAILABLE.value
    assert result.status == ConnectorStatus.OCCUPIED.value
    assert result.raw_status == "Charging"
    assert result.observed_at == observed

    db_session.refresh(c1)
    assert c1.status == ConnectorStatus.OCCUPIED
    assert c1.last_update.replace(tzinfo=timezone.utc) == observed

    events = (
        db_session.query(ConnectorStatusEvent)
        .filter(ConnectorStatusEvent.connector_id == c1.id)
        .all()
    )
    assert len(events) == 1
    assert events[0].error_code == "NoError"
    assert events[0].idempotency_key == "msg-unit-001"

    audit = (
        db_session.query(AuditLog)
        .filter(AuditLog.action == "GATEWAY_STATUS_INGESTED")
        .first()
    )
    assert audit is not None
    assert audit.resource == "connector"


def test_ingest_status_stale_out_of_order_and_idempotency_resilience(db_session):
    """TC-F2-17-V4: Ignore out-of-order stale telemetry and duplicate message retries."""
    operator = _make_user(
        db_session,
        name="Op Resilient",
        email="op.res@example.com",
        phone="+919800000002",
        role=UserRole.OPERATOR,
    )
    _, _, c1, _ = _seed_station_connectors(db_session, operator, gateway_id="GW-RES-01")

    t_newer = datetime(2026, 5, 2, 10, 0, 0, tzinfo=timezone.utc)
    t_older = datetime(2026, 5, 2, 9, 55, 0, tzinfo=timezone.utc)

    first = ingest_status(
        db_session,
        c1.id,
        "Faulted",
        t_newer,
        idempotency_key="msg-dup-100",
    )
    assert first.applied is True

    # Out-of-order older packet must not revert status back to Available
    stale = ingest_status(
        db_session,
        c1.id,
        "Available",
        t_older,
    )
    assert stale.applied is False
    assert stale.idempotent_replay is False
    assert stale.status == ConnectorStatus.FAULTED.value

    db_session.refresh(c1)
    assert c1.status == ConnectorStatus.FAULTED
    assert c1.last_update.replace(tzinfo=timezone.utc) == t_newer

    # Duplicate idempotency_key must replay cleanly without extra event row
    replay = ingest_status(
        db_session,
        c1.id,
        "Available",
        t_newer + timedelta(seconds=10),
        idempotency_key="msg-dup-100",
    )
    assert replay.applied is False
    assert replay.idempotent_replay is True
    assert replay.event_id == first.event_id
    assert (
        db_session.query(ConnectorStatusEvent)
        .filter(ConnectorStatusEvent.connector_id == c1.id)
        .count()
        == 1
    )


# ==============================================================================
# Integration / API Tests: STC-F2-17 & TC-F2-17-V4
# ==============================================================================


@pytest.mark.parametrize(
    "endpoint",
    ["/gateway/ocpp/1.6j", "/api/v1/gateway/ocpp/1.6j"],
)
def test_api_gateway_ingests_all_five_statuses_via_both_routes(
    client, db_session, endpoint
):
    operator = _make_user(
        db_session,
        name="Op Five",
        email="op.five@example.com",
        phone="+919800000003",
        role=UserRole.OPERATOR,
    )
    _, _, c1, _ = _seed_station_connectors(db_session, operator, gateway_id="GW-FIVE-01")

    base_time = datetime(2026, 5, 3, 8, 0, 0, tzinfo=timezone.utc)
    states = ["Available", "Occupied", "Reserved", "Faulted", "Offline"]

    for idx, state in enumerate(states):
        ts = (base_time + timedelta(minutes=idx + 1)).isoformat()
        resp = client.post(
            endpoint,
            json={
                "connector_id": c1.id,
                "status": state,
                "observed_at": ts,
            },
            headers=_gateway_header(),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["applied"] is True
        assert body["status"] == state
        assert datetime.fromisoformat(body["observed_at"].replace("Z", "+00:00")) == (
            base_time + timedelta(minutes=idx + 1)
        )

    db_session.refresh(c1)
    assert c1.status == ConnectorStatus.OFFLINE


def test_api_ocpp_camelcase_gateway_lookup_and_live_station_detail_reflection(
    client, db_session
):
    """STC-F2-17: Ingest OCPP 1.6J payload and verify live reflection in station-detail."""
    driver = _make_user(
        db_session,
        name="Driver Telemetry",
        email="drv.tel@example.com",
        phone="+919800000004",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op Live",
        email="op.live@example.com",
        phone="+919800000005",
        role=UserRole.OPERATOR,
    )
    station, _, c1, c2 = _seed_station_connectors(
        db_session, operator, gateway_id="CP-BLR-900"
    )

    before_detail = client.get(
        f"/api/v1/stations/station-detail?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert before_detail.status_code == 200
    assert before_detail.json()["available_connectors"] == 2

    # OCPP 1.6J StatusNotification payload addressing port 2 (connectorId=2 -> c2)
    ocpp_time = "2026-05-04T11:22:33Z"
    ingest_res = client.post(
        "/gateway/ocpp/1.6j",
        json={
            "chargePointId": "CP-BLR-900",
            "connectorId": 2,
            "state": "Charging",
            "timestamp": ocpp_time,
            "errorCode": "NoError",
            "messageId": "ocpp-msg-77",
        },
        headers=_gateway_header(),
    )
    assert ingest_res.status_code == 200
    ingest_body = ingest_res.json()
    assert ingest_body["connector_id"] == c2.id
    assert ingest_body["status"] == "Occupied"
    assert ingest_body["applied"] is True

    after_detail = client.get(
        f"/api/v1/stations/station-detail?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert after_detail.status_code == 200
    detail_payload = after_detail.json()
    assert detail_payload["available_connectors"] == 1
    by_id = {item["id"]: item for item in detail_payload["connectors"]}
    assert by_id[c1.id]["status"] == "Available"
    assert by_id[c2.id]["status"] == "Occupied"
    assert by_id[c2.id]["last_update"].startswith("2026-05-04T11:22:33")


def test_api_gateway_auth_scoping_and_validation_errors(client, db_session):
    driver = _make_user(
        db_session,
        name="Drv Unauth",
        email="drv.un@example.com",
        phone="+919800000006",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="Op Owner",
        email="op.own@example.com",
        phone="+919800000007",
        role=UserRole.OPERATOR,
    )
    op_other = _make_user(
        db_session,
        name="Op Other",
        email="op.oth@example.com",
        phone="+919800000008",
        role=UserRole.OPERATOR,
    )
    admin = _make_user(
        db_session,
        name="Admin User",
        email="admin.gw@example.com",
        phone="+919800000009",
        role=UserRole.ADMIN,
    )
    _, _, c1, _ = _seed_station_connectors(db_session, op_owner, gateway_id="GW-AUTH-01")

    payload = {
        "connector_id": c1.id,
        "status": "Reserved",
        "observed_at": "2026-05-05T09:00:00Z",
    }

    # Unauthenticated -> 401
    assert client.post("/gateway/ocpp/1.6j", json=payload).status_code == 401
    # Bad gateway secret -> 401
    assert (
        client.post(
            "/gateway/ocpp/1.6j", json=payload, headers=_gateway_header("wrong-secret")
        ).status_code
        == 401
    )
    # Driver JWT -> 403
    assert (
        client.post("/gateway/ocpp/1.6j", json=payload, headers=_auth_header(driver)).status_code
        == 403
    )
    # Foreign Operator JWT -> 403
    assert (
        client.post(
            "/gateway/ocpp/1.6j", json=payload, headers=_auth_header(op_other)
        ).status_code
        == 403
    )
    # Owning Operator JWT -> 200
    assert (
        client.post(
            "/gateway/ocpp/1.6j", json=payload, headers=_auth_header(op_owner)
        ).status_code
        == 200
    )
    # Admin JWT -> 200
    admin_res = client.post(
        "/gateway/ocpp/1.6j",
        json={
            "connector_id": c1.id,
            "status": "Faulted",
            "observed_at": "2026-05-05T09:05:00Z",
        },
        headers=_auth_header(admin),
    )
    assert admin_res.status_code == 200

    # NFR-SAFE-06 malformed status & far-future timestamp -> 422
    bad_status_res = client.post(
        "/gateway/ocpp/1.6j",
        json={"connector_id": c1.id, "status": "Exploded"},
        headers=_gateway_header(),
    )
    assert bad_status_res.status_code == 422

    future_ts = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    bad_ts_res = client.post(
        "/gateway/ocpp/1.6j",
        json={"connector_id": c1.id, "status": "Available", "observed_at": future_ts},
        headers=_gateway_header(),
    )
    assert bad_ts_res.status_code == 422

    # Unknown connector / gateway -> 404
    assert (
        client.post(
            "/gateway/ocpp/1.6j",
            json={"connector_id": 999999, "status": "Available"},
            headers=_gateway_header(),
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/gateway/ocpp/1.6j",
            json={"gateway_id": "NO-SUCH-GW", "connector_index": 1, "status": "Available"},
            headers=_gateway_header(),
        ).status_code
        == 404
    )

    # Status history endpoint RBAC & ordering
    assert (
        client.get(
            f"/api/v1/gateway/connectors/{c1.id}/status-history",
            headers=_auth_header(driver),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/gateway/connectors/{c1.id}/status-history",
            headers=_auth_header(op_other),
        ).status_code
        == 403
    )

    history_res = client.get(
        f"/api/v1/gateway/connectors/{c1.id}/status-history",
        headers=_auth_header(op_owner),
    )
    assert history_res.status_code == 200
    history_body = history_res.json()
    assert history_body["connector_id"] == c1.id
    assert history_body["current_status"] == "Faulted"
    assert history_body["total_events"] == 2
    assert [e["new_status"] for e in history_body["events"]] == ["Faulted", "Reserved"]
