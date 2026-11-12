"""
Unit and Integration Tests for Availability Markers
Requirement: REQ-F2-08 (Availability markers)
Story ID: CS19-034
Test Case ID: TC-F2-08
System Test Case ID: STC-F2-08
Architecture Ref: discovery/views.py / GET & PATCH /api/v1/stations/availability-markers
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
from app.schemas.discovery import MarkerColor
from app.discovery.views import (
    compute_station_marker,
    get_station_markers,
    HEX_GREEN,
    HEX_AMBER,
    HEX_RED,
    HEX_GREY,
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
        name="Map Driver",
        email="driver.markers@example.com",
        phone="+919876570001",
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
        email="operator.markers@example.com",
        phone="+919876570002",
        hashed_password=hash_password("OperatorPass123!"),
        role=UserRole.OPERATOR,
        operator_organization="ChargeNet India",
        is_verified=True,
        is_active=True,
    )
    db_session.add(op)
    db_session.commit()
    db_session.refresh(op)
    return op


@pytest.fixture
def marker_test_stations(db_session: Session, operator_user: User):
    """
    Creates test stations representing all four availability marker states:
    1. Green Station: All connectors available (2/2)
    2. Amber Station: Partially available (1 available, 1 occupied) (1/2)
    3. Red Station: Fully occupied / reserved (0 available, 2 occupied) (0/2)
    4. Grey Station: Offline / all faulted (0 available, 2 faulted) (0/2)
    5. Empty Station: 0 chargers / 0 connectors (0/0) -> Grey
    6. Pending Station: Should be hidden from driver map
    """
    # 1. Green Station (All Available)
    s_green = Station(
        operator_id=operator_user.id,
        name="Green Power Hub",
        address="10 Green Street, Bengaluru",
        contact_phone="+919876570010",
        latitude=12.9716,
        longitude=77.5946,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_green)
    db_session.flush()
    c_g = Charger(station_id=s_green.id, power_kw=50.0, current_type=CurrentType.DC, gateway_id="GW-G-01", is_active=True)
    db_session.add(c_g)
    db_session.flush()
    db_session.add_all([
        Connector(charger_id=c_g.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE),
        Connector(charger_id=c_g.id, connector_type=ConnectorType.CHADEMO, status=ConnectorStatus.AVAILABLE),
    ])

    # 2. Amber Station (Partially Available: 1 free, 1 busy)
    s_amber = Station(
        operator_id=operator_user.id,
        name="Amber Mixed Hub",
        address="20 Amber Avenue, Bengaluru",
        contact_phone="+919876570020",
        latitude=13.0100,
        longitude=77.6400,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_amber)
    db_session.flush()
    c_a = Charger(station_id=s_amber.id, power_kw=60.0, current_type=CurrentType.DC, gateway_id="GW-A-01", is_active=True)
    db_session.add(c_a)
    db_session.flush()
    db_session.add_all([
        Connector(charger_id=c_a.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.AVAILABLE),
        Connector(charger_id=c_a.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.OCCUPIED),
    ])

    # 3. Red Station (Fully Occupied: 0 free, 1 occupied, 1 reserved)
    s_red = Station(
        operator_id=operator_user.id,
        name="Red Busy Hub",
        address="30 Red Road, Bengaluru",
        contact_phone="+919876570030",
        latitude=12.9800,
        longitude=77.6100,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_red)
    db_session.flush()
    c_r = Charger(station_id=s_red.id, power_kw=100.0, current_type=CurrentType.DC, gateway_id="GW-R-01", is_active=True)
    db_session.add(c_r)
    db_session.flush()
    db_session.add_all([
        Connector(charger_id=c_r.id, connector_type=ConnectorType.CCS2, status=ConnectorStatus.OCCUPIED),
        Connector(charger_id=c_r.id, connector_type=ConnectorType.TYPE_2, status=ConnectorStatus.RESERVED),
    ])

    # 4. Grey Station (Offline / Faulted: 0 free, 2 faulted)
    s_grey = Station(
        operator_id=operator_user.id,
        name="Grey Offline Hub",
        address="40 Grey Boulevard, Bengaluru",
        contact_phone="+919876570040",
        latitude=12.9850,
        longitude=77.6200,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_grey)
    db_session.flush()
    c_gr = Charger(station_id=s_grey.id, power_kw=50.0, current_type=CurrentType.AC, gateway_id="GW-GR-01", is_active=True)
    db_session.add(c_gr)
    db_session.flush()
    db_session.add_all([
        Connector(charger_id=c_gr.id, connector_type=ConnectorType.TYPE_2, status=ConnectorStatus.FAULTED),
        Connector(charger_id=c_gr.id, connector_type=ConnectorType.TYPE_2, status=ConnectorStatus.OFFLINE),
    ])

    # 5. Empty Station (0 chargers)
    s_empty = Station(
        operator_id=operator_user.id,
        name="Empty Station",
        address="50 Empty Way, Bengaluru",
        contact_phone="+919876570050",
        latitude=12.9900,
        longitude=77.6300,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(s_empty)

    # 6. Pending Station (Unapproved: MUST NOT appear on map)
    s_pending = Station(
        operator_id=operator_user.id,
        name="Pending Approval Hub",
        address="60 Secret Way, Bengaluru",
        contact_phone="+919876570060",
        latitude=12.9720,
        longitude=77.5950,
        status=StationStatus.PENDING,
        is_active=True,
    )
    db_session.add(s_pending)

    db_session.commit()
    return {
        "green": s_green,
        "amber": s_amber,
        "red": s_red,
        "grey": s_grey,
        "empty": s_empty,
        "pending": s_pending,
    }


# =========================================================================
# TC-F2-08: Colour-Coded Availability Markers Acceptance Tests
# =========================================================================

def test_tc_f2_08_colour_coding_and_text_labels(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
):
    """
    REQ-F2-08: Verify that each station marker is colour-coded by availability
    and displays the number of available connectors out of the total with text labels.
    - Green: Available (2/2)
    - Amber: Partially Available (1/2)
    - Red: Occupied (0/2)
    - Grey: Offline (0/2) and Empty (0/0)
    """
    token = make_token(driver_user)

    res = client.get(
        "/api/v1/stations/availability-markers",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    markers_by_id = {m["station_id"]: m for m in data["markers"]}

    # 1. Green Marker verification
    g = markers_by_id[marker_test_stations["green"].id]
    assert g["color_code"] == MarkerColor.GREEN.value
    assert g["hex_color"] == HEX_GREEN
    assert g["status_label"] == "Available"
    assert g["total_connectors"] == 2
    assert g["available_connectors"] == 2
    assert g["badge_text"] == "2/2 Available"
    assert g["is_operational"] is True

    # 2. Amber Marker verification
    a = markers_by_id[marker_test_stations["amber"].id]
    assert a["color_code"] == MarkerColor.AMBER.value
    assert a["hex_color"] == HEX_AMBER
    assert a["status_label"] == "Partially Available"
    assert a["total_connectors"] == 2
    assert a["available_connectors"] == 1
    assert a["occupied_connectors"] == 1
    assert a["badge_text"] == "1/2 Available"
    assert a["is_operational"] is True

    # 3. Red Marker verification
    r = markers_by_id[marker_test_stations["red"].id]
    assert r["color_code"] == MarkerColor.RED.value
    assert r["hex_color"] == HEX_RED
    assert r["status_label"] == "Occupied"
    assert r["total_connectors"] == 2
    assert r["available_connectors"] == 0
    assert r["occupied_connectors"] == 1
    assert r["reserved_connectors"] == 1
    assert r["badge_text"] == "0/2 Occupied"
    assert r["is_operational"] is True

    # 4. Grey Marker verification (Faulted/Offline)
    gr = markers_by_id[marker_test_stations["grey"].id]
    assert gr["color_code"] == MarkerColor.GREY.value
    assert gr["hex_color"] == HEX_GREY
    assert gr["status_label"] == "Offline"
    assert gr["total_connectors"] == 2
    assert gr["available_connectors"] == 0
    assert gr["offline_connectors"] == 2
    assert gr["badge_text"] == "0/2 Offline"
    assert gr["is_operational"] is False

    # 5. Empty Station verification (0 chargers)
    em = markers_by_id[marker_test_stations["empty"].id]
    assert em["color_code"] == MarkerColor.GREY.value
    assert em["total_connectors"] == 0
    assert em["badge_text"] == "0/0 Offline"


def test_tc_f2_08_single_station_availability_marker(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
):
    """
    Test retrieving marker for a single station via query param and path param.
    """
    token = make_token(driver_user)
    green_id = marker_test_stations["green"].id

    # 1. Via query param GET /stations/availability-markers?station_id={id}
    res_q = client.get(
        f"/api/v1/stations/availability-markers?station_id={green_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_q.status_code == 200
    assert len(res_q.json()["markers"]) == 1
    assert res_q.json()["markers"][0]["color_code"] == "green"

    # 2. Via path param GET /stations/{id}/availability-marker
    res_p = client.get(
        f"/api/v1/stations/{green_id}/availability-marker",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_p.status_code == 200
    assert res_p.json()["color_code"] == "green"
    assert res_p.json()["badge_text"] == "2/2 Available"


def test_tc_f2_08_batch_patch_and_post_markers(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
):
    """
    Test SW Architecture Route PATCH /api/v1/stations/availability-markers and POST alias.
    """
    token = make_token(driver_user)
    sids = [marker_test_stations["green"].id, marker_test_stations["red"].id]

    # PATCH /api/v1/stations/availability-markers
    res_patch = client.patch(
        "/api/v1/stations/availability-markers",
        json={"station_ids": sids},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_patch.status_code == 200
    assert res_patch.json()["total"] == 2
    colors = {m["color_code"] for m in res_patch.json()["markers"]}
    assert colors == {"green", "red"}

    # POST /api/v1/stations/availability-markers
    res_post = client.post(
        "/api/v1/stations/availability-markers",
        json={"station_ids": sids},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_post.status_code == 200
    assert res_post.json()["total"] == 2


def test_tc_f2_08_markers_geospatial_radius_filter(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
):
    """
    Test GET /api/v1/stations/availability-markers with latitude, longitude, and radius_km.
    """
    token = make_token(driver_user)
    lat = 12.9716
    lon = 77.5946

    # Radius 1.0 km: only Green (~0 km away) is within 1 km
    res = client.get(
        f"/api/v1/stations/availability-markers?latitude={lat}&longitude={lon}&radius_km=1.0",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    assert res.json()["total"] == 1
    assert res.json()["markers"][0]["station_id"] == marker_test_stations["green"].id


def test_tc_f2_08_out_of_service_charger_updates_marker_availability(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
    db_session: Session,
):
    """
    When a charger is marked out-of-service, its connectors are excluded from
    active available connectors, transitioning the marker from Green to Amber or Red.
    """
    token = make_token(driver_user)
    s_green = marker_test_stations["green"]

    # Invalidate charger: mark out of service
    charger = db_session.query(Charger).filter(Charger.station_id == s_green.id).first()
    charger.is_out_of_service = True
    db_session.commit()

    res = client.get(
        f"/api/v1/stations/{s_green.id}/availability-marker",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    data = res.json()
    # With its only charger out-of-service, station has 0 operational connectors -> Grey
    assert data["color_code"] == MarkerColor.GREY.value
    assert data["status_label"] == "Offline"
    assert data["is_operational"] is False


def test_tc_f2_08_unapproved_stations_hidden_from_markers(
    client: TestClient,
    driver_user: User,
    marker_test_stations: dict,
):
    """
    REQ-F2-03: Pending/unapproved stations must never appear on map markers,
    and attempting to query them directly returns 404.
    """
    token = make_token(driver_user)
    pending_id = marker_test_stations["pending"].id

    # 1. Not in all markers list
    res_all = client.get(
        "/api/v1/stations/availability-markers",
        headers={"Authorization": f"Bearer {token}"},
    )
    ids = [m["station_id"] for m in res_all.json()["markers"]]
    assert pending_id not in ids

    # 2. Direct query by ID returns 404
    res_direct = client.get(
        f"/api/v1/stations/{pending_id}/availability-marker",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res_direct.status_code == 404


# =========================================================================
# STC-F2-08: Security and RBAC Tests
# =========================================================================

def test_stc_f2_08_unauthenticated_request_rejected(client: TestClient):
    """
    Unauthenticated request must return 401 Unauthorized.
    """
    res = client.get("/api/v1/stations/availability-markers")
    assert res.status_code == 401


# =========================================================================
# Direct Unit Tests: Marker Computation Logic (discovery/views.py)
# =========================================================================

def test_tc_f2_08_compute_station_marker_unit():
    """
    Direct unit test for compute_station_marker covering all colour and label states.
    """
    # Inactive station
    s_inact = Station(name="Inactive", status=StationStatus.APPROVED, is_active=False, latitude=0, longitude=0)
    m_inact = compute_station_marker(s_inact)
    assert m_inact.color_code == MarkerColor.GREY
    assert m_inact.status_label == "Offline"
    assert m_inact.is_operational is False
