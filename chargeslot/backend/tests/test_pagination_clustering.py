"""
Unit and Integration Tests for Station Pagination and Map Marker Clustering
Requirement: REQ-F2-12 (Pagination and clustering)
Story ID: CS19-038
Test Case ID: TC-F2-12
System Test Case ID: STC-F2-12
Architecture Ref: discovery/clustering.py / GET & POST /api/v1/stations/map-view & /paginated-search
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType
from app.utils.security import hash_password, create_access_token
from app.schemas.discovery import NearbyStationItem
from app.discovery.clustering import (
    validate_pagination_params,
    paginate_items,
    cluster_stations,
    DEFAULT_PAGE_SIZE,
    CLUSTERING_THRESHOLD,
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
        name="Driver Pagination Tester",
        email="driver.pagination@example.com",
        phone="+919876542222",
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
        name="Operator Pagination Tester",
        email="operator.pagination@example.com",
        phone="+919876542223",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def generate_mock_stations(count: int, base_lat: float = 12.9716, base_lon: float = 77.5946) -> list[NearbyStationItem]:
    """Generates mock in-memory NearbyStationItem instances."""
    items: list[NearbyStationItem] = []
    for i in range(1, count + 1):
        # Slightly jitter coordinates across a few grid clusters
        jitter_x = (i % 5) * 0.02
        jitter_y = (i // 5) * 0.02
        items.append(
            NearbyStationItem(
                id=i,
                name=f"Station #{i}",
                address=f"Street #{i}, Area {i % 4}",
                latitude=round(base_lat + jitter_y, 6),
                longitude=round(base_lon + jitter_x, 6),
                distance_km=round(1.0 + i * 0.2, 2),
                operating_hours="24 hours",
                amenities=["WiFi"] if i % 2 == 0 else [],
                contact_phone=f"+9198765{i:05d}",
                status="approved",
                is_active=True,
                total_chargers=2,
                total_connectors=4,
                available_connectors=2 if i % 3 != 0 else 0,
                connector_types=["CCS2"],
                max_power_kw=50.0,
                price_per_kwh=15.0,
                color_code="amber" if i % 3 != 0 else "red",
                status_label="Partially Available" if i % 3 != 0 else "Occupied",
                badge_text="2/4 Available" if i % 3 != 0 else "0/4 Occupied",
            )
        )
    return items


@pytest.fixture
def db_stations_suite(db_session: Session, operator_user: User):
    """
    Creates a set of 5 database stations to verify pagination and clustering APIs.
    """
    stations: list[Station] = []
    for i in range(1, 6):
        st = Station(
            operator_id=operator_user.id,
            name=f"DB Station {i}",
            address=f"Address {i}, Bengaluru",
            contact_phone=f"+91987653{i:04d}",
            latitude=round(12.9716 + (i * 0.01), 6),
            longitude=round(77.5946 + (i * 0.01), 6),
            amenities=["WiFi"],
            price_per_kwh=12.0 + i,
            status=StationStatus.APPROVED,
            is_active=True,
        )
        db_session.add(st)
        db_session.flush()

        ch = Charger(station_id=st.id, name=f"Ch-{i}", power_kw=50.0, current_type=CurrentType.DC, gateway_id=f"GW-P-{i}", is_active=True)
        db_session.add(ch)
        db_session.flush()

        db_session.add(Connector(charger_id=ch.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE))
        stations.append(st)

    # 1 Inactive station (must be hidden)
    st_inact = Station(
        operator_id=operator_user.id,
        name="DB Station Inactive",
        address="Inactive Rd",
        contact_phone="+919876539999",
        latitude=12.9716,
        longitude=77.5946,
        status=StationStatus.APPROVED,
        is_active=False,
    )
    db_session.add(st_inact)
    db_session.commit()
    return stations


# =========================================================================
# Unit Tests (TC-F2-12)
# =========================================================================

def test_tc_f2_12_validate_pagination_params_valid():
    """Verify default page size is 20 per REQ-F2-12."""
    page, page_size = validate_pagination_params(1)
    assert page == 1
    assert page_size == DEFAULT_PAGE_SIZE
    assert page_size == 20

    page, page_size = validate_pagination_params(3, 50)
    assert page == 3
    assert page_size == 50


def test_tc_f2_12_validate_pagination_params_invalid_page():
    """Page number < 1 is rejected with 422."""
    with pytest.raises(Exception) as exc:
        validate_pagination_params(0)
    assert "422" in str(exc.value)
    assert "Page number 0 is invalid" in str(exc.value)


def test_tc_f2_12_validate_pagination_params_invalid_page_size():
    """Page size < 1 or > 100 is rejected with 422."""
    with pytest.raises(Exception) as exc1:
        validate_pagination_params(1, 0)
    assert "422" in str(exc1.value)

    with pytest.raises(Exception) as exc2:
        validate_pagination_params(1, 101)
    assert "422" in str(exc2.value)


def test_tc_f2_12_paginate_items_calculation():
    """
    Verify 45 items paginated at 20/page (REQ-F2-12):
    Page 1: 20 items, total_pages=3, has_next=True, has_prev=False
    Page 2: 20 items, total_pages=3, has_next=True, has_prev=True
    Page 3: 5 items, total_pages=3, has_next=False, has_prev=True
    """
    mock_items = generate_mock_stations(45)

    # Page 1
    p1_items, total, total_pages, has_next, has_prev = paginate_items(mock_items, page=1, page_size=20)
    assert total == 45
    assert total_pages == 3
    assert len(p1_items) == 20
    assert p1_items[0].id == 1
    assert p1_items[-1].id == 20
    assert has_next is True
    assert has_prev is False

    # Page 2
    p2_items, _, _, has_next, has_prev = paginate_items(mock_items, page=2, page_size=20)
    assert len(p2_items) == 20
    assert p2_items[0].id == 21
    assert p2_items[-1].id == 40
    assert has_next is True
    assert has_prev is True

    # Page 3
    p3_items, _, _, has_next, has_prev = paginate_items(mock_items, page=3, page_size=20)
    assert len(p3_items) == 5
    assert p3_items[0].id == 41
    assert p3_items[-1].id == 45
    assert has_next is False
    assert has_prev is True


def test_tc_f2_12_cluster_stations_under_threshold():
    """
    When stations in view <= 50, clustering is NOT performed (REQ-F2-12).
    is_clustered is False, clusters list is empty, individual_stations returned.
    """
    mock_40 = generate_mock_stations(40)
    is_clustered, clusters, individuals = cluster_stations(mock_40, threshold=50)
    assert is_clustered is False
    assert clusters == []
    assert len(individuals) == 40


def test_tc_f2_12_cluster_stations_over_threshold():
    """
    When stations in view > 50 (e.g. 55), markers are clustered (REQ-F2-12).
    is_clustered is True, clusters list contains aggregated clusters with connectors & bounds.
    """
    mock_55 = generate_mock_stations(55)
    is_clustered, clusters, individuals = cluster_stations(mock_55, threshold=50)
    assert is_clustered is True
    assert len(clusters) > 0
    # Every cluster has valid aggregation metrics
    for cl in clusters:
        assert cl.station_count >= 2
        assert cl.total_connectors > 0
        assert cl.color_code in ["green", "amber", "red", "grey"]
        assert len(cl.bounds) == 4
        assert cl.bounds[0] <= cl.latitude <= cl.bounds[2]


# =========================================================================
# Integration & API Tests (REQ-F2-12 / TC-F2-12)
# =========================================================================

def test_tc_f2_12_api_auth_required(client: TestClient):
    """Unauthenticated requests are rejected with 401."""
    resp1 = client.get("/api/v1/stations/map-view")
    assert resp1.status_code == 401

    resp2 = client.get("/api/v1/stations/paginated-search")
    assert resp2.status_code == 401


def test_tc_f2_12_api_paginated_search_defaults(
    client: TestClient, db_stations_suite, driver_user: User
):
    """GET /stations/paginated-search returns 20/page by default."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/stations/paginated-search", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 1
    assert data["page_size"] == 20
    assert data["total"] == 5
    assert data["total_pages"] == 1
    assert data["has_next"] is False
    assert data["has_prev"] is False
    assert len(data["items"]) == 5


