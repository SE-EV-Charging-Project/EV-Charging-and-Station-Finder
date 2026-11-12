from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.dashboard.staleness import (
    STATUS_UNKNOWN,
    get_stale_connector_status_display,
    is_connector_stale,
    resolve_display_status_with_staleness,
    validate_stale_status_params,
)
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
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


def _gateway_header() -> dict[str, str]:
    return {"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET}


def _seed_mixed_freshness_station(
    db_session,
    operator: User,
    *,
    now_ref: datetime | None = None,
    status_val: StationStatus = StationStatus.APPROVED,
    gateway_prefix: str = "GW-STALE",
) -> tuple[Station, list[Connector]]:
    ref = now_ref or datetime.now(timezone.utc)

    station = Station(
        operator_id=operator.id,
        name="Freshness Monitor Hub",
        address="201 Outer Ring Rd, Bengaluru",
        latitude=12.9279,
        longitude=77.6271,
        amenities=["WiFi"],
        operating_hours="24x7",
        contact_phone="+919876533333",
        contact_email="stale@chargeslot.example",
        price_per_kwh=16.0,
        status=status_val,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()

    active_charger = Charger(
        station_id=station.id,
        name="Main Unit",
        power_kw=100.0,
        current_type=CurrentType.DC,
        gateway_id=f"{gateway_prefix}-1",
        is_active=True,
        is_out_of_service=False,
    )
    oos_charger = Charger(
        station_id=station.id,
        name="OOS Unit",
        power_kw=22.0,
        current_type=CurrentType.AC,
        gateway_id=f"{gateway_prefix}-2",
        is_active=True,
        is_out_of_service=True,
        out_of_service_reason="Hardware inspection",
    )
    inactive_charger = Charger(
        station_id=station.id,
        name="Inactive Unit",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id=f"{gateway_prefix}-3",
        is_active=False,
        is_out_of_service=False,
    )
    db_session.add_all([active_charger, oos_charger, inactive_charger])
    db_session.flush()

    c_fresh = Connector(
        charger_id=active_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=ref - timedelta(seconds=30),
    )
    c_stale = Connector(
        charger_id=active_charger.id,
        connector_type="CHAdeMO",
        status=ConnectorStatus.OCCUPIED,
        last_update=ref - timedelta(seconds=180),
    )
    c_oos = Connector(
        charger_id=oos_charger.id,
        connector_type="Type 2",
        status=ConnectorStatus.AVAILABLE,
        last_update=ref - timedelta(seconds=300),
    )
    c_inactive = Connector(
        charger_id=inactive_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.FAULTED,
        last_update=ref - timedelta(seconds=240),
    )
    db_session.add_all([c_fresh, c_stale, c_oos, c_inactive])
    db_session.commit()
    for conn in (c_fresh, c_stale, c_oos, c_inactive):
        db_session.refresh(conn)
    return station, [c_fresh, c_stale, c_oos, c_inactive]


# ==============================================================================
# Unit Tests: TC-F2-20
# ==============================================================================


def test_is_connector_stale_boundary_at_120_seconds():
    now_ref = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    # Exactly 120s elapsed -> NOT stale (rule is > 120 seconds)
    stale_120, sec_120 = is_connector_stale(
        now_ref - timedelta(seconds=120), now_utc=now_ref, threshold_seconds=120
    )
    assert stale_120 is False
    assert sec_120 == 120

    # 120.1s or 121s elapsed -> STALE
    stale_120_1, _ = is_connector_stale(
        now_ref - timedelta(seconds=120, milliseconds=100),
        now_utc=now_ref,
        threshold_seconds=120,
    )
    assert stale_120_1 is True

    stale_121, sec_121 = is_connector_stale(
        now_ref - timedelta(seconds=121), now_utc=now_ref, threshold_seconds=120
    )
    assert stale_121 is True
    assert sec_121 == 121

    # Missing last_update -> STALE
    stale_none, _ = is_connector_stale(None, now_utc=now_ref, threshold_seconds=120)
    assert stale_none is True


def test_resolve_display_status_with_staleness_replaces_cached_status():
    now_ref = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)

    fresh_status, fresh_flag, sec_fresh, _ = resolve_display_status_with_staleness(
        ConnectorStatus.OCCUPIED,
        now_ref - timedelta(seconds=45),
        now_utc=now_ref,
    )
    assert fresh_status == "Occupied"
    assert fresh_flag is False
    assert sec_fresh == 45

    stale_status, stale_flag, sec_stale, reason = resolve_display_status_with_staleness(
        ConnectorStatus.AVAILABLE,
        now_ref - timedelta(seconds=150),
        now_utc=now_ref,
    )
    assert stale_status == STATUS_UNKNOWN
    assert stale_flag is True
    assert sec_stale == 150
    assert "120" in reason

    # Out-of-service chargers keep 'Offline' while still flagging telemetry staleness
    oos_status, oos_stale, _, _ = resolve_display_status_with_staleness(
        ConnectorStatus.AVAILABLE,
        now_ref - timedelta(seconds=200),
        is_out_of_service=True,
        now_utc=now_ref,
    )
    assert oos_status == "Offline"
    assert oos_stale is True


def test_validate_stale_status_params_bounds():
    validate_stale_status_params(station_id=1, stale_threshold_seconds=120)
    for bad in [
        {"station_id": 1, "stale_threshold_seconds": 0},
        {"station_id": 1, "stale_threshold_seconds": -10},
        {"station_id": 1, "stale_threshold_seconds": 86401},
        {},
    ]:
        with pytest.raises(HTTPException) as exc:
            validate_stale_status_params(**bad)
        assert exc.value.status_code == 422


def test_get_stale_connector_status_display_unit_visibility_and_counts(db_session):
    now_ref = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    driver = _make_user(
        db_session,
        name="Drv Stale",
        email="drv.stale@example.com",
        phone="+919500000001",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="Op Stale",
        email="op.stale@example.com",
        phone="+919500000002",
        role=UserRole.OPERATOR,
    )
    op_other = _make_user(
        db_session,
        name="Op Other Stale",
        email="op.oth.stale@example.com",
        phone="+919500000003",
        role=UserRole.OPERATOR,
    )
    station, connectors = _seed_mixed_freshness_station(
        db_session, op_owner, now_ref=now_ref
    )
    c_fresh, c_stale, c_oos, c_inactive = connectors

    drv_view = get_stale_connector_status_display(
        db_session, driver, station_id=station.id, now_utc=now_ref
    )
    assert drv_view.total_connectors == 3
    assert drv_view.fresh_connectors == 1
    assert drv_view.stale_connectors == 2
    assert drv_view.unknown_status_connectors == 1

    by_id = {item.connector_id: item for item in drv_view.connectors}
    assert c_inactive.id not in by_id
    assert by_id[c_fresh.id].status == "Available"
    assert by_id[c_fresh.id].is_stale is False
    # Stale Occupied connector MUST show 'Status unknown', not 'Occupied'
    assert by_id[c_stale.id].status == "Status unknown"
    assert by_id[c_stale.id].is_stale is True
    assert by_id[c_oos.id].status == "Offline"
    assert by_id[c_oos.id].is_stale is True

    # Operator sees inactive charger connector as stale 'Status unknown' too
    op_view = get_stale_connector_status_display(
        db_session, op_owner, station_id=station.id, now_utc=now_ref
    )
    assert op_view.total_connectors == 4
    assert op_view.unknown_status_connectors == 2

    with pytest.raises(HTTPException) as exc:
        get_stale_connector_status_display(
            db_session, op_other, station_id=station.id, now_utc=now_ref
        )
    assert exc.value.status_code == 403


# ==============================================================================
# System / API Integration Tests: STC-F2-20
# ==============================================================================


def test_api_stale_status_handling_and_gateway_recovery(client, db_session):
    """
    STC-F2-20: Connectors >120s stale show 'Status unknown' and recover once a
    fresh gateway update arrives.
    """
    driver = _make_user(
        db_session,
        name="Drv STC",
        email="drv.stc20@example.com",
        phone="+919500000004",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op STC",
        email="op.stc20@example.com",
        phone="+919500000005",
        role=UserRole.OPERATOR,
    )
    now_ref = datetime.now(timezone.utc)
    station, connectors = _seed_mixed_freshness_station(
        db_session, operator, now_ref=now_ref, gateway_prefix="GW-STC20"
    )
    c_fresh, c_stale, _, _ = connectors

    # SW Architecture Page 6 route displays 'Status unknown' for stale connector
    res = client.get(
        f"/api/v1/stations/stale-status-handling?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res.status_code == 200
    body = res.json()
    assert body["stale_threshold_seconds"] == 120
    assert body["status_unknown_label"] == "Status unknown"
    assert body["fresh_connectors"] == 1
    assert body["unknown_status_connectors"] == 1

    by_id = {c["connector_id"]: c for c in body["connectors"]}
    assert by_id[c_fresh.id]["status"] == "Available"
    assert by_id[c_fresh.id]["is_stale"] is False
    assert by_id[c_stale.id]["status"] == "Status unknown"
    assert by_id[c_stale.id]["is_stale"] is True

    # live-status-display?apply_stale_fallback=true also surfaces 'Status unknown'
    live_res = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}&apply_stale_fallback=true",
        headers=_auth_header(driver),
    )
    assert live_res.status_code == 200
    assert live_res.json()["unknown_connectors"] == 1

    # Fresh gateway heartbeat for previously stale connector restores live status
    fresh_gw = client.post(
        "/gateway/ocpp/1.6j",
        json={
            "connector_id": c_stale.id,
            "status": "Available",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "stc-f2-20-recover-1",
        },
        headers=_gateway_header(),
    )
    assert fresh_gw.status_code == 200

    res_recovered = client.get(
        f"/api/v1/stations/stale-status-handling?connector_id={c_stale.id}",
        headers=_auth_header(driver),
    )
    assert res_recovered.status_code == 200
    recovered = res_recovered.json()["connectors"][0]
    assert recovered["status"] == "Available"
    assert recovered["is_stale"] is False


