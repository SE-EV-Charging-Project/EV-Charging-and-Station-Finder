import csv
from datetime import datetime, timedelta, timezone
from io import StringIO

import pytest
from fastapi import HTTPException

from app.models.analytics_snapshot import AnalyticsSnapshot
from app.models.booking import Booking, BookingStatus
from app.models.charger import (
    Charger,
    Connector,
    ConnectorStatus,
    ConnectorType,
    CurrentType,
)
from app.models.payment_record import PaymentRecord
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.services.analytics_service import (
    export_analytics_csv,
    get_analytics_summary,
)


def _analytics_user(db, suffix: str, role: UserRole) -> User:
    user = User(
        name=f"Analytics {suffix}",
        email=f"analytics-{suffix}@example.test",
        phone=f"800{suffix:0>7}",
        hashed_password="test-hash",
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _seed_analytics(db):
    driver = _analytics_user(db, "driver1", UserRole.DRIVER)
    other_driver = _analytics_user(db, "driver2", UserRole.DRIVER)
    operator = _analytics_user(db, "operator", UserRole.OPERATOR)
    other_operator = _analytics_user(db, "otherop", UserRole.OPERATOR)
    admin = _analytics_user(db, "admin", UserRole.ADMIN)
    station = Station(
        operator_id=operator.id,
        name="=Unsafe Station",
        address="Analytics Road",
        latitude=12.97,
        longitude=77.59,
        contact_phone="9876543210",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    other_station = Station(
        operator_id=other_operator.id,
        name="Other Station",
        address="Other Road",
        latitude=12.98,
        longitude=77.6,
        contact_phone="9876543211",
        status=StationStatus.APPROVED,
        is_active=True,
    )
    db.add_all([station, other_station])
    db.flush()
    charger = Charger(
        station_id=station.id,
        name="Analytics Charger",
        power_kw=50,
        current_type=CurrentType.DC,
        gateway_id="analytics-gateway",
    )
    db.add(charger)
    db.flush()
    db.add(
        Connector(
            charger_id=charger.id,
            connector_type=ConnectorType.CCS2,
            status=ConnectorStatus.AVAILABLE,
        )
    )
    ended = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=2)
    first = Booking(
        user_id=driver.id,
        station_id=station.id,
        status=BookingStatus.COMPLETED,
        start_time=ended - timedelta(hours=1),
        end_time=ended,
        session_ended_at=ended,
        energy_delivered_kwh=4.5,
    )
    other = Booking(
        user_id=other_driver.id,
        station_id=other_station.id,
        status=BookingStatus.COMPLETED,
        start_time=ended - timedelta(hours=2),
        end_time=ended,
        session_ended_at=ended,
        energy_delivered_kwh=2,
    )
    db.add_all([first, other])
    db.flush()
    db.add_all(
        [
            PaymentRecord(
                user_id=driver.id,
                booking_id=first.id,
                amount_paise=1200,
                payment_type="balance",
                idempotency_key="analytics-payment-1",
                status="captured",
            ),
            PaymentRecord(
                user_id=other_driver.id,
                booking_id=other.id,
                amount_paise=800,
                payment_type="balance",
                idempotency_key="analytics-payment-2",
                status="captured",
            ),
        ]
    )
    db.commit()
    return driver, operator, other_operator, admin, station


def test_analytics_is_role_scoped_and_includes_usage_trends(db_session):
    driver, operator, other_operator, admin, station = _seed_analytics(db_session)

    driver_summary = get_analytics_summary(db_session, driver)
    assert driver_summary.scope == "driver"
    assert driver_summary.totals["sessions"] == 1
    assert driver_summary.totals["energy_kwh"] == 4.5
    assert driver_summary.totals["spend_inr"] == 12
    assert driver_summary.totals["co2_saved_kg"] == 3.15
    assert driver_summary.top_stations[0]["station_id"] == station.id
    assert driver_summary.trends[0]["sessions"] == 1

    operator_summary = get_analytics_summary(db_session, operator)
    assert operator_summary.scope == "operator"
    assert len(operator_summary.stations) == 1
    assert operator_summary.stations[0]["sessions"] == 1
    assert operator_summary.stations[0]["revenue_inr"] == 12
    other_summary = get_analytics_summary(db_session, other_operator)
    assert other_summary.totals["sessions"] == 1
    assert other_summary.stations[0]["station_id"] != station.id

    platform_summary = get_analytics_summary(db_session, admin)
    assert platform_summary.scope == "platform"
    assert platform_summary.totals["sessions"] == 2
    assert platform_summary.totals["users"] == 5


def test_analytics_date_range_csv_and_hourly_cache_refresh(db_session):
    driver, _, _, _, station = _seed_analytics(db_session)
    session_date = datetime.now(timezone.utc).date() - timedelta(days=2)
    summary = get_analytics_summary(
        db_session,
        driver,
        start_date=session_date,
        end_date=session_date,
        granularity="month",
    )
    assert summary.trends[0]["period"] == session_date.replace(day=1).isoformat()

    csv_contents = export_analytics_csv(
        db_session,
        driver,
        start_date=session_date,
        end_date=session_date,
    )
    assert next(csv.reader(StringIO(csv_contents))) == [
        "session_date",
        "booking_id",
        "station",
        "energy_kwh",
        "spend_inr",
        "co2_saved_kg",
    ]
    assert "'=Unsafe Station" in csv_contents

    snapshot = db_session.get(AnalyticsSnapshot, 1)
    snapshot.refreshed_at -= timedelta(hours=2)
    db_session.commit()
    booking = (
        db_session.query(Booking)
        .filter(Booking.user_id == driver.id, Booking.station_id == station.id)
        .one()
    )
    booking.energy_delivered_kwh = 7
    db_session.commit()

    refreshed = get_analytics_summary(db_session, driver)
    assert refreshed.totals["energy_kwh"] == 7


def test_analytics_rejects_bad_ranges_and_unsupported_roles(db_session):
    driver, _, _, _, _ = _seed_analytics(db_session)
    today = datetime.now(timezone.utc).date()
    with pytest.raises(HTTPException) as exc:
        get_analytics_summary(
            db_session,
            driver,
            start_date=today,
            end_date=today - timedelta(days=1),
        )
    assert exc.value.status_code == 422

    with pytest.raises(HTTPException) as exc:
        get_analytics_summary(db_session, driver, granularity="day")
    assert exc.value.status_code == 422
