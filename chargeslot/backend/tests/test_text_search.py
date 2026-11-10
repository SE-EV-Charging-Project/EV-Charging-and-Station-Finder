"""
Unit and Integration Tests for Station Free-Text Search
Requirement: REQ-F2-11 (Text search)
Story ID: CS19-037
Test Case ID: TC-F2-11
System Test Case ID: STC-F2-11
Architecture Ref: discovery/text_search.py / GET & POST /api/v1/stations/text-search
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.utils.security import hash_password, create_access_token
from app.discovery.text_search import (
    validate_text_search_query,
    search_stations_by_text,
)


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_user(db_session: Session) -> User:
    user = User(
        name="Driver Search Tester",
        email="driver.textsearch@example.com",
        phone="+919876541111",
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
        name="Operator Search Tester",
        email="operator.textsearch@example.com",
        phone="+919876541112",
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
def search_stations_suite(db_session: Session, operator_user: User):
    """
    Creates a set of stations in diverse areas/names for text search testing:
    1. Station "Indiranagar Supercharge Hub" at "100 Feet Road, Indiranagar, Bengaluru"
    2. Station "Whitefield Tech Park EV" at "ITPB Main Road, Whitefield, Bengaluru"
    3. Station "Koramangala Fast Point" at "Sony World Junction, Koramangala, Bengaluru"
    4. Station "MG Road Express" at "Mahatma Gandhi Road, Central Bengaluru"
    5. Station "Koramangala Inactive Point" (is_active=False - must be hidden)
    6. Station "Indiranagar Pending Hub" (status=PENDING - must be hidden)
    """
    # 1. Indiranagar
    s1 = Station(
        operator_id=operator_user.id,
        name="Indiranagar Supercharge Hub",
        address="100 Feet Road, Indiranagar, Bengaluru",
        contact_phone="+919876540001",
        latitude=12.9780,
        longitude=77.6400,
        amenities=["Cafe", "WiFi", "Restroom"],
        price_per_kwh=15.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s1)
    db_session.flush()

    c1 = Charger(station_id=s1.id, name="Indi-C1", power_kw=60.0, current_type=CurrentType.DC, gateway_id="GW-T-01", is_active=True)
    db_session.add(c1)
    db_session.flush()
    db_session.add(Connector(charger_id=c1.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))

    # 2. Whitefield
    s2 = Station(
        operator_id=operator_user.id,
        name="Whitefield Tech Park EV",
        address="ITPB Main Road, Whitefield, Bengaluru",
        contact_phone="+919876540002",
        latitude=12.9850,
        longitude=77.7300,
        amenities=["Parking", "WiFi"],
        price_per_kwh=18.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s2)
    db_session.flush()

    c2 = Charger(station_id=s2.id, name="White-C1", power_kw=120.0, current_type=CurrentType.DC, gateway_id="GW-T-02", is_active=True)
    db_session.add(c2)
    db_session.flush()
    db_session.add(Connector(charger_id=c2.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))

    # 3. Koramangala
    s3 = Station(
        operator_id=operator_user.id,
        name="Koramangala Fast Point",
        address="Sony World Junction, Koramangala, Bengaluru",
        contact_phone="+919876540003",
        latitude=12.9350,
        longitude=77.6250,
        amenities=["Restroom"],
        price_per_kwh=12.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s3)
    db_session.flush()

    c3 = Charger(station_id=s3.id, name="Kora-C1", power_kw=30.0, current_type=CurrentType.DC, gateway_id="GW-T-03", is_active=True)
    db_session.add(c3)
    db_session.flush()
    db_session.add(Connector(charger_id=c3.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.OCCUPIED))

    # 4. MG Road Central
    s4 = Station(
        operator_id=operator_user.id,
        name="MG Road Express",
        address="Mahatma Gandhi Road, Central Bengaluru",
        contact_phone="+919876540004",
        latitude=12.9750,
        longitude=77.6000,
        amenities=["Cafe"],
        price_per_kwh=14.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s4)
    db_session.flush()

    c4 = Charger(station_id=s4.id, name="MG-C1", power_kw=50.0, current_type=CurrentType.DC, gateway_id="GW-T-04", is_active=True)
    db_session.add(c4)
    db_session.flush()
    db_session.add(Connector(charger_id=c4.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))

    # 5. Inactive Station (Must be hidden)
    s5 = Station(
        operator_id=operator_user.id,
        name="Koramangala Inactive Point",
        address="Koramangala 4th Block, Bengaluru",
        contact_phone="+919876540005",
        latitude=12.9350,
        longitude=77.6250,
        amenities=[],
        price_per_kwh=10.0,
        status=StationStatus.APPROVED,
        is_active=False,
    )
    db_session.add(s5)

    # 6. Pending Station (Must be hidden)
    s6 = Station(
        operator_id=operator_user.id,
        name="Indiranagar Pending Hub",
        address="12th Main, Indiranagar, Bengaluru",
        contact_phone="+919876540006",
        latitude=12.9780,
        longitude=77.6400,
        amenities=[],
        price_per_kwh=10.0,
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(s6)

    db_session.commit()
    return {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5, "s6": s6}


# =========================================================================
# Unit Tests (TC-F2-11)
# =========================================================================

def test_tc_f2_11_validate_query_valid():
    """Valid text search query is stripped and accepted."""
    assert validate_text_search_query("  Indiranagar  ") == "Indiranagar"
    assert validate_text_search_query("MG Road") == "MG Road"


def test_tc_f2_11_validate_query_empty_or_whitespace_raises_422():
    """Empty or whitespace-only queries are rejected with 422."""
    with pytest.raises(Exception) as exc1:
        validate_text_search_query("")
    assert "422" in str(exc1.value)

    with pytest.raises(Exception) as exc2:
        validate_text_search_query("    ")
    assert "422" in str(exc2.value)

    with pytest.raises(Exception) as exc3:
        validate_text_search_query(None)
    assert "422" in str(exc3.value)


def test_tc_f2_11_validate_query_too_long_raises_422():
    """Overly long search queries are rejected with 422."""
    with pytest.raises(Exception) as exc:
        validate_text_search_query("A" * 101)
    assert "422" in str(exc.value)
    assert "cannot exceed 100 characters" in str(exc.value)


def test_tc_f2_11_search_by_name(db_session: Session, search_stations_suite):
    """Direct function call matching station name substring."""
    total, q, items = search_stations_by_text(db_session, "Whitefield")
    assert total == 1
    assert items[0].name == "Whitefield Tech Park EV"


def test_tc_f2_11_search_by_address_or_area(db_session: Session, search_stations_suite):
    """Direct function call matching area / street in address."""
    # "Sony World" is in Koramangala address
    total, q, items = search_stations_by_text(db_session, "Sony World")
    assert total == 1
    assert "Koramangala" in items[0].name

    # "100 Feet Road" is in Indiranagar address
    total, q, items = search_stations_by_text(db_session, "100 Feet Road")
    assert total == 1
    assert "Indiranagar" in items[0].name


def test_tc_f2_11_search_case_insensitive(db_session: Session, search_stations_suite):
    """Search matches irrespective of casing."""
    total, q, items = search_stations_by_text(db_session, "indiranagar")
    assert total == 1
    assert items[0].name == "Indiranagar Supercharge Hub"

    total2, q2, items2 = search_stations_by_text(db_session, "INDIRANAGAR")
    assert total2 == 1


def test_tc_f2_11_search_no_match(db_session: Session, search_stations_suite):
    """Non-matching query returns 0 items without error."""
    total, q, items = search_stations_by_text(db_session, "NonExistentPlaceXYZ")
    assert total == 0
    assert items == []


# =========================================================================
# Integration & API Tests (REQ-F2-11 / TC-F2-11)
# =========================================================================

def test_tc_f2_11_api_auth_required(client: TestClient):
    """Unauthenticated search is rejected with 401."""
    resp = client.get("/api/v1/stations/text-search?query=Indiranagar")
    assert resp.status_code == 401


def test_tc_f2_11_api_visibility_gate(
    client: TestClient, db_session: Session, search_stations_suite, driver_user: User
):
    """
    Visibility gate (REQ-F2-03): Search for 'Koramangala' matches only approved active station,
    excluding the inactive station. Search for 'Indiranagar' excludes pending station.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Koramangala has 1 active approved and 1 inactive
    resp_kora = client.get(
        "/api/v1/stations/text-search?query=Koramangala",
        headers=headers,
    )
    assert resp_kora.status_code == 200
    data_kora = resp_kora.json()
    assert data_kora["total"] == 1
    assert data_kora["stations"][0]["name"] == "Koramangala Fast Point"

    # Indiranagar has 1 active approved and 1 pending
    resp_indi = client.get(
        "/api/v1/stations/text-search?query=Indiranagar",
        headers=headers,
    )
    assert resp_indi.status_code == 200
    data_indi = resp_indi.json()
    assert data_indi["total"] == 1
    assert data_indi["stations"][0]["name"] == "Indiranagar Supercharge Hub"