def test_api_stale_status_handling_auth_rbac_and_validation(client, db_session):
    driver = _make_user(
        db_session,
        name="Drv Auth20",
        email="drv.a20@example.com",
        phone="+919500000006",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="Op Own20",
        email="op.own20@example.com",
        phone="+919500000007",
        role=UserRole.OPERATOR,
    )
    op_other = _make_user(
        db_session,
        name="Op Oth20",
        email="op.oth20@example.com",
        phone="+919500000008",
        role=UserRole.OPERATOR,
    )
    pending_station, _ = _seed_mixed_freshness_station(
        db_session,
        op_owner,
        status_val=StationStatus.PENDING,
        gateway_prefix="GW-PEND20",
    )

    assert (
        client.get(
            f"/api/v1/stations/stale-status-handling?station_id={pending_station.id}"
        ).status_code
        == 401
    )
    assert (
        client.get(
            "/api/v1/stations/stale-status-handling",
            headers=_auth_header(driver),
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/stations/stale-status-handling?station_id={pending_station.id}&stale_threshold_seconds=0",
            headers=_auth_header(op_owner),
        ).status_code
        == 422
    )
    assert (
        client.get(
            f"/api/v1/stations/stale-status-handling?station_id={pending_station.id}",
            headers=_auth_header(driver),
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/v1/stations/stale-status-handling?station_id={pending_station.id}",
            headers=_auth_header(op_other),
        ).status_code
        == 403
    )
    assert (
        client.get(
            f"/api/v1/stations/stale-status-handling?station_id={pending_station.id}",
            headers=_auth_header(op_owner),
        ).status_code
        == 200
    )

