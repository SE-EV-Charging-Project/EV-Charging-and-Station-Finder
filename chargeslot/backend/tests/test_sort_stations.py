"""
Unit and Integration Tests for Station Sorting
Requirement: REQ-F2-10 (Sort stations)
Story ID: CS19-036
Test Case ID: TC-F2-10
System Test Case ID: STC-F2-10
Architecture Ref: discovery/sorting.py / GET & POST /api/v1/stations/sort-stations
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
from app.schemas.discovery import NearbyStationItem, StationSortBy, SortOrder
from app.discovery.sorting import (
    validate_sort_params,
    sort_station_items,
    search_and_sort_stations,
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
    user = User(
        name="Driver Sort Test",
        email="driver.sort@example.com",
        phone="+919876543210",
        hashed_password=hash_password("DriverPass123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def operator_user(db_session: Session) -> User:
    user = User(
        name="Operator Sort Test",
        email="operator.sort@example.com",
        phone="+919876543211",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sample_station_items() -> list[NearbyStationItem]:
    """
    Creates a distinct set of in-memory station items to test sorting algorithms:
    - Station 1: Distance 10.0 km, Price 12.0 INR, Power 50 kW, Available 3/3
    - Station 2: Distance 2.0 km, Price 18.0 INR, Power 150 kW, Available 1/2
    - Station 3: Distance 5.0 km, Price 15.0 INR, Power 22 kW, Available 0/2
    - Station 4: Distance 1.0 km, Price None, Power 100 kW, Available 2/4
    """
    return [
        NearbyStationItem(
            id=1,
            name="Alpha Hub",
            address="100 Feet Rd",
            latitude=12.9716,
            longitude=77.5946,
            distance_km=10.0,
            operating_hours="24 hours",
            amenities=["WiFi"],
            contact_phone="+919876500001",
            status="approved",
            is_active=True,
            total_chargers=1,
            total_connectors=3,
            available_connectors=3,
            connector_types=["CCS2"],
            max_power_kw=50.0,
            price_per_kwh=12.0,
            color_code="green",
            status_label="Available",
            badge_text="3/3 Available",
        ),
        NearbyStationItem(
            id=2,
            name="Beta Fast",
            address="Indiranagar",
            latitude=12.9780,
            longitude=77.6400,
            distance_km=2.0,
            operating_hours="24 hours",
            amenities=["Cafe", "Restroom"],
            contact_phone="+919876500002",
            status="approved",
            is_active=True,
            total_chargers=2,
            total_connectors=2,
            available_connectors=1,
            connector_types=["CCS2", "CHAdeMO"],
            max_power_kw=150.0,
            price_per_kwh=18.0,
            color_code="amber",
            status_label="Partially Available",
            badge_text="1/2 Available",
        ),
        NearbyStationItem(
            id=3,
            name="Gamma Slow",
            address="Koramangala",
            latitude=12.9352,
            longitude=77.6245,
            distance_km=5.0,
            operating_hours="08:00-22:00",
            amenities=["Parking"],
            contact_phone="+919876500003",
            status="approved",
            is_active=True,
            total_chargers=1,
            total_connectors=2,
            available_connectors=0,
            connector_types=["Type 2"],
            max_power_kw=22.0,
            price_per_kwh=15.0,
            color_code="red",
            status_label="Occupied",
            badge_text="0/2 Occupied",
        ),
        NearbyStationItem(
            id=4,
            name="Delta Mixed",
            address="MG Road",
            latitude=12.9750,
            longitude=77.6000,
            distance_km=1.0,
            operating_hours="24 hours",
            amenities=[],
            contact_phone="+919876500004",
            status="approved",
            is_active=True,
            total_chargers=2,
            total_connectors=4,
            available_connectors=2,
            connector_types=["CCS2"],
            max_power_kw=100.0,
            price_per_kwh=None,
            color_code="amber",
            status_label="Partially Available",
            badge_text="2/4 Available",
        ),
    ]


@pytest.fixture
def db_stations_suite(db_session: Session, operator_user: User):
    """
    Creates a database fixture with diverse stations to verify end-to-end API sorting (REQ-F2-10):
    1. Station A (Close, Cheap, Low Power, Fully Available):
       - Distance: ~1.1 km from (12.9716, 77.5946)
       - Price: 10.0 INR/kWh
       - Power: 30 kW
       - Available: 2/2
    2. Station B (Medium Distance, Moderate Price, Ultra Fast, Partially Available):
       - Distance: ~4.5 km
       - Price: 16.0 INR/kWh
       - Power: 120 kW
       - Available: 1/2
    3. Station C (Far, Expensive, High Power, Fully Occupied):
       - Distance: ~8.0 km
       - Price: 22.0 INR/kWh
       - Power: 60 kW
       - Available: 0/2
    4. Station D (Inactive - Must be excluded by visibility gate REQ-F2-03):
       - is_active: False
    5. Station E (Pending - Must be excluded by visibility gate REQ-F2-03):
       - status: PENDING
    """
    # 1. Station A
    st_a = Station(
        operator_id=operator_user.id,
        name="Station A - Budget Friendly",
        address="Near MG Road",
        latitude=12.9750,
        longitude=77.6040,
        amenities=["WiFi"],
        operating_hours="24 hours",
        contact_phone="+919876510001",
        price_per_kwh=10.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(st_a)
    db_session.flush()

    ch_a = Charger(
        station_id=st_a.id,
        name="Charger A1",
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="GTW-A1",
        is_active=True,
    )
    db_session.add(ch_a)
    db_session.flush()

    for i in range(2):
        db_session.add(
            Connector(
                charger_id=ch_a.id,
                connector_type=ConnectorType.CCS2,
                status=ConnectorStatus.AVAILABLE,
            )
        )

    # 2. Station B
    st_b = Station(
        operator_id=operator_user.id,
        name="Station B - Ultra Fast",
        address="Indiranagar 100ft",
        latitude=12.9780,
        longitude=77.6350,
        amenities=["Cafe", "Restroom"],
        operating_hours="24 hours",
        contact_phone="+919876510002",
        price_per_kwh=16.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(st_b)
    db_session.flush()

    ch_b = Charger(
        station_id=st_b.id,
        name="Charger B1",
        power_kw=120.0,
        current_type=CurrentType.DC,
        gateway_id="GTW-B1",
        is_active=True,
    )
    db_session.add(ch_b)
    db_session.flush()

    db_session.add(
        Connector(
            charger_id=ch_b.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    db_session.add(
        Connector(
            charger_id=ch_b.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.OCCUPIED,
        )
    )

    # 3. Station C
    st_c = Station(
        operator_id=operator_user.id,
        name="Station C - Far Premium",
        address="Whitefield Outer",
        latitude=12.9800,
        longitude=77.6700,
        amenities=["Lounge"],
        operating_hours="24 hours",
        contact_phone="+919876510003",
        price_per_kwh=22.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(st_c)
    db_session.flush()

    ch_c = Charger(
        station_id=st_c.id,
        name="Charger C1",
        power_kw=60.0,
        current_type=CurrentType.DC,
        gateway_id="GTW-C1",
        is_active=True,
    )
    db_session.add(ch_c)
    db_session.flush()

    for i in range(2):
        db_session.add(
            Connector(
                charger_id=ch_c.id,
                connector_type=ConnectorType.CCS2,
                status=ConnectorStatus.OCCUPIED,
            )
        )

    # 4. Station D (Inactive)
    st_d = Station(
        operator_id=operator_user.id,
        name="Station D - Inactive",
        address="Ghost Rd",
        latitude=12.9716,
        longitude=77.5946,
        amenities=[],
        operating_hours="24 hours",
        contact_phone="+919876510004",
        price_per_kwh=5.0,
        status=StationStatus.APPROVED,
        is_active=False,
    )
    db_session.add(st_d)

    # 5. Station E (Pending Approval)
    st_e = Station(
        operator_id=operator_user.id,
        name="Station E - Pending",
        address="Approval St",
        latitude=12.9716,
        longitude=77.5946,
        amenities=[],
        operating_hours="24 hours",
        contact_phone="+919876510005",
        price_per_kwh=5.0,
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(st_e)

    db_session.commit()
    return {"a": st_a, "b": st_b, "c": st_c, "d": st_d, "e": st_e}


# =========================================================================
# Unit Tests (TC-F2-10)
# =========================================================================

def test_tc_f2_10_validate_sort_params_valid():
    """Verify that valid sort fields resolve with correct defaults."""
    # Distance defaults to ascending (closest first)
    by, order = validate_sort_params("distance")
    assert by == StationSortBy.DISTANCE
    assert order == SortOrder.ASC

    # Price defaults to ascending (cheapest first)
    by, order = validate_sort_params("price")
    assert by == StationSortBy.PRICE
    assert order == SortOrder.ASC

    # Power defaults to descending (highest power first)
    by, order = validate_sort_params("power")
    assert by == StationSortBy.POWER
    assert order == SortOrder.DESC

    # Availability defaults to descending (most available first)
    by, order = validate_sort_params("availability")
    assert by == StationSortBy.AVAILABILITY
    assert order == SortOrder.DESC


def test_tc_f2_10_validate_sort_params_custom_order():
    """Verify that explicit sort orders override defaults."""
    by, order = validate_sort_params("distance", "desc")
    assert by == StationSortBy.DISTANCE
    assert order == SortOrder.DESC

    by, order = validate_sort_params("power", "asc")
    assert by == StationSortBy.POWER
    assert order == SortOrder.ASC


def test_tc_f2_10_validate_sort_params_invalid_field_raises_422():
    """Verify that invalid sort fields are rejected with 422."""
    with pytest.raises(Exception) as excinfo:
        validate_sort_params("color")
    assert "422" in str(excinfo.value)
    assert "Invalid sort field 'color'" in str(excinfo.value)


def test_tc_f2_10_validate_sort_params_invalid_order_raises_422():
    """Verify that invalid sort orders are rejected with 422."""
    with pytest.raises(Exception) as excinfo:
        validate_sort_params("distance", "sideways")
    assert "422" in str(excinfo.value)
    assert "Invalid sort order 'sideways'" in str(excinfo.value)


def test_tc_f2_10_sort_by_distance(sample_station_items):
    """Verify sort by distance: closest first (asc) and farthest first (desc)."""
    # Ascending (default for distance)
    sorted_asc, by, order = sort_station_items(sample_station_items, "distance")
    assert order == "asc"
    distances = [s.distance_km for s in sorted_asc]
    assert distances == [1.0, 2.0, 5.0, 10.0]
    assert sorted_asc[0].id == 4  # 1.0 km

    # Descending
    sorted_desc, by, order = sort_station_items(sample_station_items, "distance", "desc")
    assert order == "desc"
    distances = [s.distance_km for s in sorted_desc]
    assert distances == [10.0, 5.0, 2.0, 1.0]
    assert sorted_desc[0].id == 1  # 10.0 km


def test_tc_f2_10_sort_by_price(sample_station_items):
    """Verify sort by price per kWh: cheapest first (asc), None handled gracefully."""
    # Ascending (cheapest first)
    sorted_asc, by, order = sort_station_items(sample_station_items, "price")
    assert order == "asc"
    # Station 1 (12.0), Station 3 (15.0), Station 2 (18.0), Station 4 (None at end)
    assert [s.id for s in sorted_asc] == [1, 3, 2, 4]
    assert sorted_asc[0].price_per_kwh == 12.0
    assert sorted_asc[-1].price_per_kwh is None

    # Descending (most expensive first)
    sorted_desc, by, order = sort_station_items(sample_station_items, "price", "desc")
    assert order == "desc"
    # Station 2 (18.0), Station 3 (15.0), Station 1 (12.0), Station 4 (None at end)
    assert [s.id for s in sorted_desc] == [2, 3, 1, 4]


def test_tc_f2_10_sort_by_power(sample_station_items):
    """Verify sort by power rating: highest power first (desc) and lowest power first (asc)."""
    # Descending (default for power)
    sorted_desc, by, order = sort_station_items(sample_station_items, "power")
    assert order == "desc"
    # 150 kW (St 2), 100 kW (St 4), 50 kW (St 1), 22 kW (St 3)
    powers = [s.max_power_kw for s in sorted_desc]
    assert powers == [150.0, 100.0, 50.0, 22.0]
    assert [s.id for s in sorted_desc] == [2, 4, 1, 3]

    # Ascending
    sorted_asc, by, order = sort_station_items(sample_station_items, "power", "asc")
    assert order == "asc"
    powers = [s.max_power_kw for s in sorted_asc]
    assert powers == [22.0, 50.0, 100.0, 150.0]
    assert [s.id for s in sorted_asc] == [3, 1, 4, 2]


def test_tc_f2_10_sort_by_availability(sample_station_items):
    """Verify sort by availability: most available first (desc)."""
    sorted_desc, by, order = sort_station_items(sample_station_items, "availability")
    assert order == "desc"
    # Available connectors: 3 (St 1), 2 (St 4), 1 (St 2), 0 (St 3)
    avail = [s.available_connectors for s in sorted_desc]
    assert avail == [3, 2, 1, 0]
    assert [s.id for s in sorted_desc] == [1, 4, 2, 3]


# =========================================================================
# Integration & API Tests (REQ-F2-10 / TC-F2-10)
# =========================================================================

def test_tc_f2_10_api_auth_required(client: TestClient):
    """Unauthenticated sort request is rejected with 401."""
    resp = client.get("/api/v1/stations/sort-stations?sort_by=distance")
    assert resp.status_code == 401


def test_tc_f2_10_api_visibility_gate(
    client: TestClient, db_stations_suite, driver_user: User
):
    """
    Visibility gate (REQ-F2-03): Inactive (Station D) and Pending (Station E)
    must never be returned in sort results.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/sort-stations?sort_by=distance",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    station_names = [s["name"] for s in data["stations"]]
    assert not any("Inactive" in name for name in station_names)
    assert not any("Pending" in name for name in station_names)


