"""
Unit and Integration Tests for Nearby Station Search
Requirement: REQ-F2-07 (Nearby station search)
Story ID: CS19-033
Test Case ID: TC-F2-07
System Test Case ID: STC-F2-07
Architecture Ref: discovery/search.py / GET /api/v1/stations/nearby-station-search
"""

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.utils.security import hash_password, create_access_token
from app.discovery.search import (
    haversine_distance,
    validate_search_params,
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
    MIN_SEARCH_RADIUS_KM,
    MAX_SEARCH_RADIUS_KM,
)
from app.services.discovery_service import DiscoveryService


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_user(db_session: Session) -> User:
    driver = User(
        name="Search Driver",
        email="driver.nearby@example.com",
        phone="+919876560001",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(driver)
    db_session.commit()
    db_session.refresh(driver)
    return driver


@pytest.fixture
def operator_user(db_session: Session) -> User:
    op = User(
        name="Station Operator",
        email="operator.nearby@example.com",
        phone="+919876560002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="EcoCharge Network",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op)
    db_session.commit()
    db_session.refresh(op)
    return op


@pytest.fixture
def test_stations(db_session: Session, operator_user: User):
    """
    Creates multiple stations at known distances from driver center (12.9716, 77.5946 - Bengaluru MG Road):
    - Station Close (~2 km): Approved, active, has 2 chargers (1 AC, 1 DC)
    - Station Medium (~8 km): Approved, active, has 1 DC charger
    - Station Far (~25 km): Approved, active, has 1 DC charger
    - Station Beyond (~60 km): Approved, active (outside 50 km max range)
    - Station Pending (~1 km): Pending approval (MUST be hidden from driver)
    - Station Inactive (~3 km): Inactive (MUST be hidden from driver)
    - Station Rejected (~4 km): Rejected (MUST be hidden from driver)
    """
    # 1. Close station: ~2.1 km away (Indiranagar: 12.9784, 77.6408 -> ~5 km / Cubbon Park 12.9763, 77.5929 -> ~0.5 km)
    s_close = Station(
        operator_id=operator_user.id,
        name="MG Road Supercharge Hub",
        address="10 MG Road, Bengaluru",
        latitude=12.9750,
        longitude=77.6050,
        amenities=["Restroom", "Cafe", "WiFi"],
        operating_hours="24 hours",
        contact_phone="+919876560010",
        contact_email="mgroad@ecocharge.com",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_close)
    db_session.flush()

    c1 = Charger(
        station_id=s_close.id,
        name="Supercharger 1",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id="GW-CLOSE-01",
        is_active=True,
        is_out_of_service=False,
    )
    c2 = Charger(
        station_id=s_close.id,
        name="AC Fast 2",
        power_kw=22.0,
        current_type=CurrentType.AC,
        gateway_id="GW-CLOSE-02",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add_all([c1, c2])
    db_session.flush()

    conn1 = Connector(charger_id=c1.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE)
    conn2 = Connector(charger_id=c1.id, connector_type=ConnectorType.CHADEMO, status=ConnectorStatus.OCCUPIED)
    conn3 = Connector(charger_id=c2.id, connector_type=ConnectorType.TYPE_2, status=ConnectorStatus.AVAILABLE)
    db_session.add_all([conn1, conn2, conn3])

    # 2. Medium station: ~8.5 km away (Whitefield road / Marathahalli: 12.9591, 77.6974)
    s_med = Station(
        operator_id=operator_user.id,
        name="Indiranagar East Point",
        address="200 100ft Road, Indiranagar",
        latitude=12.9784,
        longitude=77.6408,
        amenities=["Restroom"],
        operating_hours="06:00 - 23:00",
        contact_phone="+919876560020",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_med)
    db_session.flush()
    c_med = Charger(
        station_id=s_med.id,
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id="GW-MED-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(c_med)
    db_session.flush()
    db_session.add(Connector(charger_id=c_med.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))

    # 3. Far station: ~25 km away (Electronic City: 12.8399, 77.6770)
    s_far = Station(
        operator_id=operator_user.id,
        name="Electronic City Gateway",
        address="50 Phase 1, Electronic City",
        latitude=12.8399,
        longitude=77.6770,
        amenities=["Restroom", "Dining"],
        operating_hours="24 hours",
        contact_phone="+919876560030",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_far)
    db_session.flush()
    c_far = Charger(
        station_id=s_far.id,
        power_kw=150.0,
        current_type=CurrentType.DC,
        gateway_id="GW-FAR-01",
        is_active=True,
    )
    db_session.add(c_far)
    db_session.flush()
    db_session.add(Connector(charger_id=c_far.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))

    # 4. Beyond station: ~65 km away (Kolar: 13.1367, 78.1291)
    s_beyond = Station(
        operator_id=operator_user.id,
        name="Highway Oasis Kolar",
        address="NH 75, Kolar",
        latitude=13.1367,
        longitude=78.1291,
        amenities=["Food Court"],
        operating_hours="24 hours",
        contact_phone="+919876560040",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_beyond)

    # 5. Pending station: ~1 km away (MUST NOT be in discovery)
    s_pending = Station(
        operator_id=operator_user.id,
        name="Secret Pending Station",
        address="Closeby Pending Lane",
        latitude=12.9720,
        longitude=77.5960,
        contact_phone="+919876560050",
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(s_pending)

    # 6. Inactive station: ~1.5 km away (MUST NOT be in discovery)
    s_inactive = Station(
        operator_id=operator_user.id,
        name="Decommissioned Close Station",
        address="Inactive Boulevard",
        latitude=12.9730,
        longitude=77.5970,
        contact_phone="+919876560060",
        status=StationStatus.APPROVED,
        is_active=False,
    )
    db_session.add(s_inactive)

    # 7. Rejected station: ~1.8 km away (MUST NOT be in discovery)
    s_rejected = Station(
        operator_id=operator_user.id,
        name="Rejected Station Close",
        address="Rejected Way",
        latitude=12.9740,
        longitude=77.5980,
        contact_phone="+919876560070",
        status=StationStatus.REJECTED,
        is_active=True,
    )
    db_session.add(s_rejected)

    db_session.commit()
    return {
        "close": s_close,
        "med": s_med,
        "far": s_far,
        "beyond": s_beyond,
        "pending": s_pending,
        "inactive": s_inactive,
        "rejected": s_rejected,
    }


# =========================================================================
# TC-F2-07: Nearby Station Search Acceptance Tests
# =========================================================================

def test_tc_f2_07_default_radius_returns_nearby_stations_sorted_by_distance(
    client: TestClient,
    driver_user: User,
    test_stations: dict,
):
    """
    REQ-F2-07: Default radius 10 km.
    Stations within 10 km (Close and Medium) are returned, sorted by ascending distance.
    Stations outside 10 km (Far, Beyond) and non-approved/inactive stations are excluded.
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    # GET /api/v1/stations/nearby-station-search
    res = client.get(
        f"/api/v1/stations/nearby-station-search?latitude={lat}&longitude={lon}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["center_latitude"] == lat
    assert data["center_longitude"] == lon
    assert data["radius_km"] == 10.0
    assert data["total_found"] == 2

    stations = data["stations"]
    assert len(stations) == 2

    # Verify sorted ascending by distance
    assert stations[0]["name"] == "MG Road Supercharge Hub"
    assert stations[1]["name"] == "Indiranagar East Point"
    assert stations[0]["distance_km"] <= stations[1]["distance_km"]

    # Verify connector counts and metrics on closest station
    close_st = stations[0]
    assert close_st["total_chargers"] == 2
    assert close_st["total_connectors"] == 3
    assert close_st["available_connectors"] == 2  # 1 occupied
    assert close_st["max_power_kw"] == 60.0
    assert "CCS2" in close_st["connector_types"]
    assert "Type 2" in close_st["connector_types"]


def test_tc_f2_07_selectable_radius_expansion(
    client: TestClient,
    driver_user: User,
    test_stations: dict,
):
    """
    REQ-F2-07: Expanding radius to 30 km includes the Far station (~25 km away),
    while excluding the Beyond station (~65 km away).
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    res = client.get(
        f"/api/v1/stations/nearby-station-search?latitude={lat}&longitude={lon}&radius_km=30.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()

    assert data["radius_km"] == 30.0
    assert data["total_found"] == 3

    names = [s["name"] for s in data["stations"]]
    assert "MG Road Supercharge Hub" in names
    assert "Indiranagar East Point" in names
    assert "Electronic City Gateway" in names
    assert "Highway Oasis Kolar" not in names


def test_tc_f2_07_selectable_radius_narrowing(
    client: TestClient,
    driver_user: User,
    test_stations: dict,
):
    """
    REQ-F2-07: Narrowing radius to 2.5 km only returns the immediate station (~1.2 km away).
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    res = client.get(
        f"/api/v1/stations/nearby-station-search?latitude={lat}&longitude={lon}&radius_km=2.5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_found"] == 1
    assert data["stations"][0]["name"] == "MG Road Supercharge Hub"


def test_tc_f2_07_post_endpoint_parity(
    client: TestClient,
    driver_user: User,
    test_stations: dict,
):
    """
    Verify POST /api/v1/stations/nearby-station-search produces identical results
    to GET query parameters.
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    payload = {
        "latitude": lat,
        "longitude": lon,
        "radius_km": 10.0,
    }

    res = client.post(
        "/api/v1/stations/nearby-station-search",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["total_found"] == 2
    assert data["stations"][0]["name"] == "MG Road Supercharge Hub"


def test_tc_f2_07_hidden_stations_approval_gate_enforcement(
    client: TestClient,
    driver_user: User,
    test_stations: dict,
):
    """
    REQ-F2-03 & REQ-F2-07: Pending, rejected, and inactive stations MUST NEVER appear
    in driver discovery results even if they are situated immediately at the driver's coordinates.
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    res = client.get(
        f"/api/v1/stations/nearby-station-search?latitude={lat}&longitude={lon}&radius_km=50.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    names = [s["name"] for s in res.json()["stations"]]

    assert "Secret Pending Station" not in names
    assert "Decommissioned Close Station" not in names
    assert "Rejected Station Close" not in names


# =========================================================================
# Input Validation & Out-of-Range Rejections (REQ-F2-07 Range 1 to 50 km)
# =========================================================================

def test_tc_f2_07_radius_below_minimum_rejected(client: TestClient, driver_user: User):
    """
    Radius < 1.0 km must be rejected with 422 Unprocessable Entity.
    """
    token = make_token(driver_user)
    res = client.get(
        "/api/v1/stations/nearby-station-search?latitude=12.9716&longitude=77.5946&radius_km=0.5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


def test_tc_f2_07_radius_above_maximum_rejected(client: TestClient, driver_user: User):
    """
    Radius > 50.0 km must be rejected with 422 Unprocessable Entity.
    """
    token = make_token(driver_user)
    res = client.get(
        "/api/v1/stations/nearby-station-search?latitude=12.9716&longitude=77.5946&radius_km=50.1",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


def test_tc_f2_07_latitude_out_of_range_rejected(client: TestClient, driver_user: User):
    """
    Latitude out of [-90, 90] must be rejected with 422.
    """
    token = make_token(driver_user)
    res = client.get(
        "/api/v1/stations/nearby-station-search?latitude=95.0&longitude=77.5946",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


def test_tc_f2_07_longitude_out_of_range_rejected(client: TestClient, driver_user: User):
    """
    Longitude out of [-180, 180] must be rejected with 422.
    """
    token = make_token(driver_user)
    res = client.get(
        "/api/v1/stations/nearby-station-search?latitude=12.9716&longitude=185.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 422


# =========================================================================
# STC-F2-07: Security and System Testing
# =========================================================================

def test_stc_f2_07_unauthenticated_request_rejected(client: TestClient):
    """
    Unauthenticated request must return 401 Unauthorized.
    """
    res = client.get("/api/v1/stations/nearby-station-search?latitude=12.9716&longitude=77.5946")
    assert res.status_code == 401


# =========================================================================
# Direct Unit Tests: Haversine Algorithm and Discovery Service
# =========================================================================

def test_tc_f2_07_haversine_distance_calculations():
    """
    Tests mathematical accuracy of the Haversine great-circle distance algorithm.
    """
    # 1. Same point distance is 0
    assert haversine_distance(12.9716, 77.5946, 12.9716, 77.5946) == 0.0

    # 2. Known distance: Bengaluru MG Road (12.9716, 77.5946) to Whitefield (12.9698, 77.7499)
    # Distance is approx 16.8 km
    dist = haversine_distance(12.9716, 77.5946, 12.9698, 77.7499)
    assert 16.0 < dist < 17.5

    # 3. Known distance: Bengaluru to Mysuru (approx 125 to 135 km)
    dist_mys = haversine_distance(12.9716, 77.5946, 12.2958, 76.6394)
    assert 120.0 < dist_mys < 140.0


def test_tc_f2_07_validate_search_params_unit():
    """
    Direct unit tests for validate_search_params boundaries.
    """
    # Valid boundaries
    validate_search_params(0.0, 0.0, 1.0)
    validate_search_params(-90.0, -180.0, 50.0)
    validate_search_params(90.0, 180.0, 25.0)

    # Invalid latitude
    with pytest.raises(Exception):
        validate_search_params(-90.1, 0.0, 10.0)
    with pytest.raises(Exception):
        validate_search_params(90.1, 0.0, 10.0)

    # Invalid longitude
    with pytest.raises(Exception):
        validate_search_params(0.0, -180.1, 10.0)
    with pytest.raises(Exception):
        validate_search_params(0.0, 180.1, 10.0)

    # Invalid radius
    with pytest.raises(Exception):
        validate_search_params(12.0, 77.0, 0.9)
    with pytest.raises(Exception):
        validate_search_params(12.0, 77.0, 50.1)


def test_tc_f2_07_service_direct_unit(db_session: Session, operator_user: User, test_stations: dict):
    """
    Direct unit test for DiscoveryService.get_nearby_stations.
    """
    res = DiscoveryService.get_nearby_stations(
        db=db_session,
        latitude=12.9716,
        longitude=77.5946,
        radius_km=10.0,
    )
    assert res.total_found == 2
    assert res.radius_km == 10.0
    assert len(res.stations) == 2
    assert res.stations[0].distance_km < res.stations[1].distance_km

