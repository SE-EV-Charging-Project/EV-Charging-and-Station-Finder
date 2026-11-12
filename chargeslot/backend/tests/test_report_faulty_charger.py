from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from app.discovery.reports import (
    MAX_FAULT_DESCRIPTION_LENGTH,
    report_faulty_charger,
    resolve_operator_forwarding_channels,
    validate_fault_report_input,
)
from app.models.audit import AuditLog
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.fault_report import (
    FaultReportStatus,
    FaultSeverity,
    FaultType,
    FaultyChargerReport,
)
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
    organization: str | None = None,
    notify_email: bool = True,
    notify_sms: bool = True,
    notify_push: bool = True,
) -> User:
    user = User(
        name=name,
        email=email,
        phone=phone,
        hashed_password=hash_password("StrongPass!1"),
        role=role,
        is_active=True,
        is_verified=True,
        operator_organization=organization,
        notify_email=notify_email,
        notify_sms=notify_sms,
        notify_push=notify_push,
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


def _seed_station_and_charger(
    db_session,
    operator: User,
    *,
    name: str = "Spark Hub",
    status_val: StationStatus = StationStatus.APPROVED,
    station_active: bool = True,
    charger_active: bool = True,
) -> tuple[Station, Charger, Connector]:
    station = Station(
        operator_id=operator.id,
        name=name,
        address="88 Koramangala 4th Block, Bengaluru",
        latitude=12.9352,
        longitude=77.6245,
        amenities=["WiFi", "Restroom"],
        operating_hours="24x7",
        contact_phone="+919845001122",
        contact_email="ops@sparkhub.example",
        price_per_kwh=17.0,
        status=status_val,
        is_active=station_active,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="DC Hyper Unit 1",
        power_kw=150.0,
        current_type=CurrentType.DC,
        gateway_id=f"GW-FAULT-{station.id}-{datetime.now(timezone.utc).timestamp()}",
        is_active=charger_active,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector = Connector(
        charger_id=charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc),
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(station)
    db_session.refresh(charger)
    db_session.refresh(connector)
    return station, charger, connector


# ==============================================================================
# Unit Tests: TC-F2-16 (REQ-F2-16 / CS19-042)
# ==============================================================================


def test_validate_fault_report_input_bounds_and_invalid_values():
    desc, ftype, sev = validate_fault_report_input(
        charger_id=1,
        description="  Connector pin bent and sparking  ",
        fault_type="connector_damage",
        severity="high",
    )
    assert desc == "Connector pin bent and sparking"
    assert ftype == FaultType.CONNECTOR_DAMAGE
    assert sev == FaultSeverity.HIGH

    with pytest.raises(HTTPException) as exc_cid:
        validate_fault_report_input(0, "Valid description here")
    assert exc_cid.value.status_code == 422

    with pytest.raises(HTTPException) as exc_short:
        validate_fault_report_input(1, "  bad ")
    assert exc_short.value.status_code == 422

    with pytest.raises(HTTPException) as exc_long:
        validate_fault_report_input(1, "x" * (MAX_FAULT_DESCRIPTION_LENGTH + 1))
    assert exc_long.value.status_code == 422

    with pytest.raises(HTTPException) as exc_type:
        validate_fault_report_input(1, "Valid description", fault_type="unknown_type")
    assert exc_type.value.status_code == 422

    with pytest.raises(HTTPException) as exc_sev:
        validate_fault_report_input(1, "Valid description", severity="extreme")
    assert exc_sev.value.status_code == 422


def test_resolve_operator_forwarding_channels_respects_preferences(db_session):
    op = _make_user(
        db_session,
        name="Channel Op",
        email="chan.op@example.com",
        phone="+919900220001",
        role=UserRole.OPERATOR,
        notify_email=True,
        notify_sms=False,
        notify_push=True,
    )
    station, _, _ = _seed_station_and_charger(db_session, op)

    channels, target_email, target_phone = resolve_operator_forwarding_channels(station, op)
    assert channels == ["in_app", "email", "push"]
    assert target_email == "ops@sparkhub.example"
    assert target_phone == "+919845001122"


def test_report_faulty_charger_persists_forwards_and_audits(db_session):
    driver = _make_user(
        db_session,
        name="Ananya Driver",
        email="ananya.flt@example.com",
        phone="+919900220002",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Spark Operator",
        email="spark.op@example.com",
        phone="+919900220003",
        role=UserRole.OPERATOR,
        organization="Spark Energy Ltd",
    )
    station, charger, connector = _seed_station_and_charger(db_session, operator)

    res = report_faulty_charger(
        db_session,
        user=driver,
        charger_id=charger.id,
        connector_id=connector.id,
        fault_type=FaultType.POWER_FAILURE,
        severity=FaultSeverity.CRITICAL,
        description="Display blacked out and charging stops after 10 seconds.",
    )
    assert res.report.status == FaultReportStatus.FORWARDED.value
    assert res.report.operator_id == operator.id
    assert res.report.forwarding.operator_name == "Spark Operator"
    assert res.report.forwarding.organization == "Spark Energy Ltd"
    assert "email" in res.report.forwarding.channels
    assert db_session.query(FaultyChargerReport).count() == 1

    # Both reporter action and operator forwarding audit events logged
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver.id,
            AuditLog.action == "FAULTY_CHARGER_REPORTED",
        )
        .count()
        == 1
    )
    assert (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == operator.id,
            AuditLog.action == "FAULTY_CHARGER_REPORT_FORWARDED",
        )
        .count()
        == 1
    )