def test_tc_f2_10_api_sort_by_distance_get(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test GET /stations/sort-stations sorted by distance from driver coordinates."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Driver at Bangalore center (12.9716, 77.5946)
    resp = client.get(
        "/api/v1/stations/sort-stations?sort_by=distance&latitude=12.9716&longitude=77.5946&radius_km=20.0",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sort_by"] == "distance"
    assert data["sort_order"] == "asc"
    stations = data["stations"]
    assert len(stations) == 3
    # Station A is closest (~1.1 km), Station B is medium (~4.5 km), Station C is far (~8.2 km)
    assert "Station A" in stations[0]["name"]
    assert "Station B" in stations[1]["name"]
    assert "Station C" in stations[2]["name"]
    assert stations[0]["distance_km"] < stations[1]["distance_km"] < stations[2]["distance_km"]


def test_tc_f2_10_api_sort_by_price_post(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test POST /stations/sort-stations sorted by price (asc: cheapest first)."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "sort_by": "price",
        "sort_order": "asc",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "radius_km": 20.0,
    }
    resp = client.post(
        "/api/v1/stations/sort-stations",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sort_by"] == "price"
    assert data["sort_order"] == "asc"
    stations = data["stations"]
    # Station A: 10 INR, Station B: 16 INR, Station C: 22 INR
    assert stations[0]["price_per_kwh"] == 10.0
    assert stations[1]["price_per_kwh"] == 16.0
    assert stations[2]["price_per_kwh"] == 22.0


def test_tc_f2_10_api_sort_by_power_post(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test POST /stations/sort-stations sorted by power (desc: fastest charger first)."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "sort_by": "power",
        "sort_order": "desc",
        "latitude": 12.9716,
        "longitude": 77.5946,
        "radius_km": 20.0,
    }
    resp = client.post(
        "/api/v1/stations/sort-stations",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sort_by"] == "power"
    assert data["sort_order"] == "desc"
    stations = data["stations"]
    # Station B: 120 kW, Station C: 60 kW, Station A: 30 kW
    assert stations[0]["max_power_kw"] == 120.0
    assert stations[1]["max_power_kw"] == 60.0
    assert stations[2]["max_power_kw"] == 30.0


def test_tc_f2_10_api_sort_by_availability_get(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test GET /stations/sort-stations sorted by availability (desc: most available first)."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/sort-stations?sort_by=availability&latitude=12.9716&longitude=77.5946&radius_km=20.0",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["sort_by"] == "availability"
    assert data["sort_order"] == "desc"
    stations = data["stations"]
    # Station A: 2 available, Station B: 1 available, Station C: 0 available
    assert stations[0]["available_connectors"] == 2
    assert stations[1]["available_connectors"] == 1
    assert stations[2]["available_connectors"] == 0


def test_tc_f2_10_api_invalid_sort_by_rejected(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test that invalid sort_by is rejected with 422."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/sort-stations?sort_by=rating",
        headers=headers,
    )
    assert resp.status_code == 422
    assert "Invalid sort field 'rating'" in resp.text


def test_tc_f2_10_api_pagination(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Test limit and offset pagination on sorted results."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/sort-stations?sort_by=distance&latitude=12.9716&longitude=77.5946&radius_km=20.0&limit=1&offset=0",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 3
    assert len(data["stations"]) == 1
    assert "Station A" in data["stations"][0]["name"]

    # Page 2
    resp2 = client.get(
        "/api/v1/stations/sort-stations?sort_by=distance&latitude=12.9716&longitude=77.5946&radius_km=20.0&limit=1&offset=1",
        headers=headers,
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert len(data2["stations"]) == 1
    assert "Station B" in data2["stations"][0]["name"]


# =========================================================================
# System Test Case (STC-F2-10)
# =========================================================================

def test_stc_f2_10_end_to_end_driver_sort_workflow(
    client: TestClient, db_stations_suite, driver_user: User
):
    """
    STC-F2-10: End-to-end system test verifying driver sorting experience:
    1. Driver opens discovery with center coordinates and sorts by distance (nearest first).
    2. Driver toggles sort to power (ultra-fast charging priority for low-battery emergency).
    3. Driver toggles sort to price (budget optimization for overnight recharge).
    4. Driver verifies combined filtering and sorting (/filter-stations with sort_by=price).
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Distance sorting
    r_dist = client.get(
        "/api/v1/stations/sort-stations?sort_by=distance&latitude=12.9716&longitude=77.5946&radius_km=15.0",
        headers=headers,
    )
    assert r_dist.status_code == 200
    assert r_dist.json()["stations"][0]["name"] == "Station A - Budget Friendly"

    # Step 2: Emergency power sorting
    r_power = client.get(
        "/api/v1/stations/sort-stations?sort_by=power&latitude=12.9716&longitude=77.5946&radius_km=15.0",
        headers=headers,
    )
    assert r_power.status_code == 200
    assert r_power.json()["stations"][0]["name"] == "Station B - Ultra Fast"
    assert r_power.json()["stations"][0]["max_power_kw"] == 120.0

    # Step 3: Budget price sorting
    r_price = client.get(
        "/api/v1/stations/sort-stations?sort_by=price&latitude=12.9716&longitude=77.5946&radius_km=15.0",
        headers=headers,
    )
    assert r_price.status_code == 200
    assert r_price.json()["stations"][0]["price_per_kwh"] == 10.0

    # Step 4: Combined Filter and Sort
    r_filtered = client.get(
        "/api/v1/stations/filter-stations?available_now=true&sort_by=price&latitude=12.9716&longitude=77.5946",
        headers=headers,
    )
    assert r_filtered.status_code == 200
    data_filt = r_filtered.json()
    # Station C has 0 available, so only Station A (10 INR) and Station B (16 INR) match
    assert data_filt["total"] == 2
    assert data_filt["stations"][0]["price_per_kwh"] == 10.0
    assert data_filt["stations"][1]["price_per_kwh"] == 16.0

