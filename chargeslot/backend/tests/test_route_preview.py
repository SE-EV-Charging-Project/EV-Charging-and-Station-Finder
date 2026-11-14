"""
Test Suite for Route Preview (REQ-F2-25 / TC-F2-25 / STC-F2-25 / CS19-051).

Requirements Under Test:
- REQ-F2-25: "The system shall display a route preview from the driver's location to a station,
  showing the route, road distance and estimated travel time with current traffic."
- Coordinate range validation: [-90, 90] for latitude, [-180, 180] for longitude.
- Traffic condition factors: 'low', 'normal', 'heavy', 'severe'.
- Fallback road estimation and notice when external maps service is offline (SR-F2-09).
- Route geometry and waypoint generation with turn/approach instructions.
- RBAC and isolation:
  - Driver can only view approved, active stations (REQ-F2-03).
  - Operator can view their own stations or approved stations. Foreign unapproved returns 403.
  - Admin has full visibility.
- Endpoints tested:
  - SW Architecture route: GET /api/v1/stations/route-preview
  - REST path route: GET /api/v1/stations/{station_id}/route-preview
  - Dedicated navigation route: GET /api/v1/navigation/route-preview
  - Dedicated navigation path: GET /api/v1/navigation/{station_id}/route-preview
- System lifecycle test (STC-F2-25).
"""

