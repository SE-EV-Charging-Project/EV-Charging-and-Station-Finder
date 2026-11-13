"""
Unit and Integration Tests for Vehicle Battery Level Input.
Requirements: REQ-F3-01, REQ-F3-02, REQ-F3-07, REQ-F3-08, REQ-F3-09
Stories: CS19-055, CS19-056, CS19-061, CS19-062, CS19-063
Test Case IDs: TC-F3-01, TC-F3-02, TC-F3-07, TC-F3-08, TC-F3-09
System Test Case ID: STC-F3-01
"""

from datetime import datetime, time, timedelta, timezone
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.booking.battery import (
    compute_charging_cost,
    compute_charging_time_minutes,
    compute_slot_length_minutes,
    compute_usable_range,
    compute_estimated_range,
    compute_energy_required,
    enter_battery_level,
    get_vehicle_battery,
)
from app.booking.validators import validate_battery_level_input, get_battery_rules
from app.models.audit import AuditLog
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.station import Station, StationStatus
from app.models.maintenance import MaintenanceWindow
from app.models.booking import Booking, BookingStatus
from app.models.booking_slot_claim import BookingSlotClaim
from app.services.booking_service import BookingService
from app.services.vehicle_service import VehicleService
from app.utils.security import hash_password, create_access_token


def make_token(user: User) -> str:
    return create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value if isinstance(user.role, UserRole) else str(user.role),
    })


