from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
from fastapi import HTTPException

from app.discovery.views import (
    build_station_detail,
    compute_station_rating_summary,
    validate_station_detail_params,
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
    organization: str | None = None,
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


def _seed_station_with_chargers(
    db_session,
    operator: User,
    *,
    name: str = "GreenCharge Hub",
    status_val: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
    price_per_kwh: float = 16.5,
) -> Station:
    t1 = datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 5, 1, 10, 15, tzinfo=timezone.utc)
    expected_return = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)

    station = Station(
        operator_id=operator.id,
        name=name,
        address="100 MG Road, Bengaluru",
        latitude=12.9716,
        longitude=77.5946,
        amenities=["WiFi", "Cafe", "Restroom"],
        operating_hours="Mon-Fri 06:00-23:00, Sat-Sun 07:00-22:00",
        contact_phone="+919876500001",
        contact_email="hub@greencharge.example",
        price_per_kwh=price_per_kwh,
        status=status_val,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.flush()

    fast_charger = Charger(
        station_id=station.id,
        name="DC Fast Unit 1",
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id="GW-DETAIL-01",
        is_active=True,
        is_out_of_service=False,
    )
    oos_charger = Charger(
        station_id=station.id,
        name="AC Backup Unit 2",
        power_kw=22.0,
        current_type=CurrentType.AC,
        gateway_id="GW-DETAIL-02",
        is_active=True,
        is_out_of_service=True,
        out_of_service_reason="Cable inspection",
        expected_return_time=expected_return,
    )
    inactive_charger = Charger(
        station_id=station.id,
        name="Decommissioned Unit 3",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-DETAIL-03",
        is_active=False,
        is_out_of_service=False,
    )
    db_session.add_all([fast_charger, oos_charger, inactive_charger])
    db_session.flush()

    c1 = Connector(
        charger_id=fast_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=t1,
    )
    c2 = Connector(
        charger_id=fast_charger.id,
        connector_type="CHAdeMO",
        status=ConnectorStatus.OCCUPIED,
        last_update=t2,
    )
    c3 = Connector(
        charger_id=oos_charger.id,
        connector_type="Type 2",
        status=ConnectorStatus.AVAILABLE,
        last_update=t1,
    )
    c4 = Connector(
        charger_id=inactive_charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=t2 + timedelta(minutes=5),
    )
    db_session.add_all([c1, c2, c3, c4])
    db_session.commit()
    db_session.refresh(station)
    return station


# ==============================================================================
# Unit Tests: TC-F2-13 (REQ-F2-13 / SR-F2-03 / BR-11)
# ==============================================================================


def test_compute_station_rating_summary_handles_empty_and_valid_reviews():
    station_no_reviews = SimpleNamespace(reviews=None)
    assert compute_station_rating_summary(station_no_reviews) == (None, 0)

    station_with_reviews = SimpleNamespace(
        reviews=[
            SimpleNamespace(rating=5),
            SimpleNamespace(rating=4),
            SimpleNamespace(rating=True),  # invalid bool ignored
            SimpleNamespace(rating=7),     # out of [1..5] ignored
        ]
    )
    avg, count = compute_station_rating_summary(station_with_reviews)
    assert avg == 4.5
    assert count == 2


def test_validate_station_detail_params_rejects_invalid_inputs():
    validate_station_detail_params(1)
    validate_station_detail_params(1, latitude=12.97, longitude=77.59)

    with pytest.raises(HTTPException) as exc_id:
        validate_station_detail_params(0)
    assert exc_id.value.status_code == 422

    with pytest.raises(HTTPException) as exc_pair:
        validate_station_detail_params(1, latitude=12.97, longitude=None)
    assert exc_pair.value.status_code == 422

    with pytest.raises(HTTPException) as exc_bounds:
        validate_station_detail_params(1, latitude=95.0, longitude=77.59)
    assert exc_bounds.value.status_code == 422


def test_build_station_detail_driver_vs_operator_and_oos_status(db_session):
    operator = _make_user(
        db_session,
        name="Riya Operator",
        email="riya.op@example.com",
        phone="+919900112233",
        role=UserRole.OPERATOR,
        organization="VoltGrid Networks",
    )
    station = _seed_station_with_chargers(db_session, operator)

    driver_detail = build_station_detail(
        station,
        include_inactive_chargers=False,
        latitude=12.9716,
        longitude=77.5946,
    )
    assert driver_detail.name == "GreenCharge Hub"
    assert driver_detail.address == "100 MG Road, Bengaluru"
    assert driver_detail.operator.name == "Riya Operator"
    assert driver_detail.operator.organization == "VoltGrid Networks"
    assert driver_detail.amenities == ["WiFi", "Cafe", "Restroom"]
    assert driver_detail.operating_hours == "Mon-Fri 06:00-23:00, Sat-Sun 07:00-22:00"
    assert driver_detail.price_per_kwh == 16.5
    assert driver_detail.average_rating is None
    assert driver_detail.total_reviews == 0
    assert driver_detail.distance_km == 0.0
    # BR-11: inactive charger excluded -> only 2 chargers & 3 connectors
    assert len(driver_detail.chargers) == 2
    assert driver_detail.total_connectors == 3
    assert driver_detail.available_connectors == 1
    assert driver_detail.last_status_update is not None

    # Out-of-service charger connector must surface live status as offline
    oos_connector = next(
        c for c in driver_detail.connectors if c.connector_type == "Type 2"
    )
    assert oos_connector.is_out_of_service is True
    assert oos_connector.status == ConnectorStatus.OFFLINE.value
    assert oos_connector.out_of_service_reason == "Cable inspection"
    assert oos_connector.expected_return_time is not None

    # Operator view includes inactive charger
    op_detail = build_station_detail(station, include_inactive_chargers=True)
    assert len(op_detail.chargers) == 3
    assert op_detail.total_connectors == 4


# ==============================================================================
# Integration / API Tests: STC-F2-13
# ==============================================================================


def test_api_station_detail_query_and_path_routes_for_driver(client, db_session):
    driver = _make_user(
        db_session,
        name="Aarav Driver",
        email="aarav.driver@example.com",
        phone="+919911223344",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Volt Operator",
        email="volt.op@example.com",
        phone="+919911223355",
        role=UserRole.OPERATOR,
        organization="Volt Infra Pvt Ltd",
    )
    station = _seed_station_with_chargers(db_session, operator)

    # Contract route: GET /api/v1/stations/station-detail
    res_query = client.get(
        f"/api/v1/stations/station-detail?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res_query.status_code == 200
    payload = res_query.json()
    assert payload["id"] == station.id
    assert payload["name"] == "GreenCharge Hub"
    assert payload["address"] == "100 MG Road, Bengaluru"
    assert payload["operator"]["name"] == "Volt Operator"
    assert payload["operator"]["organization"] == "Volt Infra Pvt Ltd"
    assert payload["amenities"] == ["WiFi", "Cafe", "Restroom"]
    assert payload["operating_hours"] == "Mon-Fri 06:00-23:00, Sat-Sun 07:00-22:00"
    assert payload["price_per_kwh"] == 16.5
    assert payload["average_rating"] is None
    assert payload["total_reviews"] == 0
    assert payload["distance_km"] is None
    assert payload["total_connectors"] == 3
    assert payload["available_connectors"] == 1
    assert payload["last_status_update"] is not None
    assert payload["availability_marker"]["color_code"] in {"green", "amber", "red", "grey"}

    connector_types = {c["connector_type"] for c in payload["connectors"]}
    assert connector_types == {"CCS2", "CHAdeMO", "Type 2"}
    for conn in payload["connectors"]:
        assert "power_kw" in conn
        assert "status" in conn
        assert "last_update" in conn

    # Path alias route with optional distance coordinates
    res_path = client.get(
        f"/api/v1/stations/{station.id}/detail?latitude=12.9816&longitude=77.5946",
        headers=_auth_header(driver),
    )
    assert res_path.status_code == 200
    path_payload = res_path.json()
    assert path_payload["id"] == station.id
    assert path_payload["distance_km"] > 0


def test_api_station_detail_driver_hidden_for_pending_rejected_inactive(client, db_session):
    driver = _make_user(
        db_session,
        name="Driver One",
        email="d1@example.com",
        phone="+919922000001",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op One",
        email="op1@example.com",
        phone="+919922000002",
        role=UserRole.OPERATOR,
    )
    pending = _seed_station_with_chargers(
        db_session, operator, name="Pending Site", status_val=StationStatus.PENDING
    )
    rejected = _seed_station_with_chargers(
        db_session, operator, name="Rejected Site", status_val=StationStatus.REJECTED
    )
    inactive = _seed_station_with_chargers(
        db_session,
        operator,
        name="Inactive Site",
        status_val=StationStatus.APPROVED,
        is_active=False,
    )

    for st in (pending, rejected, inactive):
        res = client.get(
            f"/api/v1/stations/station-detail?station_id={st.id}",
            headers=_auth_header(driver),
        )
        assert res.status_code == 404


def test_api_station_detail_operator_scoping_and_admin_access(client, db_session):
    owner_op = _make_user(
        db_session,
        name="Owner Op",
        email="owner.op@example.com",
        phone="+919933000001",
        role=UserRole.OPERATOR,
    )
    foreign_op = _make_user(
        db_session,
        name="Foreign Op",
        email="foreign.op@example.com",
        phone="+919933000002",
        role=UserRole.OPERATOR,
    )
    admin = _make_user(
        db_session,
        name="Admin User",
        email="admin@example.com",
        phone="+919933000003",
        role=UserRole.ADMIN,
    )
    pending_station = _seed_station_with_chargers(
        db_session,
        owner_op,
        name="Owner Pending Hub",
        status_val=StationStatus.PENDING,
    )

    # Owning operator can inspect own pending station including inactive charger
    res_owner = client.get(
        f"/api/v1/stations/{pending_station.id}/detail",
        headers=_auth_header(owner_op),
    )
    assert res_owner.status_code == 200
    assert len(res_owner.json()["chargers"]) == 3

    # Foreign operator receives 403 Forbidden (REQ-F1-12)
    res_foreign = client.get(
        f"/api/v1/stations/{pending_station.id}/detail",
        headers=_auth_header(foreign_op),
    )
    assert res_foreign.status_code == 403

    # Admin can inspect any station
    res_admin = client.get(
        f"/api/v1/stations/station-detail?station_id={pending_station.id}",
        headers=_auth_header(admin),
    )
    assert res_admin.status_code == 200
    assert res_admin.json()["status"] == "pending"


def test_api_station_detail_auth_not_found_and_validation_errors(client, db_session):
    driver = _make_user(
        db_session,
        name="Auth Check Driver",
        email="auth.driver@example.com",
        phone="+919944000001",
        role=UserRole.DRIVER,
    )

    # Unauthenticated -> 401
    res_unauth = client.get("/api/v1/stations/station-detail?station_id=1")
    assert res_unauth.status_code == 401

    # Missing ID -> 404
    res_missing = client.get(
        "/api/v1/stations/station-detail?station_id=99999",
        headers=_auth_header(driver),
    )
    assert res_missing.status_code == 404

    # Non-positive station_id -> 422
    res_bad_id = client.get(
        "/api/v1/stations/0/detail",
        headers=_auth_header(driver),
    )
    assert res_bad_id.status_code == 422

    # Unpaired coordinates -> 422
    res_unpaired = client.get(
        "/api/v1/stations/station-detail?station_id=1&latitude=12.97",
        headers=_auth_header(driver),
    )
    assert res_unpaired.status_code == 422
