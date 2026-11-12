from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.dashboard.views import (
    get_live_connector_status_display,
    validate_live_status_params,
)
from app.gateway.ingest import ingest_status
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


def _seed_dashboard_station(
    db_session,
    operator: User,
    *,
    name: str = "Live Status Plaza",
    status_val: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
) -> tuple[Station, Charger, Charger, list[Connector]]:
    t_base = datetime(2026, 5, 10, 9, 0, 0, tzinfo=timezone.utc)

    station = Station(
        operator_id=operator.id,
        name=name,
        address="15 Indiranagar 100ft Rd, Bengaluru",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["WiFi", "Cafe"],
        operating_hours="24x7",
        contact_phone="+919876511111",
        contact_email="plaza@chargeslot.example",
        price_per_kwh=17.5,
        status=status_val,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.flush()

    active_charger = Charger(
        station_id=station.id,
        name="FastBay 1",
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id="GW-DISP-01",
        is_active=True,
        is_out_of_service=False,
    )
    oos_charger = Charger(
        station_id=station.id,
        name="AC Bay 2",
        power_kw=22.0,
        current_type=CurrentType.AC,
        gateway_id="GW-DISP-02",
        is_active=True,
        is_out_of_service=True,
        out_of_service_reason="Scheduled relay swap",
        expected_return_time=t_base + timedelta(hours=3),
    )
    inactive_charger = Charger(
        station_id=station.id,
        name="Decommissioned Unit",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-DISP-OLD",
        is_active=False,
        is_out_of_service=False,
    )
    db_session.add_all([active_charger, oos_charger, inactive_charger])
    db_session.flush()

    c_avail = Connector(
        charger_id=active_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=t_base,
    )
    c_occ = Connector(
        charger_id=active_charger.id,
        connector_type="CHAdeMO",
        status=ConnectorStatus.OCCUPIED,
        last_update=t_base + timedelta(minutes=5),
    )
    c_oos = Connector(
        charger_id=oos_charger.id,
        connector_type="Type 2",
        status=ConnectorStatus.AVAILABLE,
        last_update=t_base + timedelta(minutes=2),
    )
    c_inactive = Connector(
        charger_id=inactive_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.OFFLINE,
        last_update=t_base,
    )
    db_session.add_all([c_avail, c_occ, c_oos, c_inactive])
    db_session.commit()
    for conn in (c_avail, c_occ, c_oos, c_inactive):
        db_session.refresh(conn)

    return station, active_charger, oos_charger, [c_avail, c_occ, c_oos, c_inactive]


# ==============================================================================
# Unit Tests: TC-F2-18
# ==============================================================================


def test_validate_live_status_params_valid_and_invalid():
    assert validate_live_status_params(station_id=1) is None
    assert validate_live_status_params(connector_id=5, status_filter="occupied") == (
        ConnectorStatus.OCCUPIED
    )
    assert validate_live_status_params(station_id=2, status_filter="  RESERVED ") == (
        ConnectorStatus.RESERVED
    )

    for kwargs in [
        {},
        {"station_id": 0},
        {"connector_id": -3},
        {"station_id": 1, "status_filter": "UnknownStatus"},
    ]:
        with pytest.raises(HTTPException) as exc:
            validate_live_status_params(**kwargs)
        assert exc.value.status_code == 422


def test_get_live_connector_status_display_unit_driver_vs_operator_and_oos(db_session):
    driver = _make_user(
        db_session,
        name="Drv View",
        email="drv.view@example.com",
        phone="+919700000001",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="Op Owner",
        email="op.owner@example.com",
        phone="+919700000002",
        role=UserRole.OPERATOR,
    )
    op_other = _make_user(
        db_session,
        name="Op Other",
        email="op.other@example.com",
        phone="+919700000003",
        role=UserRole.OPERATOR,
    )
    station, _, _, connectors = _seed_dashboard_station(db_session, op_owner)
    c_avail, c_occ, c_oos, c_inactive = connectors

    # Driver view hides inactive charger -> 3 connectors; OOS surfaces as Offline
    drv_view = get_live_connector_status_display(
        db_session, driver, station_id=station.id
    )
    assert drv_view.station_id == station.id
    assert drv_view.total_connectors == 3
    assert drv_view.available_connectors == 1
    assert drv_view.occupied_connectors == 1
    assert drv_view.offline_connectors == 1
    assert drv_view.last_status_update is not None

    by_id = {c.connector_id: c for c in drv_view.connectors}
    assert c_inactive.id not in by_id
    assert by_id[c_avail.id].status == "Available"
    assert by_id[c_avail.id].seconds_since_update >= 0
    assert by_id[c_occ.id].status == "Occupied"
    assert by_id[c_oos.id].status == "Offline"
    assert by_id[c_oos.id].is_out_of_service is True
    assert by_id[c_oos.id].out_of_service_reason == "Scheduled relay swap"

    # Single-connector lookup resolves station cleanly and carries latest error_code
    obs_time = datetime(2026, 5, 10, 10, 30, 0, tzinfo=timezone.utc)
    ingest_status(
        db_session,
        c_avail.id,
        "Faulted",
        obs_time,
        error_code="GroundFailure",
        idempotency_key="disp-unit-fault-1",
    )
    single_view = get_live_connector_status_display(
        db_session, driver, connector_id=c_avail.id
    )
    assert len(single_view.connectors) == 1
    assert single_view.connectors[0].status == "Faulted"
    assert single_view.connectors[0].last_update == obs_time
    assert single_view.connectors[0].latest_error_code == "GroundFailure"

    # Owning operator sees inactive charger too (4 connectors); foreign operator -> 403
    op_view = get_live_connector_status_display(
        db_session, op_owner, station_id=station.id
    )
    assert op_view.total_connectors == 4

    with pytest.raises(HTTPException) as exc_foreign:
        get_live_connector_status_display(db_session, op_other, station_id=station.id)
    assert exc_foreign.value.status_code == 403

    # Driver cannot access connector on inactive charger
    with pytest.raises(HTTPException) as exc_inactive:
        get_live_connector_status_display(db_session, driver, connector_id=c_inactive.id)
    assert exc_inactive.value.status_code == 404


def test_get_live_connector_status_display_rejects_mismatched_station_and_pending(db_session):
    driver = _make_user(
        db_session,
        name="Drv Gate",
        email="drv.gate@example.com",
        phone="+919700000004",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op Two",
        email="op.two@example.com",
        phone="+919700000005",
        role=UserRole.OPERATOR,
    )
    station1, _, _, conns1 = _seed_dashboard_station(db_session, operator, name="Hub One")
    station2, _, _, _ = _seed_dashboard_station(
        db_session, operator, name="Pending Hub", status_val=StationStatus.PENDING
    )

    with pytest.raises(HTTPException) as exc_pending:
        get_live_connector_status_display(db_session, driver, station_id=station2.id)
    assert exc_pending.value.status_code == 404

    with pytest.raises(HTTPException) as exc_mismatch:
        get_live_connector_status_display(
            db_session, driver, station_id=station2.id, connector_id=conns1[0].id
        )
    # Driver check hides unapproved station2 first with 404; operator sees 422 mismatch
    assert exc_mismatch.value.status_code == 404

    with pytest.raises(HTTPException) as exc_op_mismatch:
        get_live_connector_status_display(
            db_session, operator, station_id=station2.id, connector_id=conns1[0].id
        )
    assert exc_op_mismatch.value.status_code == 422


# ==============================================================================
# System / API Integration Tests: STC-F2-18
# ==============================================================================


def test_api_live_status_display_reflects_ingested_gateway_updates(client, db_session):
    """STC-F2-18: Live status display updates immediately after gateway ingestion."""
    driver = _make_user(
        db_session,
        name="Drv Live API",
        email="drv.api@example.com",
        phone="+919700000006",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op Live API",
        email="op.api@example.com",
        phone="+919700000007",
        role=UserRole.OPERATOR,
    )
    station, _, _, connectors = _seed_dashboard_station(db_session, operator)
    c_avail, c_occ, _, _ = connectors

    # Initial architecture route query
    res_before = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res_before.status_code == 200
    before = res_before.json()
    assert before["station_id"] == station.id
    assert before["total_connectors"] == 3
    assert before["available_connectors"] == 1
    assert before["availability_summary"]["color_code"] == "amber"

    # Gateway ingests status transition on c_avail -> Reserved, and c_occ -> Available
    t1 = "2026-05-10T11:15:00Z"
    t2 = "2026-05-10T11:20:00Z"
    assert (
        client.post(
            "/gateway/ocpp/1.6j",
            json={
                "connector_id": c_avail.id,
                "status": "Reserved",
                "observed_at": t1,
                "idempotency_key": "stc-f2-18-msg-1",
            },
            headers=_gateway_header(),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/gateway/ocpp/1.6j",
            json={
                "connector_id": c_occ.id,
                "status": "Available",
                "observed_at": t2,
                "idempotency_key": "stc-f2-18-msg-2",
            },
            headers=_gateway_header(),
        ).status_code
        == 200
    )

    res_after = client.get(
        f"/api/v1/stations/live-status-display?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res_after.status_code == 200
    after = res_after.json()
    assert after["available_connectors"] == 1
    assert after["reserved_connectors"] == 1
    assert after["occupied_connectors"] == 0
    assert after["offline_connectors"] == 1
    assert after["last_status_update"].startswith("2026-05-10T11:20:00")

    by_id = {c["connector_id"]: c for c in after["connectors"]}
    assert by_id[c_avail.id]["status"] == "Reserved"
    assert by_id[c_avail.id]["last_update"].startswith("2026-05-10T11:15:00")
    assert by_id[c_occ.id]["status"] == "Available"
    assert by_id[c_occ.id]["last_update"].startswith("2026-05-10T11:20:00")

    # Filtered query & path aliases work consistently
    res_filtered = client.get(
        f"/api/v1/stations/{station.id}/live-status?status=Reserved",
        headers=_auth_header(driver),
    )
    assert res_filtered.status_code == 200
    assert [c["connector_id"] for c in res_filtered.json()["connectors"]] == [c_avail.id]

    res_conn = client.get(
        f"/api/v1/connectors/{c_occ.id}/live-status",
        headers=_auth_header(driver),
    )
    assert res_conn.status_code == 200
    assert res_conn.json()["connectors"][0]["status"] == "Available"


def test_api_live_status_display_auth_rbac_and_validation(client, db_session):
    driver = _make_user(
        db_session,
        name="Drv RBAC",
        email="drv.rbac@example.com",
        phone="+919700000008",
        role=UserRole.DRIVER,
    )
    op_owner = _make_user(
        db_session,
        name="Op Own",
        email="op.own51@example.com",
        phone="+919700000009",
        role=UserRole.OPERATOR,
    )
    op_foreign = _make_user(
        db_session,
        name="Op Foreign",
        email="op.for51@example.com",
        phone="+919700000010",
        role=UserRole.OPERATOR,
    )
    admin = _make_user(
        db_session,
        name="Admin 51",
        email="admin.51@example.com",
        phone="+919700000011",
        role=UserRole.ADMIN,
    )
    station, _, _, _ = _seed_dashboard_station(
        db_session, op_owner, status_val=StationStatus.PENDING
    )

    # Unauthenticated -> 401
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}"
        ).status_code
        == 401
    )
    # Missing query args -> 422
    assert (
        client.get(
            "/api/v1/stations/live-status-display", headers=_auth_header(driver)
        ).status_code
        == 422
    )
    # Invalid status filter -> 422
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}&status=Bogus",
            headers=_auth_header(op_owner),
        ).status_code
        == 422
    )
    # Driver cannot inspect pending station -> 404
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}",
            headers=_auth_header(driver),
        ).status_code
        == 404
    )
    # Foreign operator -> 403
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}",
            headers=_auth_header(op_foreign),
        ).status_code
        == 403
    )
    # Owning operator and Admin -> 200
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}",
            headers=_auth_header(op_owner),
        ).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/v1/stations/live-status-display?station_id={station.id}",
            headers=_auth_header(admin),
        ).status_code
        == 200
    )

