"""
Test Suite for Route Cache and Fallback (REQ-F2-28 / TC-F2-28 / STC-F2-28 / CS19-054).

Requirements Under Test:
- REQ-F2-28: "The system shall cache route results for identical origin and destination pairs
  for up to 2 minutes, and shall show straight-line distance with a notice when the maps service
  is unavailable."
- Stimulus/Response SR-F2-09: "Maps service is unavailable: System shows straight-line distance
  with a notice and continues to work."
- Cache TTL: 120 seconds (2 minutes).
- Cache hit detection: identical origin coordinates (rounded to 5 decimals), station ID, and traffic condition.
- Cache bypass: force_fresh=True forces recalculation.
- Cache expiration: queries after 120 seconds trigger recalculation.
- Fallback mode: when maps service is unavailable, system shows straight-line distance,
  fallback_mode="straight_line", notice text, and continues functioning smoothly.
- Coordinate range validation: [-90, 90] for latitude, [-180, 180] for longitude.
- RBAC and data scope enforcement:
  - Driver can only access approved, active stations (404 for unapproved/inactive per REQ-F2-03).
  - Operator can access own stations or approved active stations (403 for foreign unapproved).
  - Admin has access to all stations.
- SW Architecture endpoints:
  - GET /api/v1/stations/route-cache-and-fallback
  - GET /api/v1/stations/{station_id}/route-cache-and-fallback
  - GET /api/v1/stations/{station_id}/cached-route
  - GET /api/v1/navigation/route-cache-and-fallback
  - GET /api/v1/navigation/{station_id}/route-cache-and-fallback
  - GET /api/v1/navigation/{station_id}/cached-route
- System lifecycle test (STC-F2-28).
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.cache import (
    FALLBACK_NOTICE_TEXT,
    ROUTE_CACHE_TTL_SECONDS,
    clear_route_cache,
    get_cached_route_preview,
    make_cache_key,
)
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
        hashed_password=hash_password("SecurePass123!"),
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
    name: str = "Indiranagar Fast Supercharger",
    latitude: float = 12.9716,
    longitude: float = 77.5946,
    status: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
) -> Station:
    station = Station(
        name=name,
        address="100 Feet Road, Indiranagar, Bengaluru, Karnataka",
        latitude=latitude,
        longitude=longitude,
        contact_phone="+919876543210",
        contact_email="indiranagar@chargeslot.com",
        operating_hours="24 hours",
        operator_id=operator.id,
        status=status,
        is_active=is_active,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture(autouse=True)
def _reset_cache():
    """Ensure in-memory route cache is clean before and after every test."""
    clear_route_cache()
    yield
    clear_route_cache()


@pytest.fixture(autouse=True)
def _mock_online_maps_service():
    """Default maps service to online unless simulated or mocked."""
    def _mock_routing(origin_lat, origin_lon, dest_lat, dest_lon, station_name, traffic):
        from app.navigation.routes import FREE_FLOW_SPEED_KMH, TRAFFIC_SPEEDS_KMH
        from app.schemas.navigation import RouteWaypoint

        road_dist = 6.2
        speed = TRAFFIC_SPEEDS_KMH[traffic]
        dur = round((road_dist / speed) * 60.0, 1)
        delay = max(0.0, round(dur - (road_dist / FREE_FLOW_SPEED_KMH) * 60.0, 1))
        geom = [
            [round(origin_lat, 6), round(origin_lon, 6)],
            [round((origin_lat + dest_lat) / 2, 6), round((origin_lon + dest_lon) / 2, 6)],
            [round(dest_lat, 6), round(dest_lon, 6)],
        ]
        wps = [
            RouteWaypoint(
                step_index=0,
                instruction="Depart along primary corridor",
                latitude=round(origin_lat, 6),
                longitude=round(origin_lon, 6),
                distance_km=0.0,
                duration_minutes=0.0,
            ),
            RouteWaypoint(
                step_index=1,
                instruction=f"Arrive at destination: {station_name}",
                latitude=round(dest_lat, 6),
                longitude=round(dest_lon, 6),
                distance_km=road_dist,
                duration_minutes=dur,
            ),
        ]
        return (road_dist, dur, delay, speed, geom, wps)

    with patch("app.navigation.routes._try_external_routing", side_effect=_mock_routing):
        yield


# ===========================================================================
# 1. Unit Tests: Caching Mechanics & 2-Minute TTL (TC-F2-28)
# ===========================================================================


def test_initial_request_misses_cache_and_stores_entry(db_session):
    """First request computes a fresh route preview and stores it in cache."""
    operator = _make_user(
        db_session,
        name="Cache Op 1",
        email="cache_op1@example.com",
        phone="+919876543101",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Cache Driver 1",
        email="cache_driver1@example.com",
        phone="+919876543102",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    res = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t0,
    )

    assert res.station_id == station.id
    assert res.cache_hit is False
    assert res.cache_age_seconds == 0.0
    assert res.cache_ttl_seconds == ROUTE_CACHE_TTL_SECONDS
    assert res.cache_expires_at == t0 + timedelta(seconds=120)
    assert res.is_fallback is False
    assert res.road_distance_km > 0.0


def test_subsequent_request_within_2_minutes_hits_cache(db_session):
    """Second request within 2 minutes for identical origin and station returns cached result."""
    operator = _make_user(
        db_session,
        name="Cache Op 2",
        email="cache_op2@example.com",
        phone="+919876543103",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Cache Driver 2",
        email="cache_driver2@example.com",
        phone="+919876543104",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    res1 = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t0,
    )
    assert res1.cache_hit is False

    # 45 seconds later (within 120s TTL)
    t1 = t0 + timedelta(seconds=45)
    res2 = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t1,
    )

    assert res2.cache_hit is True
    assert res2.cache_age_seconds == 45.0
    assert res2.cache_expires_at == res1.cache_expires_at
    assert res2.generated_at == res1.generated_at
    assert res2.road_distance_km == res1.road_distance_km
    assert res2.estimated_travel_time_minutes == res1.estimated_travel_time_minutes


def test_cache_expires_after_2_minutes(db_session):
    """Request after 120 seconds has elapsed refreshes the cache."""
    operator = _make_user(
        db_session,
        name="Cache Op 3",
        email="cache_op3@example.com",
        phone="+919876543105",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Cache Driver 3",
        email="cache_driver3@example.com",
        phone="+919876543106",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t0,
    )

    # 121 seconds later (> 120s TTL)
    t2 = t0 + timedelta(seconds=121)
    res_expired = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t2,
    )

    assert res_expired.cache_hit is False
    assert res_expired.cache_age_seconds == 0.0
    assert res_expired.cache_expires_at == t2 + timedelta(seconds=120)
    assert res_expired.generated_at == t2


def test_force_fresh_bypasses_cache_within_ttl(db_session):
    """force_fresh=True forces fresh route computation even within the 2-minute cache window."""
    operator = _make_user(
        db_session,
        name="Cache Op 4",
        email="cache_op4@example.com",
        phone="+919876543107",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Cache Driver 4",
        email="cache_driver4@example.com",
        phone="+919876543108",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator)

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        current_time=t0,
    )

    # 30 seconds later with force_fresh=True
    t1 = t0 + timedelta(seconds=30)
    res_fresh = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        traffic_condition="normal",
        force_fresh=True,
        current_time=t1,
    )

    assert res_fresh.cache_hit is False
    assert res_fresh.cache_age_seconds == 0.0
    assert res_fresh.generated_at == t1


def test_different_origin_coordinates_yield_cache_miss(db_session):
    """Different origin location creates a distinct cache key and misses existing cache."""
    operator = _make_user(
        db_session,
        name="Cache Op 5",
        email="cache_op5@example.com",
        phone="+919876543109",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Cache Driver 5",
        email="cache_driver5@example.com",
        phone="+919876543110",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator)

    t0 = datetime(2026, 11, 14, 10, 0, 0, tzinfo=timezone.utc)
    get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        current_time=t0,
    )

    # Different origin coordinates
    res_diff = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9400,
        origin_longitude=77.6300,
        current_time=t0 + timedelta(seconds=10),
    )
    assert res_diff.cache_hit is False


def test_cache_key_rounds_coordinates_to_5_decimals():
    """Identical locations with micro-floating variations round to same cache key."""
    key1 = make_cache_key(1, 12.935201, 77.624502, "normal")
    key2 = make_cache_key(1, 12.935204, 77.624503, "NORMAL")
    assert key1 == key2


# ===========================================================================
# 2. Fallback Mechanics: Maps Service Unavailable (REQ-F2-28 / SR-F2-09)
# ===========================================================================


def test_straight_line_fallback_when_maps_unavailable_flag_set(db_session):
    """When simulate_maps_unavailable=True, system provides straight-line distance and notice."""
    operator = _make_user(
        db_session,
        name="Fallback Op 1",
        email="fallback_op1@example.com",
        phone="+919876543111",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Fallback Driver 1",
        email="fallback_driver1@example.com",
        phone="+919876543112",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    res = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
        simulate_maps_unavailable=True,
    )

    assert res.is_fallback is True
    assert res.fallback_mode == "straight_line"
    assert res.fallback_notice == FALLBACK_NOTICE_TEXT
    assert "Maps routing service is unavailable" in res.fallback_notice
    # Per REQ-F2-28: road_distance_km equals straight-line distance fallback
    assert res.road_distance_km == res.straight_line_distance_km
    assert len(res.route_geometry) == 2
    assert res.route_geometry[0] == [round(12.9352, 6), round(77.6245, 6)]
    assert res.route_geometry[1] == [round(station.latitude, 6), round(station.longitude, 6)]
    assert len(res.waypoints) == 2
    assert "direct straight-line trajectory" in res.waypoints[0].instruction
    assert f"Arrive at destination: {station.name}" in res.waypoints[1].instruction


def test_straight_line_fallback_on_maps_service_exception(db_session):
    """When calculate_route_preview raises an unexpected maps service error, system falls back gracefully."""
    operator = _make_user(
        db_session,
        name="Fallback Op 2",
        email="fallback_op2@example.com",
        phone="+919876543113",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Fallback Driver 2",
        email="fallback_driver2@example.com",
        phone="+919876543114",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    with patch(
        "app.navigation.cache.calculate_route_preview",
        side_effect=RuntimeError("Google Maps / OSRM API Connection Timeout"),
    ):
        res = get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=12.9352,
            origin_longitude=77.6245,
        )

    # Continues to work gracefully without 500 error (SR-F2-09)
    assert res.is_fallback is True
    assert res.fallback_mode == "straight_line"
    assert res.fallback_notice == FALLBACK_NOTICE_TEXT
    assert res.road_distance_km == res.straight_line_distance_km


def test_fallback_zero_distance_when_already_at_station(db_session):
    """When driver is directly at the station, fallback produces zero distance and arrival waypoint."""
    operator = _make_user(
        db_session,
        name="Fallback Op 3",
        email="fallback_op3@example.com",
        phone="+919876543115",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Fallback Driver 3",
        email="fallback_driver3@example.com",
        phone="+919876543116",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    res = get_cached_route_preview(
        db=db_session,
        user=driver,
        station_id=station.id,
        origin_latitude=12.9716,
        origin_longitude=77.5946,
        simulate_maps_unavailable=True,
    )

    assert res.straight_line_distance_km == 0.0
    assert res.road_distance_km == 0.0
    assert res.estimated_travel_time_minutes == 0.0
    assert len(res.waypoints) == 1
    assert "Arrived at destination" in res.waypoints[0].instruction


# ===========================================================================
# 3. Coordinate Range Validation & RBAC Scoping
# ===========================================================================


def test_invalid_coordinates_raise_422(db_session):
    """Invalid latitude or longitude coordinates raise HTTP 422."""
    operator = _make_user(
        db_session,
        name="Coord Op",
        email="coord_op@example.com",
        phone="+919876543117",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Coord Driver",
        email="coord_driver@example.com",
        phone="+919876543118",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator)

    with pytest.raises(HTTPException) as exc_info:
        get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=95.0,  # Invalid latitude
            origin_longitude=77.5946,
        )
    assert exc_info.value.status_code == 422

    with pytest.raises(HTTPException) as exc_info2:
        get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=12.9716,
            origin_longitude=-195.0,  # Invalid longitude
        )
    assert exc_info2.value.status_code == 422


def test_station_not_found_raises_404(db_session):
    """Querying a non-existent station ID returns 404."""
    driver = _make_user(
        db_session,
        name="404 Driver",
        email="404_driver@example.com",
        phone="+919876543119",
        role=UserRole.DRIVER,
    )
    with pytest.raises(HTTPException) as exc_info:
        get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=999999,
            origin_latitude=12.9716,
            origin_longitude=77.5946,
        )
    assert exc_info.value.status_code == 404


def test_driver_cannot_view_unapproved_or_inactive_station(db_session):
    """Drivers querying unapproved or inactive stations receive 404 (REQ-F2-03)."""
    operator = _make_user(
        db_session,
        name="Unapp Op",
        email="unapp_op@example.com",
        phone="+919876543120",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Unapp Driver",
        email="unapp_driver@example.com",
        phone="+919876543121",
        role=UserRole.DRIVER,
    )
    pending_station = _seed_station(
        db_session,
        operator,
        status=StationStatus.PENDING,
        is_active=True,
    )
    inactive_station = _seed_station(
        db_session,
        operator,
        status=StationStatus.APPROVED,
        is_active=False,
    )

    with pytest.raises(HTTPException) as exc1:
        get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=pending_station.id,
            origin_latitude=12.9716,
            origin_longitude=77.5946,
        )
    assert exc1.value.status_code == 404

    with pytest.raises(HTTPException) as exc2:
        get_cached_route_preview(
            db=db_session,
            user=driver,
            station_id=inactive_station.id,
            origin_latitude=12.9716,
            origin_longitude=77.5946,
        )
    assert exc2.value.status_code == 404


def test_operator_scoping_rules(db_session):
    """Operator can view their own unapproved station, but receives 403 for another's unapproved station."""
    op1 = _make_user(
        db_session,
        name="Op Scoping 1",
        email="op_scoping1@example.com",
        phone="+919876543122",
        role=UserRole.OPERATOR,
    )
    op2 = _make_user(
        db_session,
        name="Op Scoping 2",
        email="op_scoping2@example.com",
        phone="+919876543123",
        role=UserRole.OPERATOR,
    )
    station_op1_pending = _seed_station(
        db_session,
        op1,
        status=StationStatus.PENDING,
        is_active=True,
    )

    # Op 1 can access own pending station
    res_own = get_cached_route_preview(
        db=db_session,
        user=op1,
        station_id=station_op1_pending.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
    )
    assert res_own.station_id == station_op1_pending.id

    # Op 2 is forbidden from accessing Op 1's pending station
    with pytest.raises(HTTPException) as exc:
        get_cached_route_preview(
            db=db_session,
            user=op2,
            station_id=station_op1_pending.id,
            origin_latitude=12.9352,
            origin_longitude=77.6245,
        )
    assert exc.value.status_code == 403