def test_tc_f2_12_api_map_view_under_threshold(
    client: TestClient, db_stations_suite, driver_user: User
):
    """
    GET /stations/map-view returns individual stations when total <= 50.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/stations/map-view?threshold=50", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_clustered"] is False
    assert data["total_stations"] == 5
    assert len(data["clusters"]) == 0
    assert len(data["individual_stations"]) == 5


def test_tc_f2_12_api_map_view_clustering_when_threshold_exceeded(
    client: TestClient, db_stations_suite, driver_user: User
):
    """
    GET /stations/map-view triggers clustering when station count exceeds threshold.
    Using threshold=2 with 5 database stations triggers is_clustered=True.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    resp = client.get("/api/v1/stations/map-view?threshold=2", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_clustered"] is True
    assert data["threshold"] == 2
    assert data["total_stations"] == 5
    assert len(data["clusters"]) > 0


def test_tc_f2_12_api_post_map_view(
    client: TestClient, db_stations_suite, driver_user: User
):
    """POST /stations/map-view query with JSON payload."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "latitude": 12.9716,
        "longitude": 77.5946,
        "radius_km": 50.0,
        "threshold": 50,
    }
    resp = client.post("/api/v1/stations/map-view", json=payload, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_clustered"] is False
    assert data["total_stations"] == 5


def test_tc_f2_12_api_pagination_validation_errors(
    client: TestClient, db_stations_suite, driver_user: User
):
    """Invalid page numbers or page sizes are rejected with 422."""
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Invalid page 0
    r1 = client.get("/api/v1/stations/paginated-search?page=0", headers=headers)
    assert r1.status_code == 422

    # Invalid page size 0
    r2 = client.get("/api/v1/stations/paginated-search?page_size=0", headers=headers)
    assert r2.status_code == 422

    # Invalid page size > 100
    r3 = client.get("/api/v1/stations/paginated-search?page_size=101", headers=headers)
    assert r3.status_code == 422


# =========================================================================
# System Test Case (STC-F2-12)
# =========================================================================

def test_stc_f2_12_end_to_end_pagination_and_clustering_workflow(
    client: TestClient, db_stations_suite, driver_user: User
):
    """
    STC-F2-12: End-to-end driver navigation experience:
    1. Driver opens map view: unclustered when stations <= 50.
    2. Map view zoom-out: clusters automatically when > 50 stations in view.
    3. Driver toggles to list view: browses stations with standard 20/page pagination.
    """
    token = make_token(driver_user)
    headers = {"Authorization": f"Bearer {token}"}

    # Step 1: Normal map view (<= 50 stations)
    r_map = client.get("/api/v1/stations/map-view", headers=headers)
    assert r_map.status_code == 200
    assert r_map.json()["is_clustered"] is False

    # Step 2: Clustered map view (simulated when > threshold)
    r_clustered = client.get("/api/v1/stations/map-view?threshold=2", headers=headers)
    assert r_clustered.status_code == 200
    clustered_data = r_clustered.json()
    assert clustered_data["is_clustered"] is True
    assert len(clustered_data["clusters"]) > 0
    cl = clustered_data["clusters"][0]
    assert "Available" in cl["badge_text"]

    # Step 3: 20/page paginated list view
    r_page = client.get("/api/v1/stations/paginated-search?page=1&page_size=20", headers=headers)
    assert r_page.status_code == 200
    page_data = r_page.json()
    assert page_data["page_size"] == 20
    assert page_data["total"] == 5
    assert len(page_data["items"]) == 5
