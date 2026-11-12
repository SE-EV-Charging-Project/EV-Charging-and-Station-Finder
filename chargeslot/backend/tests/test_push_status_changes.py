import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from starlette.websockets import WebSocketDisconnect

from app.core.config import settings
from app.dashboard.realtime import (
    StationStatusConnectionManager,
    build_status_change_event,
    status_connection_manager,
)
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.utils.security import create_access_token, hash_password


@pytest.fixture(autouse=True)
def reset_ws_manager():
    status_connection_manager.clear()
    yield
    status_connection_manager.clear()


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


def _make_token(user: User) -> str:
    return create_access_token(
        {
            "sub": str(user.id),
            "email": user.email,
            "role": user.role.value,
        }
    )


def _gateway_header() -> dict[str, str]:
    return {"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET}


def _seed_station(
    db_session,
    operator: User,
    *,
    name: str = "Realtime Hub",
    status_val: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
    gateway_prefix: str = "GW-WS",
) -> tuple[Station, Charger, Charger, Connector, Connector]:
    station = Station(
        operator_id=operator.id,
        name=name,
        address="88 Church Street, Bengaluru",
        latitude=12.9752,
        longitude=77.6046,
        amenities=["WiFi"],
        operating_hours="24x7",
        contact_phone="+919876522222",
        contact_email="ws@chargeslot.example",
        price_per_kwh=19.0,
        status=status_val,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.flush()

    active_charger = Charger(
        station_id=station.id,
        name="Fast Unit 1",
        power_kw=150.0,
        current_type=CurrentType.DC,
        gateway_id=f"{gateway_prefix}-ACT",
        is_active=True,
        is_out_of_service=False,
    )
    inactive_charger = Charger(
        station_id=station.id,
        name="Offline Archive Unit",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id=f"{gateway_prefix}-INA",
        is_active=False,
        is_out_of_service=False,
    )
    db_session.add_all([active_charger, inactive_charger])
    db_session.flush()

    c_active = Connector(
        charger_id=active_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
    )
    c_inactive = Connector(
        charger_id=inactive_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.OFFLINE,
    )
    db_session.add_all([c_active, c_inactive])
    db_session.commit()
    db_session.refresh(c_active)
    db_session.refresh(c_inactive)
    return station, active_charger, inactive_charger, c_active, c_inactive


# ==============================================================================
# Unit Tests: TC-F2-19
# ==============================================================================


class _FakeWebSocket:
    def __init__(self, *, fail_send: bool = False):
        self.accepted = False
        self.sent: list[dict] = []
        self.fail_send = fail_send

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, data: dict) -> None:
        if self.fail_send:
            raise RuntimeError("Socket broken")
        self.sent.append(data)


def test_connection_manager_isolation_inactive_filtering_and_dead_socket_cleanup():
    async def _run():
        mgr = StationStatusConnectionManager()
        ws_driver_s1 = _FakeWebSocket()
        ws_operator_s1 = _FakeWebSocket()
        ws_dead_s1 = _FakeWebSocket(fail_send=True)
        ws_driver_s2 = _FakeWebSocket()

        await mgr.connect(
            ws_driver_s1,
            station_id=10,
            user_id=1,
            role="DRIVER",
            include_inactive_chargers=False,
        )
        await mgr.connect(
            ws_operator_s1,
            station_id=10,
            user_id=2,
            role="OPERATOR",
            include_inactive_chargers=True,
        )
        await mgr.connect(
            ws_dead_s1,
            station_id=10,
            user_id=3,
            role="DRIVER",
            include_inactive_chargers=False,
        )
        await mgr.connect(
            ws_driver_s2,
            station_id=20,
            user_id=4,
            role="DRIVER",
            include_inactive_chargers=False,
        )

        assert mgr.subscriber_count(10) == 3
        assert mgr.subscriber_count(20) == 1

        delivered = await mgr.broadcast_event(10, {"type": "status_change", "id": 1})
        assert delivered == 2
        assert mgr.subscriber_count(10) == 2
        assert len(ws_driver_s1.sent) == 1
        assert len(ws_operator_s1.sent) == 1
        assert len(ws_driver_s2.sent) == 0

        # Inactive charger change goes only to subscribers permitted inactive visibility
        delivered_inactive = await mgr.broadcast_event(
            10, {"type": "status_change", "id": 2}, charger_is_active=False
        )
        assert delivered_inactive == 1
        assert len(ws_driver_s1.sent) == 1
        assert len(ws_operator_s1.sent) == 2

    asyncio.run(_run())


def test_build_status_change_event_respects_oos_and_utc_timestamps():
    conn = SimpleNamespace(id=5, connector_type="CCS2", status=ConnectorStatus.OCCUPIED)
    charger = SimpleNamespace(
        id=2,
        gateway_id="GW-EVT-1",
        is_active=True,
        is_out_of_service=True,
        connectors=[conn],
    )
    station = SimpleNamespace(
        id=1,
        name="Test Station",
        latitude=12.97,
        longitude=77.59,
        is_active=True,
        chargers=[charger],
    )
    observed = datetime(2026, 5, 11, 14, 0, 0)

    payload = build_status_change_event(
        event_id=99,
        station=station,
        charger=charger,
        connector=conn,
        previous_status=ConnectorStatus.AVAILABLE,
        new_status=ConnectorStatus.OCCUPIED,
        raw_status="Charging",
        observed_at=observed,
        error_code="NoError",
    )

    assert payload["type"] == "status_change"
    assert payload["event"] == "connector_status_changed"
    assert payload["event_id"] == 99
    assert payload["previous_status"] == "Available"
    assert payload["status"] == "Offline"
    assert payload["is_out_of_service"] is True
    assert payload["observed_at"] == "2026-05-11T14:00:00+00:00"
    assert payload["pushed_at"] is not None


# ==============================================================================
# System / WebSocket Integration Tests: STC-F2-19
# ==============================================================================


def test_ws_rejects_unauthenticated_foreign_operator_and_unapproved_stations(
    client, db_session
):
    driver = _make_user(
        db_session,
        name="WS Driver",
        email="ws.drv@example.com",
        phone="+919600000001",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="WS Owner",
        email="ws.own@example.com",
        phone="+919600000002",
        role=UserRole.OPERATOR,
    )
    op_foreign = _make_user(
        db_session,
        name="WS Foreign",
        email="ws.for@example.com",
        phone="+919600000003",
        role=UserRole.OPERATOR,
    )
    approved_station, _, _, _, _ = _seed_station(
        db_session, op_owner, gateway_prefix="GW-WS-AUTH1"
    )
    pending_station, _, _, _, _ = _seed_station(
        db_session,
        op_owner,
        name="Pending WS Hub",
        status_val=StationStatus.PENDING,
        gateway_prefix="GW-WS-AUTH2",
    )

    # Missing token -> rejected
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect(
            f"/ws/stations/status?station_id={approved_station.id}"
        ):
            pass

    # Invalid token -> rejected
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect(
            f"/ws/stations/status?station_id={approved_station.id}&token=bad.jwt.token"
        ):
            pass

    # Missing or invalid station_id -> rejected
    drv_token = _make_token(driver)
    for bad_qs in [
        f"/ws/stations/status?token={drv_token}",
        f"/ws/stations/status?station_id=0&token={drv_token}",
    ]:
        with pytest.raises((WebSocketDisconnect, Exception)):
            with client.websocket_connect(bad_qs):
                pass

    # Driver blocked from pending station (BR-01)
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect(
            f"/ws/stations/status?station_id={pending_station.id}&token={drv_token}"
        ):
            pass

    # Foreign operator blocked from approved_station (REQ-F1-12)
    foreign_token = _make_token(op_foreign)
    with pytest.raises((WebSocketDisconnect, Exception)):
        with client.websocket_connect(
            f"/ws/stations/status?station_id={approved_station.id}&token={foreign_token}"
        ):
            pass


def test_ws_live_status_push_delivered_to_all_open_station_dashboards(client, db_session):
    """
    STC-F2-19: Broadcast connector status changes to every open dashboard on the
    affected station immediately upon telemetry ingestion, without cross-station leakage.
    """
    driver1 = _make_user(
        db_session,
        name="WS Driver One",
        email="ws.d1@example.com",
        phone="+919600000004",
        role=UserRole.DRIVER,
    )
    driver2 = _make_user(
        db_session,
        name="WS Driver Two",
        email="ws.d2@example.com",
        phone="+919600000005",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="WS Op",
        email="ws.op@example.com",
        phone="+919600000006",
        role=UserRole.OPERATOR,
    )

    s1, _, _, s1_active_conn, s1_inactive_conn = _seed_station(
        db_session, operator, name="Hub Alpha", gateway_prefix="GW-S1"
    )
    s2, _, _, _, _ = _seed_station(
        db_session, operator, name="Hub Beta", gateway_prefix="GW-S2"
    )

    t1 = _make_token(driver1)
    t2 = _make_token(driver2)
    t_op = _make_token(operator)

    with (
        client.websocket_connect(
            f"/ws/stations/status?station_id={s1.id}&token={t1}"
        ) as ws_s1_drv1,
        client.websocket_connect(
            f"/ws/stations/{s1.id}/status?token={t2}"
        ) as ws_s1_drv2,
        client.websocket_connect(
            f"/ws/stations/status?station_id={s1.id}",
            headers={"Authorization": f"Bearer {t_op}"},
        ) as ws_s1_op,
        client.websocket_connect(
            f"/ws/stations/status?station_id={s2.id}&token={t1}"
        ) as ws_s2_drv1,
    ):
        # Initial snapshot frames (REQ-F2-18 + ADR-05)
        snap_d1 = ws_s1_drv1.receive_json()
        snap_d2 = ws_s1_drv2.receive_json()
        snap_op = ws_s1_op.receive_json()
        snap_s2 = ws_s2_drv1.receive_json()

        assert snap_d1["type"] == "snapshot"
        assert snap_d1["data"]["total_connectors"] == 1
        assert snap_d2["type"] == "snapshot"
        assert snap_op["type"] == "snapshot"
        assert snap_op["data"]["total_connectors"] == 2
        assert snap_s2["station_id"] == s2.id

        # Gateway pushes status change on s1 active connector -> Occupied
        started = datetime.now(timezone.utc)
        obs_ts = started.isoformat()
        ingest_resp = client.post(
            "/gateway/ocpp/1.6j",
            json={
                "connector_id": s1_active_conn.id,
                "status": "Charging",
                "observed_at": obs_ts,
                "errorCode": "NoError",
                "idempotency_key": "ws-push-evt-1",
            },
            headers=_gateway_header(),
        )
        assert ingest_resp.status_code == 200
        assert ingest_resp.json()["applied"] is True

        # Every open dashboard on s1 receives status_change within <10s SLA
        for ws_client in (ws_s1_drv1, ws_s1_drv2, ws_s1_op):
            push = ws_client.receive_json()
            assert push["type"] == "status_change"
            assert push["event"] == "connector_status_changed"
            assert push["station_id"] == s1.id
            assert push["connector_id"] == s1_active_conn.id
            assert push["previous_status"] == "Available"
            assert push["status"] == "Occupied"
            assert push["raw_status"] == "Charging"
            pushed_dt = datetime.fromisoformat(push["pushed_at"])
            assert (pushed_dt - started).total_seconds() < 10.0

        # Station 2 subscriber received no Station 1 event; ping responds directly with pong
        ws_s2_drv1.send_json({"action": "ping"})
        pong_s2 = ws_s2_drv1.receive_json()
        assert pong_s2["type"] == "pong"
        assert pong_s2["station_id"] == s2.id

        # Duplicate idempotent replay does not push duplicate change event
        replay_resp = client.post(
            "/gateway/ocpp/1.6j",
            json={
                "connector_id": s1_active_conn.id,
                "status": "Charging",
                "observed_at": obs_ts,
                "idempotency_key": "ws-push-evt-1",
            },
            headers=_gateway_header(),
        )
        assert replay_resp.status_code == 200
        assert replay_resp.json()["idempotent_replay"] is True

        # Inactive charger update goes to operator dashboard ONLY, hidden from drivers
        inactive_resp = client.post(
            "/gateway/ocpp/1.6j",
            json={
                "connector_id": s1_inactive_conn.id,
                "status": "Faulted",
                "observed_at": datetime.now(timezone.utc).isoformat(),
            },
            headers=_gateway_header(),
        )
        assert inactive_resp.status_code == 200

        op_push = ws_s1_op.receive_json()
        assert op_push["connector_id"] == s1_inactive_conn.id
        assert op_push["status"] == "Faulted"

        # Driver still gets ping->pong next without seeing inactive charger event or duplicate
        ws_s1_drv1.send_json({"action": "ping"})
        assert ws_s1_drv1.receive_json()["type"] == "pong"

        # Control error handling + refresh + clean unsubscribe
        ws_s1_drv1.send_text("not-valid-json")
        err_msg = ws_s1_drv1.receive_json()
        assert err_msg["type"] == "error"
        assert err_msg["code"] == "INVALID_MESSAGE"

        ws_s1_drv1.send_json({"action": "refresh"})
        refreshed = ws_s1_drv1.receive_json()
        assert refreshed["type"] == "snapshot"
        assert refreshed["data"]["connectors"][0]["status"] == "Occupied"

        ws_s1_drv1.send_json({"action": "unsubscribe"})
        unsub = ws_s1_drv1.receive_json()
        assert unsub["type"] == "unsubscribed"