def test_admin_has_full_access_to_unapproved_stations(db_session):
    """Admin has universal visibility including unapproved and inactive stations."""
    operator = _make_user(
        db_session,
        name="Admin Scope Op",
        email="admin_scope_op@example.com",
        phone="+919876543124",
        role=UserRole.OPERATOR,
    )
    admin = _make_user(
        db_session,
        name="Admin Scope User",
        email="admin_scope@example.com",
        phone="+919876543125",
        role=UserRole.ADMIN,
    )
    pending_station = _seed_station(
        db_session,
        operator,
        status=StationStatus.PENDING,
        is_active=False,
    )

    res = get_cached_route_preview(
        db=db_session,
        user=admin,
        station_id=pending_station.id,
        origin_latitude=12.9352,
        origin_longitude=77.6245,
    )
    assert res.station_id == pending_station.id


# ===========================================================================
# 4. HTTP API Endpoint Tests (Stations and Navigation Routers)
# ===========================================================================


def test_api_stations_route_cache_and_fallback_query(client: TestClient, db_session):
    """SW Architecture route: GET /api/v1/stations/route-cache-and-fallback."""
    operator = _make_user(
        db_session,
        name="API Op 1",
        email="api_op1@example.com",
        phone="+919876543126",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="API Driver 1",
        email="api_driver1@example.com",
        phone="+919876543127",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    # 1. First call -> Cache Miss
    resp1 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    assert data1["station_id"] == station.id
    assert data1["cache_hit"] is False
    assert data1["cache_ttl_seconds"] == 120

    # 2. Second call -> Cache Hit
    resp2 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["cache_hit"] is True
    assert data2["cache_expires_at"] == data1["cache_expires_at"]

    # 3. Third call with force_fresh=True -> Cache Miss
    resp3 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "force_fresh": True,
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    assert data3["cache_hit"] is False


def test_api_stations_path_endpoint(client: TestClient, db_session):
    """REST path route: GET /api/v1/stations/{station_id}/route-cache-and-fallback."""
    operator = _make_user(
        db_session,
        name="API Op 2",
        email="api_op2@example.com",
        phone="+919876543128",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="API Driver 2",
        email="api_driver2@example.com",
        phone="+919876543129",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    resp = client.get(
        f"/api/v1/stations/{station.id}/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "latitude": 12.9352,
            "longitude": 77.6245,
            "simulate_maps_unavailable": True,
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_fallback"] is True
    assert data["fallback_mode"] == "straight_line"
    assert data["fallback_notice"] == FALLBACK_NOTICE_TEXT
    assert data["road_distance_km"] == data["straight_line_distance_km"]


def test_api_navigation_endpoints(client: TestClient, db_session):
    """Navigation module routes: query and path endpoints with straight-line fallback."""
    operator = _make_user(
        db_session,
        name="API Op 3",
        email="api_op3@example.com",
        phone="+919876543130",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="API Driver 3",
        email="api_driver3@example.com",
        phone="+919876543131",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

    # Dedicated query route
    resp_query = client.get(
        "/api/v1/navigation/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
        },
    )
    assert resp_query.status_code == 200
    assert resp_query.json()["cache_hit"] is False

    # Path route hitting cached entry
    resp_path = client.get(
        f"/api/v1/navigation/{station.id}/route-cache-and-fallback",
        headers=_auth_header(driver),
        params={
            "latitude": 12.9352,
            "longitude": 77.6245,
        },
    )
    assert resp_path.status_code == 200
    assert resp_path.json()["cache_hit"] is True

    # Path alias route
    resp_alias = client.get(
        f"/api/v1/navigation/{station.id}/cached-route",
        headers=_auth_header(driver),
        params={
            "latitude": 12.9352,
            "longitude": 77.6245,
        },
    )
    assert resp_alias.status_code == 200
    assert resp_alias.json()["cache_hit"] is True


# ===========================================================================
# 5. System Lifecycle Test (STC-F2-28)
# ===========================================================================


def test_stc_f2_28_system_route_cache_and_fallback_lifecycle(client: TestClient, db_session):
    """
    STC-F2-28: End-to-end system lifecycle test for route caching and maps outage fallback.

    Step 1: Driver requests route preview to station -> fresh calculation stored in cache for 120s.
    Step 2: Driver refreshes route 30s later -> cache hit returned instantly with positive age.
    Step 3: External maps routing service suffers an outage -> system falls back to straight-line
            distance with notice, keeping application operational without 500 error.
    Step 4: Driver forces fresh calculation -> bypasses cache and reflects current conditions.
    Step 5: 120s TTL expires -> next request automatically triggers recalculation.
    Step 6: Driver attempts to access pending unapproved station -> isolated by RBAC (404).
    """
    operator = _make_user(
        db_session,
        name="Lifecycle Op",
        email="lifecycle_op@example.com",
        phone="+919876543132",
        role=UserRole.OPERATOR,
    )
    driver = _make_user(
        db_session,
        name="Lifecycle Driver",
        email="lifecycle_driver@example.com",
        phone="+919876543133",
        role=UserRole.DRIVER,
    )
    station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)
    auth_header = _auth_header(driver)

    t0 = datetime(2026, 11, 14, 12, 0, 0, tzinfo=timezone.utc)

    # Step 1: Initial request
    r1 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "current_time": t0.isoformat(),
        },
    )
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["cache_hit"] is False
    assert d1["cache_age_seconds"] == 0.0
    assert d1["cache_ttl_seconds"] == 120
    assert d1["is_fallback"] is False

    # Step 2: Request 30 seconds later -> Cache hit
    t1 = t0 + timedelta(seconds=30)
    r2 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "current_time": t1.isoformat(),
        },
    )
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["cache_hit"] is True
    assert d2["cache_age_seconds"] == 30.0

    # Step 3: Maps routing service unavailable -> Straight-line fallback with notice
    r3 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "simulate_maps_unavailable": True,
            "current_time": t1.isoformat(),
        },
    )
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["is_fallback"] is True
    assert d3["fallback_mode"] == "straight_line"
    assert d3["fallback_notice"] == FALLBACK_NOTICE_TEXT
    assert d3["road_distance_km"] == d3["straight_line_distance_km"]

    # Step 4: Driver forces fresh route preview -> Cache bypassed
    r4 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "force_fresh": True,
            "current_time": t1.isoformat(),
        },
    )
    assert r4.status_code == 200
    d4 = r4.json()
    assert d4["cache_hit"] is False

    # Step 5: After 120s TTL (e.g. 150s from t0) -> Cache expired and refreshed
    t2 = t0 + timedelta(seconds=150)
    r5 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
            "traffic_condition": "normal",
            "current_time": t2.isoformat(),
        },
    )
    assert r5.status_code == 200
    d5 = r5.json()
    assert d5["cache_hit"] is False

    # Step 6: RBAC isolation for unapproved station
    pending_station = _seed_station(
        db_session,
        operator,
        name="Pending Hub",
        status=StationStatus.PENDING,
    )
    r6 = client.get(
        "/api/v1/stations/route-cache-and-fallback",
        headers=auth_header,
        params={
            "station_id": pending_station.id,
            "latitude": 12.9352,
            "longitude": 77.6245,
        },
    )
    assert r6.status_code == 404
