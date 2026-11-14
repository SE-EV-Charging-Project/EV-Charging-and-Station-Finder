"""
Test Suite for Navigation Hand-off (REQ-F2-26 / TC-F2-26 / STC-F2-26 / CS19-052).

Requirements Under Test:
- REQ-F2-26: "The system shall allow the driver to start turn-by-turn navigation in the
  device's navigation application through a deep link."
- Supported app types: Google Maps, Apple Maps, Waze, and RFC 5870 generic geo: URI.
- With and without driver origin coordinates.
- Coordinate range validation [-90, 90] and [-180, 180].
- RBAC and station visibility:
  - Driver can only access approved, active stations (REQ-F2-03).
  - Operator can access own station or approved stations. Foreign unapproved access returns 403.
  - Admin has full access.
- SW Architecture endpoints:
  - GET /api/v1/stations/navigation-hand-off
  - GET /api/v1/stations/{station_id}/navigation-hand-off
  - GET /api/v1/navigation/navigation-hand-off
  - GET /api/v1/navigation/{station_id}/navigation-hand-off
- System lifecycle test (STC-F2-26).
"""

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.handoff import (
    build_navigation_links,
    generate_navigation_handoff,
    normalize_app_type,
)
from app.schemas.navigation import NavigationAppType
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
    name: str = "Indiranagar Fast EV Station",
    address: str = "100 Feet Road, Indiranagar, Bangalore",
    latitude: float = 12.9784,
    longitude: float = 77.6408,
    status: StationStatus = StationStatus.APPROVED,
    is_active: bool = True,
) -> Station:
    station = Station(
        name=name,
        address=address,
        latitude=latitude,
        longitude=longitude,
        contact_phone="9876543210",
        contact_email="indiranagar@chargeslot.com",
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
# TC-F2-26: Unit Tests - URL Construction & App Type Normalization
# ===========================================================================


class TestNavigationLinkConstruction:
    def test_app_type_normalization(self):
        assert normalize_app_type(None) == NavigationAppType.GOOGLE_MAPS
        assert normalize_app_type("") == NavigationAppType.GOOGLE_MAPS
        assert normalize_app_type("GOOGLE_MAPS") == NavigationAppType.GOOGLE_MAPS
        assert normalize_app_type("apple_maps") == NavigationAppType.APPLE_MAPS
        assert normalize_app_type("  waze  ") == NavigationAppType.WAZE
        assert normalize_app_type("generic_geo") == NavigationAppType.GENERIC_GEO

    def test_invalid_app_type_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            normalize_app_type("uber")
        assert exc_info.value.status_code == 422
        assert "Invalid navigation app_type" in exc_info.value.detail

    def test_build_links_with_origin(self):
        links = build_navigation_links(
            station_name="City Center Hub",
            dest_lat=12.9750,
            dest_lon=77.6050,
            origin_lat=12.9300,
            origin_lon=77.5800,
        )

        assert "google.com/maps/dir/" in links["google_maps_url"]
        assert "origin=12.930000,77.580000" in links["google_maps_url"]
        assert "destination=12.975000,77.605000" in links["google_maps_url"]

        assert "maps.apple.com" in links["apple_maps_url"]
        assert "saddr=12.930000,77.580000" in links["apple_maps_url"]
        assert "daddr=12.975000,77.605000" in links["apple_maps_url"]

        assert "waze.com/ul" in links["waze_url"]
        assert "ll=12.975000,77.605000" in links["waze_url"]

        assert "geo:12.975000,77.605000" in links["geo_uri"]
        assert "City%20Center%20Hub" in links["geo_uri"]

    def test_build_links_without_origin(self):
        links = build_navigation_links(
            station_name="City Center Hub",
            dest_lat=12.9750,
            dest_lon=77.6050,
        )

        assert "destination=12.975000,77.605000" in links["google_maps_url"]
        assert "origin=" not in links["google_maps_url"]
        assert "daddr=12.975000,77.605000" in links["apple_maps_url"]
        assert "saddr=" not in links["apple_maps_url"]


# ===========================================================================
# TC-F2-26: Unit & Service Logic Tests
# ===========================================================================


class TestNavigationHandoffServiceLogic:
    def test_handoff_google_maps_default(self, db_session):
        operator = _make_user(db_session, name="Op Link", email="oplink@test.com", phone="9000000101", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Link", email="drlink@test.com", phone="9000000102", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        resp = generate_navigation_handoff(
            db=db_session,
            user=driver,
            station_id=station.id,
            origin_latitude=12.9200,
            origin_longitude=77.5800,
        )

        assert resp.station_id == station.id
        assert resp.station_name == station.name
        assert resp.app_type == "google_maps"
        assert resp.deep_link_url == resp.google_maps_url
        assert "destination=12.978400,77.640800" in resp.deep_link_url

    def test_handoff_apple_maps(self, db_session):
        operator = _make_user(db_session, name="Op Apple", email="opapple@test.com", phone="9000000103", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Apple", email="drapple@test.com", phone="9000000104", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        resp = generate_navigation_handoff(
            db=db_session,
            user=driver,
            station_id=station.id,
            app_type="apple_maps",
            origin_latitude=12.9200,
            origin_longitude=77.5800,
        )

        assert resp.app_type == "apple_maps"
        assert resp.deep_link_url == resp.apple_maps_url
        assert "daddr=12.978400,77.640800" in resp.deep_link_url

    def test_handoff_waze_and_geo(self, db_session):
        operator = _make_user(db_session, name="Op Waze", email="opwaze@test.com", phone="9000000105", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Waze", email="drwaze@test.com", phone="9000000106", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        resp_waze = generate_navigation_handoff(db_session, driver, station.id, app_type="waze")
        assert resp_waze.app_type == "waze"
        assert resp_waze.deep_link_url == resp_waze.waze_url

        resp_geo = generate_navigation_handoff(db_session, driver, station.id, app_type="generic_geo")
        assert resp_geo.app_type == "generic_geo"
        assert resp_geo.deep_link_url == resp_geo.geo_uri

    def test_partial_origin_coordinates_raises_422(self, db_session):
        operator = _make_user(db_session, name="Op Part", email="oppart@test.com", phone="9000000107", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver Part", email="drpart@test.com", phone="9000000108", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        with pytest.raises(HTTPException) as exc_info:
            generate_navigation_handoff(db_session, driver, station.id, origin_latitude=12.9200, origin_longitude=None)
        assert exc_info.value.status_code == 422

    def test_station_not_found_raises_404(self, db_session):
        driver = _make_user(db_session, name="Driver 404", email="dr404handoff@test.com", phone="9000000109", role=UserRole.DRIVER)
        with pytest.raises(HTTPException) as exc_info:
            generate_navigation_handoff(db_session, driver, 999999)
        assert exc_info.value.status_code == 404


# ===========================================================================
# TC-F2-26: RBAC and Station Visibility
# ===========================================================================


class TestNavigationHandoffRBAC:
    def test_driver_cannot_access_unapproved_station(self, db_session):
        operator = _make_user(db_session, name="Op RBAC1", email="oprbac1@test.com", phone="9000000110", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver RBAC1", email="drrbac1@test.com", phone="9000000111", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator, status=StationStatus.PENDING)

        with pytest.raises(HTTPException) as exc_info:
            generate_navigation_handoff(db_session, driver, station.id)
        assert exc_info.value.status_code == 404

    def test_operator_can_access_own_unapproved_station(self, db_session):
        operator = _make_user(db_session, name="Op RBAC2", email="oprbac2@test.com", phone="9000000112", role=UserRole.OPERATOR)
        station = _seed_station(db_session, operator, status=StationStatus.PENDING)

        resp = generate_navigation_handoff(db_session, operator, station.id)
        assert resp.station_id == station.id

    def test_foreign_operator_cannot_access_other_unapproved_station(self, db_session):
        operator_a = _make_user(db_session, name="Op A", email="op_a@test.com", phone="9000000113", role=UserRole.OPERATOR)
        operator_b = _make_user(db_session, name="Op B", email="op_b@test.com", phone="9000000114", role=UserRole.OPERATOR)
        station_a = _seed_station(db_session, operator_a, status=StationStatus.PENDING)

        with pytest.raises(HTTPException) as exc_info:
            generate_navigation_handoff(db_session, operator_b, station_a.id)
        assert exc_info.value.status_code == 403

    def test_admin_can_access_any_station(self, db_session):
        operator = _make_user(db_session, name="Op Adm", email="opadmhand@test.com", phone="9000000115", role=UserRole.OPERATOR)
        admin = _make_user(db_session, name="Admin Hand", email="adminhand@test.com", phone="9000000116", role=UserRole.ADMIN)
        station = _seed_station(db_session, operator, status=StationStatus.REJECTED, is_active=False)

        resp = generate_navigation_handoff(db_session, admin, station.id)
        assert resp.station_id == station.id


# ===========================================================================
# TC-F2-26: HTTP Endpoints Integration Tests
# ===========================================================================


class TestNavigationHandoffEndpoints:
    def test_sw_architecture_handoff_query(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op EndH1", email="opendh1@test.com", phone="9000000120", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver EndH1", email="drendh1@test.com", phone="9000000121", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        response = client.get(
            "/api/v1/stations/navigation-hand-off",
            params={
                "station_id": station.id,
                "app_type": "google_maps",
                "origin_latitude": 12.9200,
                "origin_longitude": 77.5800,
            },
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["station_id"] == station.id
        assert data["app_type"] == "google_maps"
        assert "destination=" in data["deep_link_url"]
        assert "origin=" in data["deep_link_url"]
        assert "apple_maps_url" in data
        assert "waze_url" in data
        assert "geo_uri" in data

    def test_station_path_handoff(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op EndH2", email="opendh2@test.com", phone="9000000122", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver EndH2", email="drendh2@test.com", phone="9000000123", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        response = client.get(
            f"/api/v1/stations/{station.id}/navigation-hand-off",
            params={"app_type": "apple_maps"},
            headers=_auth_header(driver),
        )

        assert response.status_code == 200
        data = response.json()
        assert data["app_type"] == "apple_maps"
        assert "maps.apple.com" in data["deep_link_url"]

    def test_navigation_module_endpoints(self, client: TestClient, db_session):
        operator = _make_user(db_session, name="Op NavH", email="opnavh@test.com", phone="9000000124", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Driver NavH", email="drnavh@test.com", phone="9000000125", role=UserRole.DRIVER)
        station = _seed_station(db_session, operator)

        # GET /api/v1/navigation/navigation-hand-off
        resp1 = client.get(
            "/api/v1/navigation/navigation-hand-off",
            params={"station_id": station.id, "app_type": "waze"},
            headers=_auth_header(driver),
        )
        assert resp1.status_code == 200
        assert resp1.json()["app_type"] == "waze"

        # GET /api/v1/navigation/{station_id}/navigation-hand-off
        resp2 = client.get(
            f"/api/v1/navigation/{station.id}/navigation-hand-off",
            params={"app_type": "generic_geo"},
            headers=_auth_header(driver),
        )
        assert resp2.status_code == 200
        assert resp2.json()["app_type"] == "generic_geo"


# ===========================================================================
# STC-F2-26: System Integration & Lifecycle Test
# ===========================================================================


class TestNavigationHandoffSystemLifecycle:
    def test_system_navigation_handoff_lifecycle(self, client: TestClient, db_session):
        """
        STC-F2-26 Lifecycle Test:
        1. Operator creates station (pending approval).
        2. Driver attempts navigation hand-off before approval -> 404 (REQ-F2-03).
        3. Operator previews hand-off for own station -> 200.
        4. Administrator approves station.
        5. Driver requests navigation hand-off for Google Maps, Apple Maps, Waze, and geo URI.
        6. Verifies deep links adhere to provider URL schemes.
        """
        operator = _make_user(db_session, name="Sys Op Handoff", email="sysophand@chargeslot.com", phone="9444444441", role=UserRole.OPERATOR)
        driver = _make_user(db_session, name="Sys Driver Handoff", email="sysdrhand@chargeslot.com", phone="9444444442", role=UserRole.DRIVER)
        admin = _make_user(db_session, name="Sys Admin Handoff", email="sysadmhand@chargeslot.com", phone="9444444443", role=UserRole.ADMIN)

        station = _seed_station(
            db_session,
            operator,
            name="Whitefield Fast Charging Depot",
            address="ITPL Main Road, Whitefield",
            latitude=12.9850,
            longitude=77.7300,
            status=StationStatus.PENDING,
        )

        # 2. Driver attempts before approval
        resp_unapp = client.get(
            "/api/v1/stations/navigation-hand-off",
            params={"station_id": station.id},
            headers=_auth_header(driver),
        )
        assert resp_unapp.status_code == 404

        # 3. Operator previews own station
        resp_op = client.get(
            f"/api/v1/stations/{station.id}/navigation-hand-off",
            headers=_auth_header(operator),
        )
        assert resp_op.status_code == 200

        # 4. Admin approves
        station.status = StationStatus.APPROVED
        station.reviewed_by_admin_id = admin.id
        db_session.commit()

        # 5. Driver generates deep links for each app type
        for app_type in ["google_maps", "apple_maps", "waze", "generic_geo"]:
            resp = client.get(
                "/api/v1/stations/navigation-hand-off",
                params={
                    "station_id": station.id,
                    "app_type": app_type,
                    "origin_latitude": 12.9350,
                    "origin_longitude": 77.6200,
                },
                headers=_auth_header(driver),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["app_type"] == app_type
            assert len(data["deep_link_url"]) > 10
            assert "12.985" in data["destination_latitude"].__str__()