def test_report_faulty_charger_visibility_role_and_mismatch_guards(db_session):
    driver = _make_user(
        db_session,
        name="Guard Driver",
        email="guard.drv@example.com",
        phone="+919900220004",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Guard Op",
        email="guard.op@example.com",
        phone="+919900220005",
        role=UserRole.OPERATOR,
    )
    station_a, charger_a, _ = _seed_station_and_charger(db_session, operator, name="Hub A")
    station_b, _, conn_b = _seed_station_and_charger(db_session, operator, name="Hub B")
    _, pending_charger, _ = _seed_station_and_charger(
        db_session, operator, name="Pending Hub", status_val=StationStatus.PENDING
    )
    _, inactive_charger, _ = _seed_station_and_charger(
        db_session, operator, name="Inactive Charger Hub", charger_active=False
    )

    # Operator role denied -> 403
    with pytest.raises(HTTPException) as exc_op:
        report_faulty_charger(db_session, user=operator, charger_id=charger_a.id, description="Charger fault")
    assert exc_op.value.status_code == 403

    # Driver blocked on unapproved station / inactive charger -> 404
    for hidden in (pending_charger, inactive_charger):
        with pytest.raises(HTTPException) as exc_vis:
            report_faulty_charger(db_session, user=driver, charger_id=hidden.id, description="Charger fault")
        assert exc_vis.value.status_code == 404

    # Mismatched station_id -> 422
    with pytest.raises(HTTPException) as exc_st:
        report_faulty_charger(
            db_session,
            user=driver,
            charger_id=charger_a.id,
            station_id=station_b.id,
            description="Wrong station ID test",
        )
    assert exc_st.value.status_code == 422

    # Mismatched connector_id -> 422
    with pytest.raises(HTTPException) as exc_conn:
        report_faulty_charger(
            db_session,
            user=driver,
            charger_id=charger_a.id,
            connector_id=conn_b.id,
            description="Wrong connector ID test",
        )
    assert exc_conn.value.status_code == 422


# ==============================================================================
# Integration / API Tests: STC-F2-16
# ==============================================================================