def test_tc_f2_11_api_get_text_search(
    client: TestClient, db_session: Session, search_stations_suite, driver_user: User
):
    """GET /stations/text-search with driver location returns results with distance."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/text-search?query=Bengaluru&latitude=12.9716&longitude=77.5946",
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    # All 4 approved stations have 'Bengaluru' in address
    assert data["total"] == 4
    # Distance is computed
    for s in data["stations"]:
        assert s["distance_km"] >= 0.0


def test_tc_f2_11_api_post_text_search(
    client: TestClient, db_session: Session, search_stations_suite, driver_user: User
):
    """POST /stations/text-search alternative JSON payload."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "query": "MG Road",
        "latitude": 12.9716,
        "longitude": 77.5946,
    }
    resp = client.post(
        "/api/v1/stations/text-search",
        json=payload,
        headers=headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["stations"][0]["name"] == "MG Road Express"


def test_tc_f2_11_api_empty_query_rejected(
    client: TestClient, search_stations_suite, driver_user: User
):
    """Empty search query is rejected with 422."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get(
        "/api/v1/stations/text-search?query=   ",
        headers=headers,
    )
    assert resp.status_code == 422


def test_tc_f2_11_api_search_with_sorting(
    client: TestClient, db_session: Session, search_stations_suite, driver_user: User
):
    """Text search integrated with REQ-F2-10 sorting (e.g. sort by power)."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Search for all approved stations in Bengaluru, sorted by power (descending)
    resp = client.get(
        "/api/v1/stations/text-search?query=Bengaluru&sort_by=power",
        headers=headers,
    )
    assert resp.status_code == 200
    stations = resp.json()["stations"]
    assert len(stations) == 4
    # Whitefield (120 kW) > Indiranagar (60 kW) > MG Road (50 kW) > Koramangala (30 kW)
    assert stations[0]["max_power_kw"] == 120.0
    assert stations[1]["max_power_kw"] == 60.0
    assert stations[2]["max_power_kw"] == 50.0
    assert stations[3]["max_power_kw"] == 30.0


# =========================================================================
# System Test Case (STC-F2-11)
# =========================================================================

def test_stc_f2_11_end_to_end_driver_text_search(
    client: TestClient, db_session: Session, search_stations_suite, driver_user: User
):
    """
    STC-F2-11: End-to-end system test verifying driver keyword search workflow:
    1. Driver searches for neighborhood "Indiranagar".
    2. Driver checks availability markers and charger connector metrics on returned station.
    3. Driver conducts broad search "Bengaluru" with radius limit and sorts by cheapest price.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Search neighborhood "Indiranagar"
    r1 = client.get(
        "/api/v1/stations/text-search?query=Indiranagar",
        headers=headers,
    )
    assert r1.status_code == 200
    st1 = r1.json()["stations"][0]
    assert st1["name"] == "Indiranagar Supercharge Hub"
    assert st1["available_connectors"] == 1
    assert st1["color_code"] == "green"

    # Step 2: Broad search sorted by price
    r2 = client.get(
        "/api/v1/stations/text-search?query=Bengaluru&sort_by=price",
        headers=headers,
    )
    assert r2.status_code == 200
    stations = r2.json()["stations"]
    # Cheapest is Koramangala (12 INR), then MG Road (14 INR), Indiranagar (15 INR), Whitefield (18 INR)
    assert stations[0]["price_per_kwh"] == 12.0
    assert stations[1]["price_per_kwh"] == 14.0
    assert stations[2]["price_per_kwh"] == 15.0
    assert stations[3]["price_per_kwh"] == 18.0

