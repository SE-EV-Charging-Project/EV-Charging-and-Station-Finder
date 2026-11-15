from datetime import datetime, timedelta, timezone

import pytest

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.booking_payment_event import (
    BookingPaymentEvent,
    BookingPaymentEventStatus,
)
from app.models.booking_slot_claim import BookingSlotClaim
from app.models.charger import Charger, Connector, ConnectorStatus, CurrentType
from app.models.charging_session_start_command import (
    ChargingSessionStartCommand,
    SessionStartCommandStatus,
)
from app.models.in_app_notification import InAppNotification
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.models.vehicle import ConnectorType, Vehicle
from app.utils.security import create_access_token, hash_password


def _create_user(db_session, name: str, email: str, phone: str, role: UserRole) -> User:
    user = User(
        name=name,
        email=email,
        phone=phone,
        hashed_password=hash_password("StrongPass!1"),
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
        {"sub": str(user.id), "email": user.email, "role": user.role.value}
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def faultable_booking(db_session):
    driver = _create_user(
        db_session, "Fault Driver", "fault.driver@example.com", "+919800000301",
        UserRole.DRIVER,
    )
    operator = _create_user(
        db_session, "Fault Operator", "fault.operator@example.com", "+919800000302",
        UserRole.OPERATOR,
    )
    station = Station(
        operator_id=operator.id,
        name="Fault Recovery Station",
        address="42 Residency Road, Bengaluru",
        latitude=12.9718,
        longitude=77.6012,
        amenities=[],
        operating_hours="24x7",
        contact_phone="+919876500099",
        price_per_kwh=5.0,
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db_session.add(station)
    db_session.flush()
    charger = Charger(
        station_id=station.id,
        name="Faulting Charger",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-FAULT-01",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(charger)
    db_session.flush()
    connector = Connector(
        charger_id=charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    vehicle = Vehicle(
        user_id=driver.id,
        make="Tata",
        model="Nexon EV",
        battery_kwh=60.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        current_soc=40,
        target_soc=80,
    )
    db_session.add_all([connector, vehicle])
    db_session.flush()
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    start_time = now + timedelta(minutes=60 + (15 - now.minute % 15) % 15)
    booking = Booking(
        user_id=driver.id,
        vehicle_id=vehicle.id,
        station_id=station.id,
        charger_id=charger.id,
        connector_id=connector.id,
        start_soc=40,
        target_soc=80,
        est_energy_kwh=20.0,
        est_duration_min=60,
        reservation_fee_amount=10.0,
        status=BookingStatus.CONFIRMED,
        start_time=start_time,
        end_time=start_time + timedelta(hours=1),
    )
    db_session.add(booking)
    db_session.flush()
    claim = BookingSlotClaim(
        booking_id=booking.id,
        charger_id=charger.id,
        vehicle_id=vehicle.id,
        slot_start_time=start_time,
    )
    payment = BookingPaymentEvent(
        booking_id=booking.id,
        provider_event_id="fault-reservation-payment",
        amount_inr=10.0,
        status=BookingPaymentEventStatus.SUCCEEDED,
    )
    db_session.add_all([claim, payment])
    db_session.commit()
    return {
        "driver": driver,
        "station": station,
        "charger": charger,
        "connector": connector,
        "vehicle": vehicle,
        "booking": booking,
        "payment": payment,
    }


def test_no_show_sweep_marks_after_grace_applies_fee_and_releases_claims(
    db_session, faultable_booking
):
    booking = faultable_booking["booking"]
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    booking.start_time = now - timedelta(minutes=16)
    booking.end_time = now + timedelta(minutes=44)
    eligible_claim = BookingSlotClaim(
        booking_id=booking.id,
        charger_id=booking.charger_id,
        vehicle_id=booking.vehicle_id,
        slot_start_time=now - timedelta(minutes=15),
    )
    not_due = Booking(
        user_id=booking.user_id,
        vehicle_id=None,
        station_id=booking.station_id,
        charger_id=booking.charger_id,
        status=BookingStatus.CONFIRMED,
        start_time=now - timedelta(minutes=14),
        end_time=now + timedelta(minutes=46),
    )
    db_session.add_all([eligible_claim, not_due])
    db_session.commit()

    from app.booking.no_show import sweep_no_show_bookings

    marked = sweep_no_show_bookings(db_session, now=now)
    assert marked == [booking.id]
    assert booking.status == BookingStatus.NO_SHOW
    assert booking.cancellation_fee_amount == 10.0
    assert (
        db_session.query(BookingSlotClaim)
        .filter(BookingSlotClaim.booking_id == booking.id)
        .count()
        == 0
    )
    assert (
        db_session.query(InAppNotification)
        .filter(InAppNotification.dedupe_key == f"booking-no-show:{booking.id}")
        .count()
        == 1
    )
    assert sweep_no_show_bookings(db_session, now=now) == []
    assert not_due.status == BookingStatus.CONFIRMED


def test_checkin_is_rejected_after_the_grace_period(client, faultable_booking):
    scenario = faultable_booking
    scenario["booking"].start_time = datetime.now(timezone.utc) - timedelta(minutes=16)
    response = client.post(
        f"/api/v1/bookings/{scenario['booking'].id}/check-in",
        json={
            "latitude": scenario["station"].latitude,
            "longitude": scenario["station"].longitude,
        },
        headers=_auth_header(scenario["driver"]),
    )
    assert response.status_code == 409


def test_fault_reassigns_booking_and_notifies_only_its_driver(
    client, db_session, faultable_booking
):
    from app.models.charger import Charger, Connector

    scenario = faultable_booking
    alternative_charger = Charger(
        station_id=scenario["station"].id,
        name="Alternative Charger",
        power_kw=50.0,
        current_type=CurrentType.DC,
        gateway_id="GW-FAULT-02",
        is_active=True,
        is_out_of_service=False,
    )
    db_session.add(alternative_charger)
    db_session.flush()
    alternative_connector = Connector(
        charger_id=alternative_charger.id,
        connector_type=ConnectorType.CCS2,
        status=ConnectorStatus.AVAILABLE,
    )
    db_session.add(alternative_connector)
    scenario["booking"].checked_in_at = datetime.now(timezone.utc)
    db_session.commit()
    start_request = client.post(
        f"/api/v1/bookings/{scenario['booking'].id}/start-session",
        json={},
        headers=_auth_header(scenario["driver"]),
    )
    assert start_request.status_code == 202
    start_command_id = start_request.json()["command_id"]

    response = client.post(
        "/api/v1/gateway/ocpp/1.6j",
        json={
            "connector_id": scenario["connector"].id,
            "status": "Faulted",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "connector-fault-event-1",
        },
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    assert "reassigned or cancelled" in response.json()["message"]
    assert scenario["booking"].status == BookingStatus.REASSIGNED
    assert scenario["booking"].charger_id == alternative_charger.id
    assert scenario["booking"].connector_id == alternative_connector.id
    assert scenario["booking"].checked_in_at is None
    assert scenario["payment"].refund_due is False
    start_command = (
        db_session.query(ChargingSessionStartCommand)
        .filter(ChargingSessionStartCommand.id == start_command_id)
        .one()
    )
    assert start_command.status == SessionStartCommandStatus.FAILED
    assert (
        db_session.query(BookingSlotClaim)
        .filter(
            BookingSlotClaim.booking_id == scenario["booking"].id,
            BookingSlotClaim.charger_id == alternative_charger.id,
        )
        .count()
        == 4
    )

    replay = client.post(
        "/api/v1/gateway/ocpp/1.6j",
        json={
            "connector_id": scenario["connector"].id,
            "status": "Faulted",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "connector-fault-event-1",
        },
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert replay.status_code == 200
    assert replay.json()["idempotent_replay"] is True

    notification_response = client.get(
        "/api/v1/notifications",
        headers=_auth_header(scenario["driver"]),
    )
    assert notification_response.status_code == 200
    notification = notification_response.json()["notifications"][0]
    assert notification["notification_type"] == "booking_reassigned"
    assert notification["payload"]["charger_id"] == alternative_charger.id
    assert notification_response.json()["unread_count"] == 1
    notification_id = notification["id"]
    marked_read = client.patch(
        f"/api/v1/notifications/{notification_id}/read",
        headers=_auth_header(scenario["driver"]),
    )
    assert marked_read.status_code == 200
    assert marked_read.json()["read_at"]
    other_driver = _create_user(
        db_session,
        "Other Notification Driver",
        "fault.other@example.com",
        "+919800000303",
        UserRole.DRIVER,
    )
    foreign_read = client.patch(
        f"/api/v1/notifications/{notification_id}/read",
        headers=_auth_header(other_driver),
    )
    assert foreign_read.status_code == 404


def test_fault_without_alternative_cancels_and_marks_full_refund_due(
    client, faultable_booking
):
    scenario = faultable_booking
    response = client.post(
        "/api/v1/gateway/ocpp/1.6j",
        json={
            "connector_id": scenario["connector"].id,
            "status": "Faulted",
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "idempotency_key": "connector-fault-event-no-alternative",
        },
        headers={"X-Gateway-Secret": settings.GATEWAY_WEBHOOK_SECRET},
    )
    assert response.status_code == 200
    assert scenario["booking"].status == BookingStatus.CANCELLED
    assert scenario["booking"].cancellation_fee_amount == 0.0
    assert scenario["payment"].refund_due is True
    assert (
        scenario["booking"].reservation_fee_amount
        == scenario["payment"].amount_inr
    )