def test_api_report_faulty_charger_and_forward_workflow(client, db_session):
    driver = _make_user(
        db_session,
        name="API Fault Driver",
        email="api.flt.drv@example.com",
        phone="+919900330001",
        role=UserRole.DRIVER,
    )
    owner_op = _make_user(
        db_session,
        name="Owner Fault Op",
        email="api.flt.op@example.com",
        phone="+919900330002",
        role=UserRole.OPERATOR,
        organization="PowerGrid EV",
    )
    station, charger, connector = _seed_station_and_charger(db_session, owner_op)

    # 1. Submit via contract route POST /api/v1/stations/report-faulty-charger
    res_create = client.post(
        "/api/v1/stations/report-faulty-charger",
        json={
            "charger_id": charger.id,
            "connector_id": connector.id,
            "fault_type": "connector_damage",
            "severity": "high",
            "description": "CCS2 locking latch is broken and fails to engage.",
        },
        headers=_auth_header(driver),
    )
    assert res_create.status_code == 201
    created = res_create.json()["report"]
    assert created["status"] == "forwarded"
    assert created["operator_id"] == owner_op.id
    assert created["forwarding"]["operator_name"] == "Owner Fault Op"
    assert created["forwarding"]["organization"] == "PowerGrid EV"
    report_id = created["id"]

    # 2. Owning operator receives forwarded report in their inbox
    res_op_list = client.get(
        "/api/v1/stations/report-faulty-charger",
        headers=_auth_header(owner_op),
    )
    assert res_op_list.status_code == 200
    assert res_op_list.json()["total"] == 1
    assert res_op_list.json()["reports"][0]["id"] == report_id

    res_station_list = client.get(
        f"/api/v1/stations/{station.id}/fault-reports",
        headers=_auth_header(owner_op),
    )
    assert res_station_list.status_code == 200
    assert res_station_list.json()["total"] == 1

    # 3. Owning operator resolves the forwarded fault report
    res_resolve = client.patch(
        f"/api/v1/stations/fault-reports/{report_id}/status",
        json={
            "status": "resolved",
            "operator_notes": "Technician replaced CCS2 latch pin.",
        },
        headers=_auth_header(owner_op),
    )
    assert res_resolve.status_code == 200
    resolved = res_resolve.json()
    assert resolved["status"] == "resolved"
    assert resolved["operator_notes"] == "Technician replaced CCS2 latch pin."
    assert resolved["resolved_at"] is not None


def test_api_report_fault_path_alias_rbac_and_validation(client, db_session):
    driver_a = _make_user(
        db_session,
        name="Reporter A",
        email="rep.a@example.com",
        phone="+919900440001",
        role=UserRole.DRIVER,
    )
    driver_b = _make_user(
        db_session,
        name="Reporter B",
        email="rep.b@example.com",
        phone="+919900440002",
        role=UserRole.DRIVER,
    )
    owner_op = _make_user(
        db_session,
        name="Owner Op",
        email="own.op@example.com",
        phone="+919900440003",
        role=UserRole.OPERATOR,
    )
    foreign_op = _make_user(
        db_session,
        name="Foreign Op",
        email="for.op@example.com",
        phone="+919900440004",
        role=UserRole.OPERATOR,
    )
    station, charger, _ = _seed_station_and_charger(db_session, owner_op)

    # Unauthenticated -> 401
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": charger.id, "description": "Unauthenticated test fault"},
        ).status_code
        == 401
    )

    # Driver A submits via REST path alias
    res_alias = client.post(
        f"/api/v1/stations/chargers/{charger.id}/report-fault",
        json={"description": "Screen unresponsive on DC Hyper Unit 1"},
        headers=_auth_header(driver_a),
    )
    assert res_alias.status_code == 201
    report_id = res_alias.json()["report"]["id"]

    # Driver isolation: Driver B does not see Driver A's report
    assert (
        client.get(
            "/api/v1/stations/report-faulty-charger",
            headers=_auth_header(driver_b),
        ).json()["total"]
        == 0
    )

    # Foreign operator denied from reading/updating station reports -> 403 (REQ-F1-12)
    assert (
        client.get(
            f"/api/v1/stations/{station.id}/fault-reports",
            headers=_auth_header(foreign_op),
        ).status_code
        == 403
    )
    assert (
        client.patch(
            f"/api/v1/stations/fault-reports/{report_id}/status",
            json={"status": "acknowledged"},
            headers=_auth_header(foreign_op),
        ).status_code
        == 403
    )

    # Driver cannot update status -> 403
    assert (
        client.patch(
            f"/api/v1/stations/fault-reports/{report_id}/status",
            json={"status": "resolved"},
            headers=_auth_header(driver_a),
        ).status_code
        == 403
    )

    # Operator cannot submit a driver fault report -> 403
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": charger.id, "description": "Operator reporting test"},
            headers=_auth_header(owner_op),
        ).status_code
        == 403
    )

    # Missing charger -> 404
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": 99999, "description": "Charger not found check"},
            headers=_auth_header(driver_a),
        ).status_code
        == 404
    )

    # Malformed / out-of-range inputs -> 422
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": 0, "description": "Bad charger id"},
            headers=_auth_header(driver_a),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": charger.id, "description": "hi"},
            headers=_auth_header(driver_a),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/stations/report-faulty-charger",
            json={"charger_id": charger.id, "description": "Bad severity", "severity": "panic"},
            headers=_auth_header(driver_a),
        ).status_code
        == 422
    )