@pytest.fixture
def driver_alice(db_session: Session) -> User:
    user = User(
        name="Alice Driver",
        email="alice.driver@example.com",
        phone="+919876543201",
        hashed_password=hash_password("AliceSecure123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
        default_target_battery=80,
        low_battery_threshold=20,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def driver_bob(db_session: Session) -> User:
    user = User(
        name="Bob Driver",
        email="bob.driver@example.com",
        phone="+919876543202",
        hashed_password=hash_password("BobSecure123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
        default_target_battery=85,
        low_battery_threshold=25,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def operator_charlie(db_session: Session) -> User:
    user = User(
        name="Charlie Operator",
        email="charlie.operator@example.com",
        phone="+919876543203",
        hashed_password=hash_password("CharlieOp123!"),
        role=UserRole.OPERATOR,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def admin_dave(db_session: Session) -> User:
    user = User(
        name="Dave Admin",
        email="dave.admin@example.com",
        phone="+919876543204",
        hashed_password=hash_password("DaveAdmin123!"),
        role=UserRole.ADMIN,
        is_verified=True,
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def alice_vehicle(db_session: Session, driver_alice: User) -> Vehicle:
    v = Vehicle(
        user_id=driver_alice.id,
        make="Tata",
        model="Nexon EV",
        battery_kwh=40.5,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        registration_no="KA01EV1111",
        is_default=True,
        current_soc=None,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


@pytest.fixture
def bob_vehicle(db_session: Session, driver_bob: User) -> Vehicle:
    v = Vehicle(
        user_id=driver_bob.id,
        make="MG",
        model="ZS EV",
        battery_kwh=50.3,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.4,
        max_dc_kw=80.0,
        consumption_kwh_100km=16.5,
        registration_no="MH02EV2222",
        is_default=True,
        current_soc=50,
    )
    db_session.add(v)
    db_session.commit()
    db_session.refresh(v)
    return v


# =========================================================================
# TC-F3-01: Unit Tests for Calculation Rules (Appendix B.1 & B.2)
# =========================================================================

def test_tc_f3_01_usable_range_calculations():
    """
    Test usable driving range calculation:
    max(0, (SoC_now - reserve) / 100 * battery_kWh) / (consumption_kWh_per_100km / 100), reserve = 10%.
    """
    # Tata Nexon: 40.5 kWh, 15 kWh/100km (factor = 0.15)
    # 1. At 100% SoC: (100 - 10) / 100 * 40.5 / 0.15 = 0.9 * 40.5 / 0.15 = 243.0 km
    assert compute_usable_range(40.5, 15.0, 100) == 243.0

    # 2. At 50% SoC: (50 - 10) / 100 * 40.5 / 0.15 = 0.4 * 40.5 / 0.15 = 108.0 km
    assert compute_usable_range(40.5, 15.0, 50) == 108.0

    # 3. At 10% SoC (exactly reserve): usable range must be 0.0 km
    assert compute_usable_range(40.5, 15.0, 10) == 0.0

    # 4. Below reserve (e.g. 5% SoC): usable range must be capped at 0.0 km
    assert compute_usable_range(40.5, 15.0, 5) == 0.0
    assert compute_usable_range(40.5, 15.0, 0) == 0.0

    # 5. Invalid battery specs return 0.0
    assert compute_usable_range(0.0, 15.0, 50) == 0.0
    assert compute_usable_range(40.5, 0.0, 50) == 0.0


def test_tc_f3_01_estimated_range_calculations():
    """
    Test estimated driving range calculation without reserve deduction.
    """
    # 40.5 kWh / 0.15 = 270.0 km at 100%
    assert compute_estimated_range(40.5, 15.0, 100) == 270.0
    assert compute_estimated_range(40.5, 15.0, 50) == 135.0
    assert compute_estimated_range(40.5, 15.0, None) == 270.0


def test_tc_f3_01_energy_required_calculations():
    """
    Test energy required in kWh:
    (target_soc - current_soc) / 100 * battery_kWh / 0.90 efficiency.
    """
    # 40.5 kWh, from 20% to 80% (60% delta):
    # 0.60 * 40.5 / 0.90 = 24.3 / 0.90 = 27.0 kWh
    assert compute_energy_required(40.5, current_soc=20, target_soc=80, efficiency=0.90) == 27.0

    # From 80% to 80%: 0.0 kWh
    assert compute_energy_required(40.5, current_soc=80, target_soc=80) == 0.0

    # When current_soc exceeds target_soc: 0.0 kWh
    assert compute_energy_required(40.5, current_soc=90, target_soc=80) == 0.0


def test_tc_f3_01_validation_rules_and_boundary_checks():
    """
    Unit test validator function validate_battery_level_input.
    """
    # Valid values
    soc, target = validate_battery_level_input(50, 80)
    assert soc == 50
    assert target == 80

    # Boundary: 0% and 100%
    soc0, _ = validate_battery_level_input(0)
    assert soc0 == 0
    soc100, _ = validate_battery_level_input(100)
    assert soc100 == 100

    # Fractional percentages are invalid because SoC is an integer percentage.
    with pytest.raises(Exception) as exc_float:
        validate_battery_level_input(45.6)
    assert "integer" in str(exc_float.value).lower()

    # Out of range: < 0
    with pytest.raises(Exception) as exc:
        validate_battery_level_input(-1)
    assert "between 0% and 100%" in str(exc.value)

    # Out of range: > 100
    with pytest.raises(Exception) as exc2:
        validate_battery_level_input(101)
    assert "between 0% and 100%" in str(exc2.value)

    # Missing / None
    with pytest.raises(Exception) as exc3:
        validate_battery_level_input(None)
    assert "mandatory" in str(exc3.value).lower()

    # Non-numeric
    with pytest.raises(Exception) as exc4:
        validate_battery_level_input("full")
    assert "numeric" in str(exc4.value).lower()


@pytest.fixture
def alice_station(db_session: Session, driver_alice: User) -> Station:
    station = Station(
        operator_id=driver_alice.id,
        name="Estimate Test Station",
        address="1 Test Road",
        latitude=12.9716,
        longitude=77.5946,
        contact_phone="+919876543205",
        price_per_kwh=8.5,
        operating_hours="08:00 - 20:00",
        status=StationStatus.APPROVED,
    )
    db_session.add(station)
    db_session.commit()
    db_session.refresh(station)
    return station


@pytest.fixture
def alice_charger(db_session: Session, alice_station: Station) -> Charger:
    charger = Charger(
        station_id=alice_station.id,
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="estimate-test-gateway",
    )
    db_session.add(charger)
    db_session.commit()
    db_session.refresh(charger)
    return charger


@pytest.fixture
def alice_connector(db_session: Session, alice_charger: Charger) -> Connector:
    connector = Connector(
        charger_id=alice_charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add(connector)
    db_session.commit()
    db_session.refresh(connector)
    return connector


def test_tc_f3_02_rejects_fractional_battery_and_target_percentages(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    token = make_token(driver_alice)
    headers = {"Authorization": f"Bearer {token}"}
    for payload in (
        {"vehicle_id": alice_vehicle.id, "battery_level": 45.6},
        {"vehicle_id": alice_vehicle.id, "battery_level": 45, "target_soc": 80.5},
    ):
        response = client.post(
            "/api/v1/bookings/battery-level-input",
            json=payload,
            headers=headers,
        )
        assert response.status_code == 422
    assert alice_vehicle.current_soc is None


def test_tc_f3_02_rejects_non_finite_and_boolean_battery_percentages():
    for value in (True, float("nan"), float("inf")):
        with pytest.raises(HTTPException):
            validate_battery_level_input(value)


def test_tc_f3_07_charging_time_calculation_validates_power_and_energy():
    assert compute_charging_time_minutes(27.0, 30.0) == 54.0
    assert compute_charging_time_minutes(0.0, 30.0) == 0.0
    with pytest.raises(HTTPException):
        compute_charging_time_minutes(1.0, 0.0)
    with pytest.raises(HTTPException):
        compute_charging_time_minutes(float("nan"), 30.0)


def test_tc_f3_08_slot_length_rounds_up_to_15_minute_boundaries():
    assert compute_slot_length_minutes(0) == 0
    assert compute_slot_length_minutes(1) == 15
    assert compute_slot_length_minutes(15) == 15
    assert compute_slot_length_minutes(15.1) == 30
    assert compute_slot_length_minutes(54) == 60

    for invalid_time in (-1, float("nan"), float("inf"), True):
        with pytest.raises(HTTPException):
            compute_slot_length_minutes(invalid_time)


def test_tc_f3_09_charging_cost_uses_energy_and_station_tariff():
    assert compute_charging_cost(27.0, 8.5) == 229.5
    assert compute_charging_cost(0.0, 8.5) == 0.0
    for invalid_value in (-1, float("nan"), float("inf"), True):
        with pytest.raises(HTTPException):
            compute_charging_cost(invalid_value, 8.5)
        with pytest.raises(HTTPException):
            compute_charging_cost(27.0, invalid_value)


def test_tc_f3_07_charging_time_uses_effective_vehicle_and_charger_power(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_charger: Charger,
):
    alice_vehicle.current_soc = 20
    db_session.commit()

    response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={
            "vehicle_id": alice_vehicle.id,
            "charger_id": alice_charger.id,
            "target_soc": 80,
        },
        headers={"Authorization": f"Bearer {make_token(driver_alice)}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "vehicle_id": alice_vehicle.id,
        "charger_id": alice_charger.id,
        "current_soc": 20,
        "target_soc": 80,
        "energy_required_kwh": 27.0,
        "effective_charging_power_kw": 30.0,
        "estimated_charging_time_minutes": 54.0,
        "slot_length_minutes": 60,
        "message": "Charging time estimate calculated successfully.",
    }

    alice_charger.power_kw = 100.0
    db_session.commit()
    vehicle_limited_response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={
            "vehicle_id": alice_vehicle.id,
            "charger_id": alice_charger.id,
            "target_soc": 80,
        },
        headers={"Authorization": f"Bearer {make_token(driver_alice)}"},
    )
    assert vehicle_limited_response.status_code == 200
    assert vehicle_limited_response.json()["effective_charging_power_kw"] == 50.0
    assert vehicle_limited_response.json()["estimated_charging_time_minutes"] == 32.4
    assert vehicle_limited_response.json()["slot_length_minutes"] == 45

    alice_charger.current_type = CurrentType.AC
    alice_charger.power_kw = 22.0
    db_session.commit()
    ac_response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={
            "vehicle_id": alice_vehicle.id,
            "charger_id": alice_charger.id,
            "target_soc": 80,
        },
        headers={"Authorization": f"Bearer {make_token(driver_alice)}"},
    )
    assert ac_response.status_code == 200
    assert ac_response.json()["effective_charging_power_kw"] == 7.2
    assert ac_response.json()["estimated_charging_time_minutes"] == 225.0
    assert ac_response.json()["slot_length_minutes"] == 225


def test_tc_f3_09_cost_estimate_uses_station_tariff_and_checks_ownership(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    bob_vehicle: Vehicle,
):
    alice_vehicle.current_soc = 20
    db_session.commit()
    headers = {"Authorization": f"Bearer {make_token(driver_alice)}"}
    payload = {
        "vehicle_id": alice_vehicle.id,
        "station_id": alice_station.id,
        "target_soc": 80,
    }

    response = client.post(
        "/api/v1/bookings/cost-estimate",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json() == {
        "vehicle_id": alice_vehicle.id,
        "station_id": alice_station.id,
        "current_soc": 20,
        "target_soc": 80,
        "energy_required_kwh": 27.0,
        "price_per_kwh": 8.5,
        "estimated_cost": 229.5,
        "currency": "INR",
        "message": "Charging cost estimate calculated successfully.",
    }

    foreign_vehicle_response = client.post(
        "/api/v1/bookings/cost-estimate",
        json={**payload, "vehicle_id": bob_vehicle.id},
        headers=headers,
    )
    assert foreign_vehicle_response.status_code == 403

    missing_station_response = client.post(
        "/api/v1/bookings/cost-estimate",
        json={**payload, "station_id": 999999},
        headers=headers,
    )
    assert missing_station_response.status_code == 404

    invalid_target_response = client.post(
        "/api/v1/bookings/cost-estimate",
        json={**payload, "target_soc": 101},
        headers=headers,
    )
    assert invalid_target_response.status_code == 422

    alice_vehicle.current_soc = None
    db_session.commit()
    missing_soc_response = client.post(
        "/api/v1/bookings/cost-estimate",
        json=payload,
        headers=headers,
    )
    assert missing_soc_response.status_code == 422

    alice_vehicle.current_soc = 20
    alice_station.price_per_kwh = None
    db_session.commit()
    missing_tariff_response = client.post(
        "/api/v1/bookings/cost-estimate",
        json=payload,
        headers=headers,
    )
    assert missing_tariff_response.status_code == 409


def test_tc_f3_10_recommended_slots_rank_by_start_then_tariff_and_duration(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    alice_connector: Connector,
):
    alice_vehicle.current_soc = 20
    alice_connector.status = ConnectorStatus.OCCUPIED
    cheaper_station = Station(
        operator_id=driver_alice.id,
        name="Cheaper Estimate Station",
        address="2 Test Road",
        latitude=12.972,
        longitude=77.595,
        contact_phone="+919876543206",
        price_per_kwh=5.0,
        operating_hours="08:00 - 20:00",
        status=StationStatus.APPROVED,
    )
    db_session.add(cheaper_station)
    db_session.commit()
    cheaper_charger = Charger(
        station_id=cheaper_station.id,
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="cheaper-estimate-gateway",
    )
    db_session.add(cheaper_charger)
    db_session.commit()
    db_session.refresh(cheaper_charger)
    db_session.add(
        Connector(
            charger_id=cheaper_charger.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    db_session.commit()
    slower_charger = Charger(
        station_id=cheaper_station.id,
        power_kw=15.0,
        current_type=CurrentType.DC,
        gateway_id="slower-estimate-gateway",
    )
    db_session.add(slower_charger)
    db_session.commit()
    db_session.refresh(slower_charger)
    db_session.add(
        Connector(
            charger_id=slower_charger.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    db_session.commit()

    slot_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    response = client.get(
        "/api/v1/bookings/recommended-slots",
        params={
            "vehicle_id": alice_vehicle.id,
            "date": slot_date.isoformat(),
            "target_soc": 80,
            "limit": 4,
        },
        headers={"Authorization": f"Bearer {make_token(driver_alice)}"},
    )

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["total"] > len(data["items"])
    assert [item["rank"] for item in data["items"]] == [1, 2, 3, 4]
    first_start = datetime.fromisoformat(
        data["items"][0]["start_time"].replace("Z", "+00:00")
    )
    second_start = datetime.fromisoformat(
        data["items"][1]["start_time"].replace("Z", "+00:00")
    )
    assert first_start == second_start
    assert data["items"][0]["station_id"] == cheaper_station.id
    assert data["items"][0]["charger_id"] == cheaper_charger.id
    assert data["items"][1]["charger_id"] == slower_charger.id
    assert data["items"][0]["price_per_kwh"] <= data["items"][1]["price_per_kwh"]
    assert data["items"][0]["price_per_kwh"] == 5.0
    assert data["items"][1]["price_per_kwh"] == 5.0
    assert data["items"][0]["slot_length_minutes"] < data["items"][1]["slot_length_minutes"]
    assert data["items"][0]["slot_length_minutes"] == 60
    assert data["items"][0]["estimated_cost"] == 135.0
    assert alice_station.id in {item["station_id"] for item in data["items"]}


def test_tc_f3_11_manual_slot_booking_rejects_foreign_vehicle_and_overlaps(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    alice_charger: Charger,
    alice_connector: Connector,
    bob_vehicle: Vehicle,
):
    alice_vehicle.current_soc = 20
    db_session.commit()
    slot_date = datetime.now(timezone.utc).date() + timedelta(days=1)
    start_time = datetime.combine(slot_date, time(9, 0), tzinfo=timezone.utc)
    payload = {
        "station_id": alice_station.id,
        "charger_id": alice_charger.id,
        "vehicle_id": alice_vehicle.id,
        "start_time": start_time.isoformat(),
        "target_soc": 80,
    }
    headers = {"Authorization": f"Bearer {make_token(driver_alice)}"}

    wrong_connector_charger = Charger(
        station_id=alice_station.id,
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="wrong-connector-gateway",
    )
    db_session.add(wrong_connector_charger)
    db_session.commit()
    db_session.refresh(wrong_connector_charger)
    db_session.add(
        Connector(
            charger_id=wrong_connector_charger.id,
            connector_type=ConnectorType.GBT,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    maintenance_window = MaintenanceWindow(
        station_id=alice_station.id,
        charger_id=alice_charger.id,
        title="Slot test maintenance",
        start_time=start_time,
        end_time=start_time + timedelta(minutes=60),
        created_by_user_id=driver_alice.id,
    )
    db_session.add(maintenance_window)
    db_session.commit()

    maintenance_response = client.post(
        "/api/v1/bookings/manual-slot",
        json=payload,
        headers=headers,
    )
    assert maintenance_response.status_code == 409
    db_session.delete(maintenance_window)
    db_session.commit()

    incompatible_response = client.post(
        "/api/v1/bookings/manual-slot",
        json={**payload, "charger_id": wrong_connector_charger.id},
        headers=headers,
    )
    assert incompatible_response.status_code == 422

    response = client.post(
        "/api/v1/bookings/manual-slot",
        json=payload,
        headers=headers,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "Confirmed"
    assert response.json()["slot_length_minutes"] == 60
    assert (
        db_session.query(BookingSlotClaim)
        .filter(BookingSlotClaim.booking_id == response.json()["booking_id"])
        .count()
        == 4
    )
    actual_end_time = datetime.fromisoformat(
        response.json()["end_time"].replace("Z", "+00:00")
    )
    assert actual_end_time == start_time + timedelta(minutes=60)

    overlap_response = client.post(
        "/api/v1/bookings/manual-slot",
        json={**payload, "start_time": (start_time + timedelta(minutes=45)).isoformat()},
        headers=headers,
    )
    assert overlap_response.status_code == 409

    foreign_vehicle_response = client.post(
        "/api/v1/bookings/manual-slot",
        json={**payload, "vehicle_id": bob_vehicle.id},
        headers=headers,
    )
    assert foreign_vehicle_response.status_code == 403


def test_tc_f3_12_slot_hold_expires_after_five_minutes_and_blocks_booking(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    alice_charger: Charger,
    alice_connector: Connector,
):
    alice_vehicle.current_soc = 20
    db_session.commit()
    start_time = datetime.combine(
        datetime.now(timezone.utc).date() + timedelta(days=1),
        time(9, 0),
        tzinfo=timezone.utc,
    )
    payload = {
        "station_id": alice_station.id,
        "charger_id": alice_charger.id,
        "vehicle_id": alice_vehicle.id,
        "start_time": start_time.isoformat(),
        "target_soc": 80,
    }
    headers = {"Authorization": f"Bearer {make_token(driver_alice)}"}
    response = client.post(
        "/api/v1/bookings/hold-slot",
        json=payload,
        headers=headers,
    )

    assert response.status_code == 201, response.text
    hold = response.json()
    assert hold["status"] == BookingStatus.HELD.value
    expires_at = datetime.fromisoformat(hold["hold_expires_at"].replace("Z", "+00:00"))
    assert timedelta(minutes=4, seconds=59) <= expires_at - datetime.now(timezone.utc)
    assert expires_at - datetime.now(timezone.utc) <= timedelta(minutes=5)

    blocked_booking = client.post(
        "/api/v1/bookings/manual-slot",
        json=payload,
        headers=headers,
    )
    assert blocked_booking.status_code == 409

    booking = db_session.query(Booking).filter(Booking.id == hold["booking_id"]).one()
    booking.hold_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db_session.commit()
    available_booking = client.post(
        "/api/v1/bookings/manual-slot",
        json=payload,
        headers=headers,
    )
    assert available_booking.status_code == 201, available_booking.text


def test_tc_f3_13_database_claim_prevents_duplicate_charger_intervals(
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    alice_charger: Charger,
):
    slot_start = datetime.combine(
        datetime.now(timezone.utc).date() + timedelta(days=1),
        time(9, 0),
        tzinfo=timezone.utc,
    )
    first_booking = Booking(
        user_id=driver_alice.id,
        vehicle_id=alice_vehicle.id,
        station_id=alice_station.id,
        charger_id=alice_charger.id,
        start_soc=20,
        target_soc=80,
        est_energy_kwh=27.0,
        est_duration_min=60,
        status=BookingStatus.CONFIRMED,
        start_time=slot_start,
        end_time=slot_start + timedelta(hours=1),
    )
    db_session.add(first_booking)
    db_session.flush()
    db_session.add(
        BookingSlotClaim(
            charger_id=alice_charger.id,
            slot_start_time=slot_start,
            vehicle_id=alice_vehicle.id,
            booking_id=first_booking.id,
        )
    )
    db_session.commit()

    duplicate_booking = Booking(
        user_id=driver_alice.id,
        vehicle_id=alice_vehicle.id,
        station_id=alice_station.id,
        charger_id=alice_charger.id,
        start_soc=20,
        target_soc=80,
        est_energy_kwh=27.0,
        est_duration_min=60,
        status=BookingStatus.CONFIRMED,
        start_time=slot_start,
        end_time=slot_start + timedelta(hours=1),
    )
    db_session.add(duplicate_booking)
    db_session.flush()
    db_session.add(
        BookingSlotClaim(
            charger_id=alice_charger.id,
            slot_start_time=slot_start,
            vehicle_id=alice_vehicle.id,
            booking_id=duplicate_booking.id,
        )
    )
    with pytest.raises(
        IntegrityError,
        match="booking_slot_claims.(charger_id|vehicle_id)",
    ):
        db_session.commit()
    db_session.rollback()

    second_charger = Charger(
        station_id=alice_station.id,
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="second-vehicle-claim-gateway",
    )
    db_session.add(second_charger)
    db_session.commit()
    db_session.refresh(second_charger)
    second_booking = Booking(
        user_id=driver_alice.id,
        vehicle_id=alice_vehicle.id,
        station_id=alice_station.id,
        charger_id=second_charger.id,
        start_soc=20,
        target_soc=80,
        est_energy_kwh=27.0,
        est_duration_min=60,
        status=BookingStatus.CONFIRMED,
        start_time=slot_start,
        end_time=slot_start + timedelta(hours=1),
    )
    db_session.add(second_booking)
    db_session.flush()
    db_session.add(
        BookingSlotClaim(
            charger_id=second_charger.id,
            slot_start_time=slot_start,
            vehicle_id=alice_vehicle.id,
            booking_id=second_booking.id,
        )
    )
    with pytest.raises(
        IntegrityError,
        match="booking_slot_claims.vehicle_id",
    ):
        db_session.commit()
    db_session.rollback()


def test_tc_f3_14_vehicle_cannot_book_overlapping_slot_on_another_charger(
    client: TestClient,
    db_session: Session,
    driver_alice: User,
    alice_vehicle: Vehicle,
    alice_station: Station,
    alice_charger: Charger,
    alice_connector: Connector,
):
    alice_vehicle.current_soc = 20
    second_charger = Charger(
        station_id=alice_station.id,
        power_kw=30.0,
        current_type=CurrentType.DC,
        gateway_id="second-vehicle-overlap-gateway",
    )
    db_session.add(second_charger)
    db_session.commit()
    db_session.refresh(second_charger)
    db_session.add(
        Connector(
            charger_id=second_charger.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    slot_start = datetime.combine(
        datetime.now(timezone.utc).date() + timedelta(days=1),
        time(9, 0),
        tzinfo=timezone.utc,
    )
    db_session.add(
        Booking(
            user_id=driver_alice.id,
            vehicle_id=alice_vehicle.id,
            station_id=alice_station.id,
            charger_id=alice_charger.id,
            start_soc=20,
            target_soc=80,
            est_energy_kwh=27.0,
            est_duration_min=60,
            status=BookingStatus.CONFIRMED,
            start_time=slot_start,
            end_time=slot_start + timedelta(hours=1),
        )
    )
    db_session.commit()

    headers = {"Authorization": f"Bearer {make_token(driver_alice)}"}
    request_payload = {
        "station_id": alice_station.id,
        "charger_id": second_charger.id,
        "vehicle_id": alice_vehicle.id,
        "start_time": (slot_start + timedelta(minutes=45)).isoformat(),
        "target_soc": 80,
    }
    booking_response = client.post(
        "/api/v1/bookings/manual-slot",
        json=request_payload,
        headers=headers,
    )
    assert booking_response.status_code == 409

    recommendation_response = client.get(
        "/api/v1/bookings/recommended-slots",
        params={
            "vehicle_id": alice_vehicle.id,
            "date": slot_start.date().isoformat(),
            "target_soc": 80,
            "station_id": alice_station.id,
        },
        headers=headers,
    )
    assert recommendation_response.status_code == 200
    assert all(
        datetime.fromisoformat(item["start_time"].replace("Z", "+00:00"))
        >= slot_start + timedelta(hours=1)
        or datetime.fromisoformat(item["end_time"].replace("Z", "+00:00"))
        <= slot_start
        for item in recommendation_response.json()["items"]
    )


def test_tc_f3_07_charging_time_requires_owned_vehicle_and_saved_battery_level(
    client: TestClient,
    driver_alice: User,
    alice_vehicle: Vehicle,
    driver_bob: User,
    bob_vehicle: Vehicle,
    alice_charger: Charger,
):
    headers = {"Authorization": f"Bearer {make_token(driver_alice)}"}
    foreign_vehicle_response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={"vehicle_id": bob_vehicle.id, "charger_id": alice_charger.id},
        headers=headers,
    )
    assert foreign_vehicle_response.status_code == 403

    missing_soc_response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={"vehicle_id": alice_vehicle.id, "charger_id": alice_charger.id},
        headers=headers,
    )
    assert missing_soc_response.status_code == 422


def test_tc_f3_07_charging_time_rejects_missing_charger(
    client: TestClient,
    driver_alice: User,
    alice_vehicle: Vehicle,
):
    alice_vehicle.current_soc = 20
    response = client.post(
        "/api/v1/bookings/charging-time-estimate",
        json={"vehicle_id": alice_vehicle.id, "charger_id": 999999},
        headers={"Authorization": f"Bearer {make_token(driver_alice)}"},
    )
    assert response.status_code == 404


# =========================================================================
# TC-F3-01: Integration Tests via SW Architecture & REST Endpoints
# =========================================================================

def test_tc_f3_01_enter_battery_level_architecture_route(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-01: Driver enters battery level via SW Architecture route:
    POST /api/v1/bookings/battery-level-input (Page 7).
    """
    token = make_token(driver_alice)
    payload = {
        "vehicle_id": alice_vehicle.id,
        "battery_level": 55,
        "target_soc": 85,
    }
    resp = client.post(
        "/api/v1/bookings/battery-level-input",
        json=payload,
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_id"] == alice_vehicle.id
    assert data["current_soc"] == 55
    assert data["current_battery_percentage"] == 55
    assert data["target_soc"] == 85
    assert data["is_low_battery"] is False
    assert data["usable_range_km"] > 0
    assert data["estimated_range_km"] > data["usable_range_km"]
    assert data["energy_required_kwh"] > 0
    assert data["battery_updated_at"] is not None


def test_tc_f3_01_update_battery_level_multiple_times(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-02: Driver updates battery percentage whenever required.
    Verify that subsequent updates overwrite the stored state and update ranges.
    """
    token = make_token(driver_alice)

    # First update: 70%
    r1 = client.patch(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 70},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r1.status_code == 200
    assert r1.json()["current_soc"] == 70
    range_at_70 = r1.json()["usable_range_km"]

    # Second update: 30% (battery discharged after trip)
    r2 = client.patch(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 30},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200
    assert r2.json()["current_soc"] == 30
    range_at_30 = r2.json()["usable_range_km"]
    assert range_at_30 < range_at_70

    # Third update: 90% (after charging)
    r3 = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 90},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r3.status_code == 200
    assert r3.json()["current_soc"] == 90
    assert r3.json()["usable_range_km"] > range_at_70


def test_tc_f3_01_default_vehicle_auto_selection(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-03: When vehicle_id is omitted, driver's primary default vehicle is automatically used.
    """
    token = make_token(driver_alice)
    resp = client.post(
        "/api/v1/bookings/battery-level-input",
        json={"battery_level": 65},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["vehicle_id"] == alice_vehicle.id
    assert data["current_soc"] == 65
    assert data["target_soc"] == 80  # Default 80%


def test_tc_f3_01_get_battery_level_persisted(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-04: Retrieve persisted battery level via GET endpoints.
    """
    token = make_token(driver_alice)
    # Set to 42%
    client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 42, "target_soc": 90},
        headers={"Authorization": f"Bearer {token}"},
    )

    # 1. Retrieve via GET /api/v1/bookings/battery-level-input?vehicle_id=...
    r_arch = client.get(
        f"/api/v1/bookings/battery-level-input?vehicle_id={alice_vehicle.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_arch.status_code == 200
    assert r_arch.json()["current_soc"] == 42
    assert r_arch.json()["target_soc"] == 90

    # 2. Retrieve via GET /api/v1/vehicles/{vehicle_id}/battery
    r_veh = client.get(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_veh.status_code == 200
    assert r_veh.json()["current_soc"] == 42

    # 3. Retrieve default vehicle battery via GET /api/v1/vehicles/battery-level
    r_def = client.get(
        "/api/v1/vehicles/battery-level",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_def.status_code == 200
    assert r_def.json()["vehicle_id"] == alice_vehicle.id
    assert r_def.json()["current_soc"] == 42


def test_tc_f3_01_low_battery_trigger_flag(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-05: When battery level is at or below the low_battery_threshold (20%),
    is_low_battery is flagged True (REQ-F3-20 / Appendix B.2).
    """
    token = make_token(driver_alice)

    # 15% <= 20% -> is_low_battery True
    r_low = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 15},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_low.status_code == 200
    assert r_low.json()["is_low_battery"] is True

    # 20% <= 20% -> is_low_battery True
    r_exact = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 20},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_exact.status_code == 200
    assert r_exact.json()["is_low_battery"] is True

    # 21% > 20% -> is_low_battery False
    r_above = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 21},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r_above.status_code == 200
    assert r_above.json()["is_low_battery"] is False


def test_tc_f3_01_boundary_partitions(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-06: Boundary value analysis (0%, 1%, 99%, 100%).
    """
    token = make_token(driver_alice)

    for boundary_val in [0, 1, 99, 100]:
        resp = client.post(
            f"/api/v1/vehicles/{alice_vehicle.id}/battery",
            json={"battery_level": boundary_val},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["current_soc"] == boundary_val


def test_tc_f3_01_reject_out_of_range_and_malformed_input(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-07: Negative, out-of-range (>100), and non-numeric inputs are rejected with 422.
    """
    token = make_token(driver_alice)
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Negative battery percentage
    r_neg = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": -5},
        headers=headers,
    )
    assert r_neg.status_code == 422

    # 2. Greater than 100%
    r_over = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 105},
        headers=headers,
    )
    assert r_over.status_code == 422

    # 3. String / malformed
    r_str = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": "fifty percent"},
        headers=headers,
    )
    assert r_str.status_code == 422

    # 4. Out of range target_soc
    r_target_neg = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 50, "target_soc": -10},
        headers=headers,
    )
    assert r_target_neg.status_code == 422

    r_target_over = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 50, "target_soc": 110},
        headers=headers,
    )
    assert r_target_over.status_code == 422


def test_tc_f3_01_driver_isolation_and_foreign_vehicle_denied(
    client: TestClient, driver_alice: User, driver_bob: User, bob_vehicle: Vehicle
):
    """
    TC-F3-01-08: A driver cannot view or update the battery level of another user's vehicle (403 Forbidden).
    """
    alice_token = make_token(driver_alice)
    headers = {"Authorization": f"Bearer {alice_token}"}

    # Alice attempts to update Bob's vehicle battery
    r_post = client.post(
        f"/api/v1/vehicles/{bob_vehicle.id}/battery",
        json={"battery_level": 60},
        headers=headers,
    )
    assert r_post.status_code == 403

    # Alice attempts to inspect Bob's vehicle battery
    r_get = client.get(
        f"/api/v1/vehicles/{bob_vehicle.id}/battery",
        headers=headers,
    )
    assert r_get.status_code == 403

    # Alice attempts to update Bob's vehicle via architecture route with vehicle_id
    r_arch = client.post(
        "/api/v1/bookings/battery-level-input",
        json={"vehicle_id": bob_vehicle.id, "battery_level": 60},
        headers=headers,
    )
    assert r_arch.status_code == 403


def test_tc_f3_01_role_enforcement_and_unauthenticated(
    client: TestClient, operator_charlie: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-09: Unauthenticated requests return 401; Station Operator role returns 403 Forbidden.
    """
    # 1. Unauthenticated request
    r_unauth = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 50},
    )
    assert r_unauth.status_code == 401

    # 2. Operator token
    op_token = make_token(operator_charlie)
    r_op = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 50},
        headers={"Authorization": f"Bearer {op_token}"},
    )
    assert r_op.status_code == 403
    assert "Only drivers and administrators" in r_op.json()["detail"]


def test_tc_f3_01_admin_can_update_vehicle_battery(
    client: TestClient, admin_dave: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-10: Administrator role has elevated access to view and update any vehicle's battery.
    """
    admin_token = make_token(admin_dave)
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 75, "target_soc": 95},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["current_soc"] == 75
    assert resp.json()["target_soc"] == 95


def test_tc_f3_01_nonexistent_vehicle_and_empty_garage(
    client: TestClient, driver_alice: User, driver_bob: User, db_session: Session
):
    """
    TC-F3-01-11: 404 Not Found for nonexistent vehicle ID or driver with no vehicles.
    """
    alice_token = make_token(driver_alice)
    headers = {"Authorization": f"Bearer {alice_token}"}

    # Nonexistent vehicle ID
    r_notfound = client.post(
        "/api/v1/vehicles/999999/battery",
        json={"battery_level": 50},
        headers=headers,
    )
    assert r_notfound.status_code == 404

    # Driver with no vehicles
    fresh_driver = User(
        name="Empty Driver",
        email="empty.driver@example.com",
        phone="+919876543299",
        hashed_password=hash_password("Empty123!"),
        role=UserRole.DRIVER,
        is_verified=True,
        is_active=True,
    )
    db_session.add(fresh_driver)
    db_session.commit()
    db_session.refresh(fresh_driver)

    fresh_token = make_token(fresh_driver)
    r_empty = client.post(
        "/api/v1/bookings/battery-level-input",
        json={"battery_level": 50},
        headers={"Authorization": f"Bearer {fresh_token}"},
    )
    assert r_empty.status_code == 404
    assert "Driver does not have any registered vehicles" in r_empty.json()["detail"]


def test_tc_f3_01_creates_audit_log(
    client: TestClient, db_session: Session, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-12: Battery level updates generate immutable audit log records.
    """
    token = make_token(driver_alice)
    client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 60, "target_soc": 80},
        headers={"Authorization": f"Bearer {token}"},
    )

    log = (
        db_session.query(AuditLog)
        .filter(AuditLog.user_id == driver_alice.id, AuditLog.action == "VEHICLE_BATTERY_UPDATE")
        .first()
    )
    assert log is not None
    assert f"vehicles/{alice_vehicle.id}" in log.resource
    assert "60%" in log.details


def test_tc_f3_01_vehicle_summary_card_reflects_battery(
    client: TestClient, driver_alice: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-13: Vehicle summary card reflects updated current_soc and adjusts usable range.
    """
    token = make_token(driver_alice)
    # Set to 50%
    client.post(
        f"/api/v1/vehicles/{alice_vehicle.id}/battery",
        json={"battery_level": 50},
        headers={"Authorization": f"Bearer {token}"},
    )

    summary_res = client.get(
        f"/api/v1/vehicles/{alice_vehicle.id}/summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert summary_res.status_code == 200
    card = summary_res.json()
    assert card["current_soc"] == 50
    # Tata Nexon (40.5 kWh, 15 kWh/100km): at 50% SoC usable range = 108.0 km
    assert card["usable_range_km"] == 108.0


def test_tc_f3_01_get_battery_rules_endpoint(client: TestClient):
    """
    TC-F3-01-14: GET /api/v1/bookings/battery-rules returns Appendix B rules.
    """
    res = client.get("/api/v1/bookings/battery-rules")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    rules = data["rules"]
    assert "battery_level" in rules
    assert rules["battery_level"]["min"] == 0
    assert rules["battery_level"]["max"] == 100
    assert rules["reserve"]["default"] == 10


def test_tc_f3_01_direct_service_layer_unit_tests(
    db_session: Session, driver_alice: User, driver_bob: User, alice_vehicle: Vehicle
):
    """
    TC-F3-01-15: Direct unit testing of BookingService methods.
    """
    # 1. Update battery via BookingService
    res = BookingService.set_battery_level(
        db=db_session,
        user=driver_alice,
        battery_level=80,
        vehicle_id=alice_vehicle.id,
        target_soc=90,
    )
    assert res.current_soc == 80
    assert res.target_soc == 90

    # 2. Get battery via BookingService
    res_get = BookingService.get_battery_level(
        db=db_session,
        user=driver_alice,
        vehicle_id=alice_vehicle.id,
    )
    assert res_get.current_soc == 80

    # 3. BookingService range & energy calculations
    usable = BookingService.calculate_usable_range(40.5, 15.0, 80)
    assert usable == round(((80 - 10) / 100.0 * 40.5) / 0.15, 1)

    energy = BookingService.calculate_energy_required(40.5, 20, 80)
    assert energy == 27.0
