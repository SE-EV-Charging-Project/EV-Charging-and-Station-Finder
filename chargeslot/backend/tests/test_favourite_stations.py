from datetime import datetime, timezone
import pytest
from fastapi import HTTPException

from app.discovery.favourites import (
    list_favourite_stations,
    remove_favourite_station,
    save_favourite_station,
    validate_favourite_params,
)
from app.models.audit import AuditLog
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.favourite import FavouriteStation
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


def _seed_station(
    db_session,
    operator: User,
    *,
    name: str = "Metro EV Hub",
    latitude: float = 12.9716,
    longitude: float = 77.5946,
    status_val: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
    price_per_kwh: float = 14.5,
) -> Station:
    station = Station(
        operator_id=operator.id,
        name=name,
        address="42 Residency Road, Bengaluru",
        latitude=latitude,
        longitude=longitude,
        amenities=["WiFi", "Restroom"],
        operating_hours="24x7",
        contact_phone="+919800112233",
        contact_email="metro@ev.example",
        price_per_kwh=price_per_kwh,
        status=status_val,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.flush()

    charger = Charger(
        station_id=station.id,
        name="Fast Charger 1",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id=f"GW-FAV-{station.id}",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()

    connector = Connector(
        charger_id=charger.id,
        connector_type="CCS2",
        status=ConnectorStatus.AVAILABLE,
        last_update=datetime(2026, 5, 1, 10, 0, tzinfo=timezone.utc),
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(station)
    return station


# ==============================================================================
# Unit Tests: TC-F2-14 (REQ-F2-14 / CS19-040)
# ==============================================================================


def test_validate_favourite_params_rejects_invalid_inputs():
    validate_favourite_params(station_id=1)
    validate_favourite_params(latitude=12.97, longitude=77.59)

    with pytest.raises(HTTPException) as exc_id:
        validate_favourite_params(station_id=0)
    assert exc_id.value.status_code == 422

    with pytest.raises(HTTPException) as exc_pair:
        validate_favourite_params(latitude=12.97, longitude=None)
    assert exc_pair.value.status_code == 422

    with pytest.raises(HTTPException) as exc_bounds:
        validate_favourite_params(latitude=95.0, longitude=77.59)
    assert exc_bounds.value.status_code == 422


def test_save_list_remove_favourite_station_unit(db_session):
    driver = _make_user(
        db_session,
        name="Fav Driver",
        email="fav.driver@example.com",
        phone="+919900001101",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Station Operator",
        email="fav.op@example.com",
        phone="+919900001102",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)

    # Save favourite
    saved = save_favourite_station(
        db_session,
        user=driver,
        station_id=station.id,
        latitude=12.9716,
        longitude=77.5946,
    )
    assert saved.is_favourite is True
    assert saved.station_id == station.id
    assert saved.favourite is not None
    assert saved.favourite.distance_km == 0.0
    assert saved.favourite.availability_marker.color_code.value == "green"

    # Idempotent re-save does not duplicate rows
    resaved = save_favourite_station(db_session, user=driver, station_id=station.id)
    assert resaved.is_favourite is True
    assert (
        db_session.query(FavouriteStation)
        .filter(FavouriteStation.user_id == driver.id)
        .count()
        == 1
    )

    # List favourites
    listed = list_favourite_stations(db_session, user=driver)
    assert listed.total == 1
    assert listed.stations[0].name == "Metro EV Hub"

    # Audit log recorded
    added_log = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver.id,
            AuditLog.action == "FAVOURITE_STATION_ADDED",
        )
        .first()
    )
    assert added_log is not None

    # Remove favourite
    removed = remove_favourite_station(db_session, user=driver, station_id=station.id)
    assert removed.is_favourite is False
    assert removed.favourite is None
    assert list_favourite_stations(db_session, user=driver).total == 0

    removed_log = (
        db_session.query(AuditLog)
        .filter(
            AuditLog.user_id == driver.id,
            AuditLog.action == "FAVOURITE_STATION_REMOVED",
        )
        .first()
    )
    assert removed_log is not None


def test_save_favourite_rejects_unapproved_or_inactive_and_operator_role(db_session):
    driver = _make_user(
        db_session,
        name="Driver User",
        email="drv.vis@example.com",
        phone="+919900001103",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op User",
        email="op.vis@example.com",
        phone="+919900001104",
        role=UserRole.OPERATOR,
    )
    approved = _seed_station(db_session, operator, name="Open Hub")
    pending = _seed_station(
        db_session, operator, name="Pending Hub", status_val=StationStatus.PENDING
    )
    inactive = _seed_station(
        db_session,
        operator,
        name="Inactive Hub",
        status_val=StationStatus.APPROVED,
        is_active=False,
    )

    for hidden in (pending, inactive):
        with pytest.raises(HTTPException) as exc:
            save_favourite_station(db_session, user=driver, station_id=hidden.id)
        assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc_op:
        save_favourite_station(db_session, user=operator, station_id=approved.id)
    assert exc_op.value.status_code == 403


def test_deactivated_favourite_hidden_from_list_but_still_removable(db_session):
    driver = _make_user(
        db_session,
        name="Driver Cleanup",
        email="drv.clean@example.com",
        phone="+919900001105",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op Cleanup",
        email="op.clean@example.com",
        phone="+919900001106",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator, name="Temp Active Hub")
    save_favourite_station(db_session, user=driver, station_id=station.id)

    # Station is deactivated later
    station.is_active = False
    db_session.commit()

    assert list_favourite_stations(db_session, user=driver).total == 0
    removed = remove_favourite_station(db_session, user=driver, station_id=station.id)
    assert removed.is_favourite is False


# ==============================================================================
# Integration / API Tests: STC-F2-14
# ==============================================================================


def test_api_favourite_stations_contract_routes_save_list_remove(client, db_session):
    driver = _make_user(
        db_session,
        name="API Driver",
        email="api.drv@example.com",
        phone="+919900002201",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="API Operator",
        email="api.op@example.com",
        phone="+919900002202",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)

    # 1. Save via POST /api/v1/stations/favourite-stations
    res_save = client.post(
        "/api/v1/stations/favourite-stations",
        json={"station_id": station.id},
        headers=_auth_header(driver),
    )
    assert res_save.status_code == 201
    save_payload = res_save.json()
    assert save_payload["is_favourite"] is True
    assert save_payload["station_id"] == station.id
    assert save_payload["favourite"]["name"] == "Metro EV Hub"
    assert save_payload["favourite"]["price_per_kwh"] == 14.5
    assert save_payload["favourite"]["availability_marker"]["color_code"] == "green"

    # 2. List via GET /api/v1/stations/favourite-stations with coordinates
    res_list = client.get(
        "/api/v1/stations/favourite-stations?latitude=12.9816&longitude=77.5946",
        headers=_auth_header(driver),
    )
    assert res_list.status_code == 200
    list_payload = res_list.json()
    assert list_payload["total"] == 1
    assert len(list_payload["stations"]) == 1
    assert list_payload["stations"][0]["station_id"] == station.id
    assert list_payload["stations"][0]["distance_km"] > 0

    # 3. Duplicate save remains idempotent
    res_dup = client.post(
        "/api/v1/stations/favourite-stations",
        json={"station_id": station.id},
        headers=_auth_header(driver),
    )
    assert res_dup.status_code == 201
    assert client.get(
        "/api/v1/stations/favourite-stations",
        headers=_auth_header(driver),
    ).json()["total"] == 1

    # 4. Remove via DELETE /api/v1/stations/favourite-stations?station_id=...
    res_del = client.delete(
        f"/api/v1/stations/favourite-stations?station_id={station.id}",
        headers=_auth_header(driver),
    )
    assert res_del.status_code == 200
    assert res_del.json()["is_favourite"] is False

    # 5. Verify list is empty after removal
    assert client.get(
        "/api/v1/stations/favourite-stations",
        headers=_auth_header(driver),
    ).json()["total"] == 0


def test_api_favourite_path_aliases_and_driver_isolation(client, db_session):
    driver_a = _make_user(
        db_session,
        name="Driver A",
        email="driver.a.fav@example.com",
        phone="+919900003301",
        role=UserRole.DRIVER,
    )
    driver_b = _make_user(
        db_session,
        name="Driver B",
        email="driver.b.fav@example.com",
        phone="+919900003302",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Op Multi",
        email="op.multi@example.com",
        phone="+919900003303",
        role=UserRole.OPERATOR,
    )
    station = _seed_station(db_session, operator)

    # Driver A saves via path alias
    res_add = client.post(
        f"/api/v1/stations/{station.id}/favourite",
        headers=_auth_header(driver_a),
    )
    assert res_add.status_code == 201

    # Driver B's list does NOT expose Driver A's favourites
    res_b_list = client.get(
        "/api/v1/stations/favourite-stations",
        headers=_auth_header(driver_b),
    )
    assert res_b_list.status_code == 200
    assert res_b_list.json()["total"] == 0

    # Driver B cannot remove Driver A's favourite
    res_b_del = client.delete(
        f"/api/v1/stations/{station.id}/favourite",
        headers=_auth_header(driver_b),
    )
    assert res_b_del.status_code == 404

    # Driver A's favourite remains intact and can be deleted by Driver A
    assert client.get(
        "/api/v1/stations/favourite-stations",
        headers=_auth_header(driver_a),
    ).json()["total"] == 1

    res_a_del = client.delete(
        f"/api/v1/stations/{station.id}/favourite",
        headers=_auth_header(driver_a),
    )
    assert res_a_del.status_code == 200
    assert res_a_del.json()["is_favourite"] is False


def test_api_favourite_auth_rbac_not_found_and_validation_errors(client, db_session):
    driver = _make_user(
        db_session,
        name="Validation Driver",
        email="val.drv@example.com",
        phone="+919900004401",
        role=UserRole.DRIVER,
    )
    operator = _make_user(
        db_session,
        name="Blocked Op",
        email="blk.op@example.com",
        phone="+919900004402",
        role=UserRole.OPERATOR,
    )

    # Unauthenticated -> 401
    assert client.get("/api/v1/stations/favourite-stations").status_code == 401
    assert (
        client.post("/api/v1/stations/favourite-stations", json={"station_id": 1}).status_code
        == 401
    )
    assert (
        client.delete("/api/v1/stations/favourite-stations?station_id=1").status_code == 401
    )

    # Operator role denied -> 403
    assert (
        client.get(
            "/api/v1/stations/favourite-stations", headers=_auth_header(operator)
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/v1/stations/favourite-stations",
            json={"station_id": 1},
            headers=_auth_header(operator),
        ).status_code
        == 403
    )
    assert (
        client.delete(
            "/api/v1/stations/favourite-stations?station_id=1",
            headers=_auth_header(operator),
        ).status_code
        == 403
    )

    # Missing station -> 404
    assert (
        client.post(
            "/api/v1/stations/favourite-stations",
            json={"station_id": 99999},
            headers=_auth_header(driver),
        ).status_code
        == 404
    )

    # Invalid station_id or unpaired coords -> 422
    assert (
        client.post(
            "/api/v1/stations/favourite-stations",
            json={"station_id": 0},
            headers=_auth_header(driver),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/stations/0/favourite",
            headers=_auth_header(driver),
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/stations/favourite-stations?latitude=12.97",
            headers=_auth_header(driver),
        ).status_code
        == 422
    )