from unittest.mock import MagicMock, patch
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.routes import (
    calculate_route_preview,
    normalize_traffic_condition,
    validate_coordinates,
    ROAD_DISTANCE_EXPANSION_FACTOR,
    TRAFFIC_SPEEDS_KMH,
)
from app.schemas.navigation import TrafficCondition
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
    name: str = "MG Road Fast EV Hub",
    address: str = "MG Road, Bangalore",
    latitude: float = 12.9750,
    longitude: float = 77.6050,
    status: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
) -> Station:
    station = Station(
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        contact_phone="9876543210",
        contact_email="mgroad@chargeslot.com",
        operating_hours="24 hours",
        status=status,
        is_active=is_active,
        operator_id=operator.id,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


# ===========================================================================
# TC-F2-25: Unit Tests - Coordinates & Traffic Validation
# ===========================================================================


class TestCoordinateAndTrafficValidation:
    def test_valid_coordinates(self):
        lat, lon = validate_coordinates(12.9716, 77.5946)
        assert lat == 12.9716
        assert lon == 77.5946

        # Boundary extremes
        assert validate_coordinates(90.0, 180.0) == (90.0, 180.0)
        assert validate_coordinates(-90.0, -180.0) == (-90.0, -180.0)
        assert validate_coordinates(0.0, 0.0) == (0.0, 0.0)

    def test_invalid_latitude_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_coordinates(90.001, 77.0)
        assert exc_info.value.status_code == 422
        assert "Latitude" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info2:
            validate_coordinates(-95.0, 77.0)
        assert exc_info2.value.status_code == 422

    def test_invalid_longitude_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate_coordinates(12.0, 180.5)
        assert exc_info.value.status_code == 422
        assert "Longitude" in exc_info.value.detail

        with pytest.raises(HTTPException) as exc_info2:
            validate_coordinates(12.0, -185.0)
        assert exc_info2.value.status_code == 422

    def test_traffic_condition_normalization(self):
        assert normalize_traffic_condition(None) == TrafficCondition.NORMAL
        assert normalize_traffic_condition("") == TrafficCondition.NORMAL
        assert normalize_traffic_condition("LOW") == TrafficCondition.LOW
        assert normalize_traffic_condition("  heavy  ") == TrafficCondition.HEAVY
        assert normalize_traffic_condition("severe") == TrafficCondition.SEVERE
        assert normalize_traffic_condition("normal") == TrafficCondition.NORMAL

    def test_invalid_traffic_condition_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            normalize_traffic_condition("hyperdrive")
        assert exc_info.value.status_code == 422
        assert "Invalid traffic condition" in exc_info.value.detail


# ===========================================================================
# TC-F2-25: Unit & Service Logic Tests
# ===========================================================================


class TestRoutePreviewServiceLogic:
    def test_route_preview_basic_calculation(self, db_session):
        operator = _make_user(db_session, name="Op 1", email="op1@test.com", phone="9000000001", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver 1", email="dr1@test.com", phone="9000000002", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

        # Driver is ~10 km away
        origin_lat = 12.9200
        origin_lon = 77.5800

        preview = calculate_route_preview(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=origin_lat,
            origin_longitude=origin_lon,
            traffic_condition="normal",
        )

        assert preview.station_id == station.id
        assert preview.station_name == station.name
        assert preview.straight_line_distance_km > 0
        assert preview.road_distance_km >= preview.straight_line_distance_km
        assert preview.estimated_travel_time_minutes > 0
        assert preview.traffic_condition == "normal"
        assert len(preview.route_geometry) >= 2
        assert len(preview.waypoints) >= 2
        assert preview.waypoints[0].step_index == 0
        assert preview.waypoints[-1].step_index == len(preview.waypoints) - 1

    def test_route_preview_different_traffic_conditions(self, db_session):
        operator = _make_user(db_session, name="Op Traffic", email="optraffic@test.com", phone="9000000010", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Traffic", email="drtraffic@test.com", phone="9000000011", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, latitude=13.0000, longitude=77.6000)

        origin_lat = 12.9000
        origin_lon = 77.6000

        res_low = calculate_route_preview(db_session, driver, station.id, origin_lat, origin_lon, "low")
        res_normal = calculate_route_preview(db_session, driver, station.id, origin_lat, origin_lon, "normal")
        res_heavy = calculate_route_preview(db_session, driver, station.id, origin_lat, origin_lon, "heavy")
        res_severe = calculate_route_preview(db_session, driver, station.id, origin_lat, origin_lon, "severe")

        # Distances are identical
        assert res_low.road_distance_km == res_normal.road_distance_km == res_heavy.road_distance_km == res_severe.road_distance_km

        # Duration ordering: low < normal < heavy < severe
        assert res_low.estimated_travel_time_minutes < res_normal.estimated_travel_time_minutes
        assert res_normal.estimated_travel_time_minutes < res_heavy.estimated_travel_time_minutes
        assert res_heavy.estimated_travel_time_minutes < res_severe.estimated_travel_time_minutes

        # Delays increase as traffic worsens
        assert res_low.traffic_delay_minutes <= res_normal.traffic_delay_minutes
        assert res_normal.traffic_delay_minutes < res_heavy.traffic_delay_minutes
        assert res_heavy.traffic_delay_minutes < res_severe.traffic_delay_minutes

    def test_route_preview_already_at_station(self, db_session):
        operator = _make_user(db_session, name="Op Zero", email="opzero@test.com", phone="9000000020", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Zero", email="drzero@test.com", phone="9000000021", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, latitude=12.9500, longitude=77.6000)

        preview = calculate_route_preview(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=12.9500,
            origin_longitude=77.6000,
            traffic_condition="normal",
        )

        assert preview.straight_line_distance_km == 0.0
        assert preview.road_distance_km == 0.0
        assert preview.estimated_travel_time_minutes == 0.0
        assert preview.traffic_delay_minutes == 0.0
        assert len(preview.waypoints) == 1
        assert "destination" in preview.waypoints[0].instruction.lower()

    def test_station_not_found_raises_404(self, db_session):
        driver = _make_user(db_session, name="Dr 404", email="dr404@test.com", phone="9000000030", role=UserRole.DRIVER)
        with pytest.raises(HTTPException) as exc_info:
            calculate_route_preview(
                db=db_session,
                user=driver,
                station_id=999999,
                origin_latitude=12.9716,
                origin_longitude=77.5946,
            )
        assert exc_info.value.status_code == 404


# ===========================================================================
# TC-F2-25: RBAC and Station Visibility
# ===========================================================================


class TestRoutePreviewRBAC:
    def test_driver_cannot_preview_unapproved_station(self, db_session):
        operator = _make_user(db_session, name="Op Unapp", email="opunapp@test.com", phone="9000000040", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Unapp", email="drunapp@test.com", phone="9000000041", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, status=StationStatus.PENDING)

        with pytest.raises(HTTPException) as exc_info:
            calculate_route_preview(db_session, driver, station.id, 12.9, 77.5)
        # Driver receives 404 for unapproved station (REQ-F2-03)
        assert exc_info.value.status_code == 404

    def test_driver_cannot_preview_inactive_station(self, db_session):
        operator = _make_user(db_session, name="Op Inactive", email="opinact@test.com", phone="9000000042", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Inactive", email="drinact@test.com", phone="9000000043", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, status=StationStatus.APPROVED, is_active=False)

        with pytest.raises(HTTPException) as exc_info:
            calculate_route_preview(db_session, driver, station.id, 12.9, 77.5)
        assert exc_info.value.status_code == 404

    def test_operator_can_preview_own_unapproved_station(self, db_session):
        operator = _make_user(db_session, name="Op Own", email="opown@test.com", phone="9000000044", role=UserRole.OPERATOR)
        station = _seed_station(db_session, operator, status=StationStatus.PENDING)

        preview = calculate_route_preview(db_session, operator, station.id, 12.9, 77.5)
        assert preview.station_id == station.id
        assert preview.station_status == "pending"

    def test_foreign_operator_cannot_preview_other_operator_unapproved_station(self, db_session):
        operator_a = _make_user(db_session, name="Op A", email="opa@test.com", phone="9000000045", role=UserRole.OPERATOR)
        operator_b = _make_user(db_session, name="Op B", email="opb@test.com", phone="9000000046", role=UserRole.OPERATOR)
        station_a = _seed_station(db_session, operator_a, status=StationStatus.PENDING)

        with pytest.raises(HTTPException) as exc_info:
            calculate_route_preview(db_session, operator_b, station_a.id, 12.9, 77.5)
        assert exc_info.value.status_code == 403
        assert "Permission denied" in exc_info.value.detail

    def test_admin_can_preview_any_station(self, db_session):
        operator = _make_user(db_session, name="Op AdmTest", email="opadm@test.com", phone="9000000047", role=UserRole.OPERATOR)
        admin = _make_user(db_session, name="Super Admin", email="admin@test.com", phone="9000000048", role=UserRole.ADMIN)
        station = _seed_station(db_session, operator, status=StationStatus.REJECTED, is_active=False)

        preview = calculate_route_preview(db_session, admin, station.id, 12.9, 77.5)
        assert preview.station_id == station.id
        assert preview.station_status == "rejected"
        assert preview.is_active is False


# ===========================================================================
# TC-F2-25: External Routing and Fallback Tests (SR-F2-09)
# ===========================================================================


class TestExternalRoutingAndFallback:
    def test_external_osrm_success(self, db_session):
        operator = _make_user(db_session, name="Op OSRM", email="oposrm@test.com", phone="9000000050", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver OSRM", email="drosrm@test.com", phone="9000000051", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "code": "Ok",
            "routes": [
                {
                    "distance": 8500.0,  # 8.5 km
                    "duration": 900.0,   # 15 minutes
                    "geometry": {
                        "coordinates": [
                            [77.5800, 12.9200],
                            [77.5850, 12.9400],
                            [77.5946, 12.9716],
                        ]
                    },
                    "legs": [
                        {
                            "steps": [
                                {
                                    "maneuver": {
                                        "location": [77.5800, 12.9200],
                                        "instruction": "Head north on Hosur Road",
                                    },
                                    "distance": 3500.0,
                                    "duration": 400.0,
                                },
                                {
                                    "maneuver": {
                                        "location": [77.5946, 12.9716],
                                        "instruction": f"Arrive at {station.name}",
                                    },
                                    "distance": 5000.0,
                                    "duration": 500.0,
                                },
                            ]
                        }
                    ],
                }
            ],
        }

        with patch("httpx.Client.get", return_value=mock_response):
            preview = calculate_route_preview(
                db=db_session,
                user=driver,
                station_id=station.id,
                origin_latitude=12.9200,
                origin_longitude=77.5800,
                traffic_condition="normal",
            )

            assert preview.road_distance_km == 8.5
            assert preview.is_fallback is False
            assert preview.fallback_notice is None
            assert len(preview.route_geometry) == 3
            # Check geometry coordinate conversion from [lon, lat] to [lat, lon]
            assert preview.route_geometry[0] == [12.9200, 77.5800]
            assert preview.route_geometry[-1] == [12.9716, 77.5946]
            assert len(preview.waypoints) == 2

    def test_external_osrm_failure_falls_back_gracefully(self, db_session):
        operator = _make_user(db_session, name="Op Fail", email="opfail@test.com", phone="9000000052", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Fail", email="drfail@test.com", phone="9000000053", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, latitude=12.9716, longitude=77.5946)

        # External service throws connection exception
        with patch("httpx.Client.get", side_effect=Exception("Connection refused")):
            preview = calculate_route_preview(
                db=db_session,
                user=driver,
                station_id=station.id,
                origin_latitude=12.9200,
                origin_longitude=77.5800,
                traffic_condition="heavy",
            )

            # Verifies SR-F2-09 fallback behavior
            assert preview.is_fallback is True
            assert preview.fallback_notice is not None
            assert "temporarily unavailable" in preview.fallback_notice
            assert preview.road_distance_km > 0
            assert preview.estimated_travel_time_minutes > 0
            assert len(preview.route_geometry) >= 2
            assert len(preview.waypoints) >= 2


# ===========================================================================
# TC-F2-25: HTTP Endpoints Integration Tests
# ===========================================================================


class TestRoutePreviewEndpoints:
    def test_sw_architecture_route_preview_query(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op End1", email="opend1@test.com", phone="9000000060", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver End1", email="drend1@test.com", phone="9000000061", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        # GET /api/v1/stations/route-preview?station_id=...&latitude=...&longitude=...&traffic_condition=...
        response = client.get(
            "/api/v1/stations/route-preview",
            params={
                "station_id": station.id,
                "latitude": 12.9200,
                "longitude": 77.5800,
                "traffic_condition": "normal",
            },
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["station_id"] == station.id
        assert data["station_name"] == station.name
        assert data["origin_latitude"] == 12.9200
        assert data["origin_longitude"] == 77.5800
        assert data["road_distance_km"] > 0
        assert data["estimated_travel_time_minutes"] > 0
        assert data["traffic_condition"] == "normal"
        assert isinstance(data["route_geometry"], list)
        assert isinstance(data["waypoints"], list)
        assert "generated_at" in data

    def test_station_path_route_preview(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op End2", email="opend2@test.com", phone="9000000062", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver End2", email="drend2@test.com", phone="9000000063", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        # GET /api/v1/stations/{station_id}/route-preview?latitude=...&longitude=...
        response = client.get(
            f"/api/v1/stations/{station.id}/route-preview",
            params={
                "latitude": 12.9300,
                "longitude": 77.5900,
                "traffic_condition": "heavy",
            },
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["station_id"] == station.id
        assert data["traffic_condition"] == "heavy"

    def test_navigation_module_endpoints(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op Nav", email="opnav@test.com", phone="9000000064", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Nav", email="drnav@test.com", phone="9000000065", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        # GET /api/v1/navigation/route-preview
        resp1 = client.get(
            "/api/v1/navigation/route-preview",
            params={
                "station_id": station.id,
                "latitude": 12.9100,
                "longitude": 77.5700,
            },
            headers=_auth_header(driver),
        )
        assert resp1.status_code == 200
        assert resp1.json()["station_id"] == station.id

        # GET /api/v1/navigation/{station_id}/route-preview
        resp2 = client.get(
            f"/api/v1/navigation/{station.id}/route-preview",
            params={
                "latitude": 12.9100,
                "longitude": 77.5700,
            },
            headers=_auth_header(driver),
        )
        assert resp2.status_code == 200
        assert resp2.json()["station_id"] == station.id

    def test_endpoint_missing_coordinates_fails_422(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op Param", email="opparam@test.com", phone="9000000066", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Param", email="drparam@test.com", phone="9000000067", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        # Missing longitude
        response = client.get(
            f"/api/v1/stations/{station.id}/route-preview",
            params={"latitude": 12.9100},
            headers=_auth_header(driver),
        )
        assert response.status_code == 422

    def test_endpoint_unauthorized_without_token(self, client: TestClient, db_session):
        response = client.get(
            "/api/v1/stations/route-preview",
            params={
                "station_id": 1,
                "latitude": 12.9100,
                "longitude": 77.5700,
            },
        )
        assert response.status_code == 401


# ===========================================================================
# STC-F2-25: System Integration & Lifecycle Test
# ===========================================================================


class TestRoutePreviewSystemLifecycle:
    def test_system_route_preview_full_lifecycle(self, client: TestClient, db_session):
        """
        STC-F2-25 Lifecycle Test:
        1. Operator creates station.
        2. Driver attempts route preview before approval -> receives 404 (REQ-F2-03).
        3. Operator previews their own station -> receives 200 with status 'pending'.
        4. Administrator approves station.
        5. Driver queries route preview with low and severe traffic -> receives 200 with complete preview.
        6. Validates road distance, ETA with traffic, waypoint sequence, and geometry format.
        """
        operator = _make_user(db_session, name="System Op", email="sysop@chargeslot.com", phone="9111111111", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="System Driver", email="sysdr@chargeslot.com", phone="9222222222", role=UserRole.DRIVER)
        admin = _make_user(db_session, name="System Admin", email="sysadm@chargeslot.com", phone="9333333333", role=UserRole.ADMIN)

        # 1. Operator creates station (pending approval)
        station = _seed_station(
            db_session,
            operator,
            name="Electronic City Supercharger",
            address="Phase 1, Electronic City, Bangalore",
            latitude=12.8450,
            longitude=77.6600,
            status=StationStatus.PENDING,
        )

        driver_lat = 12.9350
        driver_lon = 77.6200

        # 2. Driver attempts route preview before approval -> hidden (404)
        resp_unapproved_driver = client.get(
            "/api/v1/stations/route-preview",
            params={"station_id": station.id, "latitude": driver_lat, "longitude": driver_lon},
            headers=_auth_header(driver),
        )
        assert resp_unapproved_driver.status_code == 404

        # 3. Operator previews own pending station -> 200 OK
        resp_op_preview = client.get(
            f"/api/v1/stations/{station.id}/route-preview",
            params={"latitude": driver_lat, "longitude": driver_lon},
            headers=_auth_header(operator),
        )
        assert resp_op_preview.status_code == 200
        assert resp_op_preview.json()["station_status"] == "pending"

        # 4. Administrator approves station
        station.status = StationStatus.APPROVED
        station.reviewed_by_admin_id = admin.id
        db_session.commit()

        # 5. Driver queries route preview with low traffic
        resp_driver_low = client.get(
            "/api/v1/stations/route-preview",
            params={
                "station_id": station.id,
                "latitude": driver_lat,
                "longitude": driver_lon,
                "traffic_condition": "low",
            },
            headers=_auth_header(driver),
        )
        assert resp_driver_low.status_code == 200
        data_low = resp_driver_low.json()
        assert data_low["station_name"] == "Electronic City Supercharger"
        assert data_low["station_status"] == "approved"
        assert data_low["is_active"] is True
        assert data_low["traffic_condition"] == "low"
        assert data_low["road_distance_km"] > 0
        low_time = data_low["estimated_travel_time_minutes"]

        # Driver queries route preview with severe traffic
        resp_driver_severe = client.get(
            "/api/v1/stations/route-preview",
            params={
                "station_id": station.id,
                "latitude": driver_lat,
                "longitude": driver_lon,
                "traffic_condition": "severe",
            },
            headers=_auth_header(driver),
        )
        assert resp_driver_severe.status_code == 200
        data_severe = resp_driver_severe.json()
        assert data_severe["traffic_condition"] == "severe"
        severe_time = data_severe["estimated_travel_time_minutes"]

        # 6. Verify severe traffic ETA is significantly higher than low traffic ETA
        assert severe_time > low_time * 2.0

        # Verify waypoints completeness
        waypoints = data_severe["waypoints"]
        assert len(waypoints) >= 2
        assert waypoints[0]["step_index"] == 0
        assert "depart" in waypoints[0]["instruction"].lower()
        assert waypoints[-1]["step_index"] == len(waypoints) - 1
        assert "electronic city supercharger" in waypoints[-1]["instruction"].lower()

        # Verify route geometry coordinate pairs
        geometry = data_severe["route_geometry"]
        assert len(geometry) >= 2
        assert geometry[0][0] == round(driver_lat, 6)
        assert geometry[0][1] == round(driver_lon, 6)
        assert geometry[-1][0] == round(station.latitude, 6)
        assert geometry[-1][1] == round(station.longitude, 6)
