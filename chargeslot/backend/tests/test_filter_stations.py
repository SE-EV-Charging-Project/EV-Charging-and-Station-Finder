"""
Unit and Integration Tests for Station Filtering
Requirement: REQ-F2-09 (Filter stations)
Story ID: CS19-035
Test Case ID: TC-F2-09
System Test Case ID: STC-F2-09
Architecture Ref: discovery/filters.py / GET & POST /api/v1/stations/filter-stations
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import Vehicle, ConnectorType
from app.utils.security import hash_password, create_access_token
from app.discovery.filters import apply_station_filters
from app.services.discovery_service import DiscoveryService


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_a(db_session: Session) -> User:
    d = User(
        name="Driver Alpha",
        email="driver.alpha.filters@example.com",
        phone="+919876580001",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    return d


@pytest.fixture
def driver_b(db_session: Session) -> User:
    d = User(
        name="Driver Beta",
        email="driver.beta.filters@example.com",
        phone="+919876580002",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(d)
    db_session.commit()
    db_session.refresh(d)
    return d


@pytest.fixture
def vehicle_ccs2(db_session: Session, driver_a: User) -> Vehicle:
    v = Vehicle(
        user_id=driver_a.id,
        make="Tata",
        model="Nexon EV",
        battery_kwh=40.5,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        is_default=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def vehicle_type2(db_session: Session, driver_a: User) -> Vehicle:
    v = Vehicle(
        user_id=driver_a.id,
        make="Mahindra",
        model="XUV400",
        battery_kwh=39.4,
        connector_type=ConnectorType.TYPE_2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=16.0,
        is_default=False,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def vehicle_other_driver(db_session: Session, driver_b: User) -> Vehicle:
    v = Vehicle(
        user_id=driver_b.id,
        make="MG",
        model="ZS EV",
        battery_kwh=50.3,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.4,
        max_dc_kw=80.0,
        consumption_kwh_100km=17.0,
        is_default=True,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def operator_user(db_session: Session) -> User:
    op = User(
        name="Filter Operator",
        email="operator.filters@example.com",
        phone="+919876580003",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="GridCharge Ltd",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op)
    db_session.commit()
    db_session.refresh(op)
    return op


@pytest.fixture
def filter_test_stations(db_session: Session, operator_user: User):
    """
    Creates multiple stations with distinct amenities, power ratings, connector types, and availability:
    - Station 1: CCS2 + CHAdeMO, 150 kW DC, Available now (2 free), Amenities: ["WiFi", "Cafe", "Restroom"]
    - Station 2: Type 2 AC, 22 kW AC, Available now (1 free), Amenities: ["Restroom"]
    - Station 3: CCS2 DC, 60 kW DC, Busy now (0 free), Amenities: ["WiFi", "Dining"]
    - Station 4: GB/T DC, 30 kW DC, Available now (1 free), Amenities: []
    - Station 5: Pending approval (MUST be excluded)
    """
    # Station 1: Ultra-fast DC hub
    s1 = Station(
        operator_id=operator_user.id,
        name="High Power Highway Hub",
        address="100 Highway Express, Bengaluru",
        contact_phone="+919876580010",
        latitude=12.9716,
        longitude=77.5946,
        amenities=["WiFi", "Cafe", "Restroom"],
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s1)
    db_session.flush()
    c1 = Charger(station_id=s1.id, power_kw=150.0, current_type=CurrentType.DC, gateway_id="GW-F-01", is_active=True)
    db_session.add(c1)
    db_session.flush()
    db_session.add_all([
        Connector(charger_id=c1.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE),
        Connector(charger_id=c1.id, connector_type=ConnectorType.CHADEMO, status=ConnectorStatus.AVAILABLE),
    ])

    # Station 2: Slow AC destination hub
    s2 = Station(
        operator_id=operator_user.id,
        name="Mall Slow AC Point",
        address="200 City Mall, Bengaluru",
        contact_phone="+919876580020",
        latitude=12.9750,
        longitude=77.6000,
        amenities=["Restroom"],
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s2)
    db_session.flush()
    c2 = Charger(station_id=s2.id, power_kw=22.0, current_type=CurrentType.AC, gateway_id="GW-F-02", is_active=True)
    db_session.add(c2)
    db_session.flush()
    db_session.add(Connector(charger_id=c2.id, connector_type=ConnectorType.TYPE_2, status=ConnectorStatus.AVAILABLE))

    # Station 3: Busy fast charger
    s3 = Station(
        operator_id=operator_user.id,
        name="Downtown Busy Fast Point",
        address="300 Downtown Lane, Bengaluru",
        contact_phone="+919876580030",
        latitude=12.9800,
        longitude=77.6100,
        amenities=["WiFi", "Dining"],
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s3)
    db_session.flush()
    c3 = Charger(station_id=s3.id, power_kw=60.0, current_type=CurrentType.DC, gateway_id="GW-F-03", is_active=True)
    db_session.add(c3)
    db_session.flush()
    db_session.add(Connector(charger_id=c3.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.OCCUPIED))

    # Station 4: GB/T fleet station
    s4 = Station(
        operator_id=operator_user.id,
        name="Fleet Depot GB/T",
        address="400 Depot Road, Bengaluru",
        contact_phone="+919876580040",
        latitude=12.9850,
        longitude=77.6200,
        amenities=[],
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s4)
    db_session.flush()
    c4 = Charger(station_id=s4.id, power_kw=30.0, current_type=CurrentType.DC, gateway_id="GW-F-04", is_active=True)
    db_session.add(c4)
    db_session.flush()
    db_session.add(Connector(charger_id=c4.id, connector_type=ConnectorType.GBT, status=ConnectorStatus.AVAILABLE))

    # Station 5: Unapproved station (MUST be excluded)
    s5 = Station(
        operator_id=operator_user.id,
        name="Unapproved Station",
        address="500 Ghost Street, Bengaluru",
        contact_phone="+919876580050",
        latitude=12.9716,
        longitude=77.5946,
        amenities=["WiFi", "Cafe"],
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(s5)

    db_session.commit()
    return {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5}


# =========================================================================
# TC-F2-09: Filtering Acceptance Tests
# =========================================================================

def test_tc_f2_09_filter_by_connector_type(
    client: TestClient,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Filtering by connector_types returns only stations with matching plug.
    """
    token = make_token(driver_a)

    # 1. Filter by CHAdeMO: only Station 1 has CHAdeMO
    res_ch = client.get(
        "/api/v1/stations/filter-stations?connector_types=CHAdeMO",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_ch.status_code == 200
    names = [s["name"] for s in res_ch.json()["stations"]]
    assert names == ["High Power Highway Hub"]

    # 2. Filter by Type 2: only Station 2 has Type 2
    res_t2 = client.get(
        "/api/v1/stations/filter-stations?connector_types=Type 2",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_t2.status_code == 200
    names_t2 = [s["name"] for s in res_t2.json()["stations"]]
    assert names_t2 == ["Mall Slow AC Point"]


def test_tc_f2_09_filter_by_minimum_power(
    client: TestClient,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Filter by minimum power (kW).
    min_power_kw=100.0 returns only stations with >= 100 kW (Station 1 has 150 kW).
    """
    token = make_token(driver_a)

    res = client.get(
        "/api/v1/stations/filter-stations?min_power_kw=100.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    stations = res.json()["stations"]
    assert len(stations) == 1
    assert stations[0]["name"] == "High Power Highway Hub"
    assert stations[0]["max_power_kw"] == 150.0


def test_tc_f2_09_filter_by_availability_now(
    client: TestClient,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Filter by available_now=true excludes fully occupied/busy stations (Station 3).
    """
    token = make_token(driver_a)

    res = client.get(
        "/api/v1/stations/filter-stations?available_now=true",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    names = [s["name"] for s in res.json()["stations"]]
    assert "High Power Highway Hub" in names
    assert "Mall Slow AC Point" in names
    assert "Fleet Depot GB/T" in names
    assert "Downtown Busy Fast Point" not in names  # Occupied


def test_tc_f2_09_filter_by_amenities(
    client: TestClient,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Filter by amenities (WiFi and Cafe). Only Station 1 has both.
    """
    token = make_token(driver_a)

    res = client.get(
        "/api/v1/stations/filter-stations?amenities=WiFi&amenities=Cafe",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    names = [s["name"] for s in res.json()["stations"]]
    assert names == ["High Power Highway Hub"]


def test_tc_f2_09_filter_by_vehicle_compatibility(
    client: TestClient,
    driver_a: User,
    vehicle_type2: Vehicle,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Filter stations compatible with driver's selected vehicle.
    vehicle_type2 uses Type 2 connector -> only Station 2 matches.
    """
    token = make_token(driver_a)

    res = client.get(
        f"/api/v1/stations/filter-stations?vehicle_id={vehicle_type2.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    names = [s["name"] for s in res.json()["stations"]]
    assert names == ["Mall Slow AC Point"]
    station = res.json()["stations"][0]
    assert station["vehicle_compatible_max_power_kw"] == 7.2


def test_tc_f3_05_vehicle_filter_caps_power_and_rejects_unsupported_current(
    client: TestClient,
    db_session: Session,
    driver_a: User,
    vehicle_ccs2: Vehicle,
    filter_test_stations: dict,
):
    token = make_token(driver_a)

    vehicle_ccs2.max_dc_kw = 25.0
    db_session.commit()
    response = client.get(
        f"/api/v1/stations/filter-stations?vehicle_id={vehicle_ccs2.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    stations = response.json()["stations"]
    assert {station["name"] for station in stations} == {
        "High Power Highway Hub",
        "Downtown Busy Fast Point",
    }
    assert all(
        station["vehicle_compatible_max_power_kw"] == 25.0
        for station in stations
    )

    vehicle_ccs2.max_dc_kw = 0.0
    db_session.commit()
    response = client.get(
        f"/api/v1/stations/filter-stations?vehicle_id={vehicle_ccs2.id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["stations"] == []


def test_tc_f2_09_combined_filters_via_post(
    client: TestClient,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    REQ-F2-09: Combined filter testing via POST /api/v1/stations/filter-stations:
    connector_types=["CCS2"], min_power_kw=50, available_now=True, amenities=["WiFi"]
    """
    token = make_token(driver_a)

    payload = {
        "connector_types": ["CCS2"],
        "min_power_kw": 50.0,
        "available_now": True,
        "amenities": ["WiFi"],
    }

    res = client.post(
        "/api/v1/stations/filter-stations",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["stations"][0]["name"] == "High Power Highway Hub"


# =========================================================================
# STC-F2-09: Security and Negative Validation Tests
# =========================================================================

def test_stc_f2_09_unauthenticated_request_rejected(client: TestClient):
    """
    Unauthenticated request must return 401 Unauthorized.
    """
    res = client.get("/api/v1/stations/filter-stations")
    assert res.status_code == 401


def test_stc_f2_09_cannot_filter_with_foreign_vehicle(
    client: TestClient,
    driver_a: User,
    vehicle_other_driver: Vehicle,
):
    """
    Driver A cannot use Driver B's vehicle ID for filtering (403 Forbidden per REQ-F1-26).
    """
    token = make_token(driver_a)

    res = client.get(
        f"/api/v1/stations/filter-stations?vehicle_id={vehicle_other_driver.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 403


def test_stc_f2_09_nonexistent_vehicle_rejected(
    client: TestClient,
    driver_a: User,
):
    """
    Non-existent vehicle ID returns 404 Not Found.
    """
    token = make_token(driver_a)

    res = client.get(
        "/api/v1/stations/filter-stations?vehicle_id=99999",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 404


def test_stc_f2_09_negative_power_rejected(
    client: TestClient,
    driver_a: User,
):
    """
    min_power_kw < 0 must return 422 Unprocessable Entity.
    """
    token = make_token(driver_a)

    res = client.get(
        "/api/v1/stations/filter-stations?min_power_kw=-10.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


# =========================================================================
# Direct Unit Tests for discovery/filters.py
# =========================================================================

def test_tc_f2_09_direct_unit_filters(
    db_session: Session,
    driver_a: User,
    filter_test_stations: dict,
):
    """
    Direct unit test for apply_station_filters with pagination and proximity.
    """
    total, applied, stations = apply_station_filters(
        db=db_session,
        user=driver_a,
        min_power_kw=20.0,
        available_now=True,
        limit=2,
        offset=0,
    )
    assert total >= 2
    assert len(stations) == 2
    assert applied["min_power_kw"] == 20.0
    assert applied["available_now"] is True

