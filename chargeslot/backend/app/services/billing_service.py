from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.booking import Booking, BookingStatus
from app.models.charging_session_reading import ChargingSessionReading
from app.models.payment_record import PaymentRecord
from app.models.station import Station
from app.models.station_tariff import StationTariff
from app.models.user import User


def _money(value: Decimal | float | int) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def snapshot_booking_tariff(
    db: Session,
    booking: Booking,
    *,
    confirmed_at: datetime | None = None,
) -> None:
    """Freeze the effective station tariff when a booking is confirmed."""
    if booking.station_id is None:
        raise ValueError("A station is required to snapshot a booking tariff.")

    station = db.query(Station).filter(Station.id == booking.station_id).first()
    if station is None:
        raise ValueError("The booking station no longer exists.")

    confirmation_time = confirmed_at or datetime.now(timezone.utc)
    if confirmation_time.tzinfo is None:
        confirmation_time = confirmation_time.replace(tzinfo=timezone.utc)
    tariff = (
        db.query(StationTariff)
        .filter(
            StationTariff.station_id == station.id,
            StationTariff.effective_from <= confirmation_time,
        )
        .order_by(StationTariff.effective_from.desc(), StationTariff.id.desc())
        .first()
    )
    booking.tariff_snapshot_id = tariff.id if tariff else None
    booking.tariff_price_per_kwh = (
        tariff.price_per_kwh if tariff else station.price_per_kwh or 0.0
    )
    booking.tariff_idle_fee_per_minute = tariff.idle_fee_per_minute if tariff else 0.0
    booking.tariff_tax_rate_percent = tariff.tax_rate_percent if tariff else 0.0
    booking.tariff_peak_periods = list(tariff.peak_periods or []) if tariff else []
    booking.confirmed_at = confirmation_time
    booking.reservation_fee_amount = float(
        _money(settings.RESERVATION_FEE_INR)
    )


def _is_peak_period(booking: Booking) -> bool:
    if booking.start_time is None:
        return False
    start_time = booking.start_time
    if start_time.tzinfo is None:
        start_time = start_time.replace(tzinfo=timezone.utc)
    start_clock = start_time.astimezone(timezone.utc).time().replace(tzinfo=None)

    for period in booking.tariff_peak_periods or []:
        try:
            period_start = time.fromisoformat(period["start"])
            period_end = time.fromisoformat(period["end"])
            if period_start <= period_end:
                matches = period_start <= start_clock < period_end
            else:
                matches = start_clock >= period_start or start_clock < period_end
        except (KeyError, TypeError, ValueError):
            continue
        if matches:
            return True
    return False


def calculate_final_bill(
    db: Session,
    booking: Booking,
    *,
    ended_at: datetime,
    meter_stop_wh: int,
) -> float:
    """Compute actual energy, idle charge, taxes, and paid reservation credit."""
    readings = (
        db.query(ChargingSessionReading)
        .filter(
            ChargingSessionReading.booking_id == booking.id,
            ChargingSessionReading.transaction_id == booking.session_transaction_id,
        )
        .order_by(ChargingSessionReading.observed_at.asc(), ChargingSessionReading.id.asc())
        .all()
    )
    if readings:
        energy_kwh = max(0.0, meter_stop_wh / 1000 - readings[0].energy_meter_kwh)
    else:
        energy_kwh = 0.0

    base_rate = Decimal(str(booking.tariff_price_per_kwh or 0.0))
    if _is_peak_period(booking):
        multiplier = next(
            (
                Decimal(str(period.get("multiplier", 1)))
                for period in booking.tariff_peak_periods or []
                if isinstance(period, dict)
                and _period_matches(booking, period)
            ),
            Decimal("1"),
        )
        base_rate *= multiplier

    energy_cost = _money(Decimal(str(energy_kwh)) * base_rate)
    scheduled_end = booking.end_time
    if scheduled_end.tzinfo is None:
        scheduled_end = scheduled_end.replace(tzinfo=timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    idle_seconds = max(0.0, (ended_at - scheduled_end).total_seconds())
    idle_minutes = int(
        (Decimal(str(idle_seconds)) / Decimal(60)).to_integral_value(
            rounding=ROUND_CEILING
        )
    )
    idle_cost = _money(
        Decimal(idle_minutes) * Decimal(str(booking.tariff_idle_fee_per_minute or 0.0))
    )
    tax = _money(
        (energy_cost + idle_cost)
        * Decimal(str(booking.tariff_tax_rate_percent or 0.0))
        / Decimal(100)
    )
    gross = energy_cost + idle_cost + tax
    reservation_credit = _money(booking.reservation_fee_paid_amount or 0.0)
    total_due = max(Decimal(0), gross - reservation_credit)

    booking.energy_cost_amount = float(energy_cost)
    booking.energy_delivered_kwh = energy_kwh
    booking.idle_fee_amount = float(idle_cost)
    booking.tax_amount = float(tax)
    booking.final_bill_amount = float(total_due)
    db.flush()
    return float(total_due)


def _period_matches(booking: Booking, period: dict) -> bool:
    try:
        start = booking.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        clock = start.astimezone(timezone.utc).time().replace(tzinfo=None)
        period_start = time.fromisoformat(period["start"])
        period_end = time.fromisoformat(period["end"])
        if period_start <= period_end:
            return period_start <= clock < period_end
        return clock >= period_start or clock < period_end
    except (KeyError, TypeError, ValueError):
        return False


def update_payment_due(db: Session, booking: Booking) -> bool:
    """Set Payment Due from the unpaid post-reservation balance."""
    captured_balance = (
        db.query(func.coalesce(func.sum(PaymentRecord.amount_paise), 0))
        .filter(
            PaymentRecord.booking_id == booking.id,
            PaymentRecord.status == "captured",
            PaymentRecord.payment_type.in_(("balance", "session")),
        )
        .scalar()
    )
    due_paise = max(
        0,
        int((_money(booking.final_bill_amount or 0.0) * 100).to_integral_value())
        - int(captured_balance or 0),
    )
    booking.payment_due = due_paise > 0
    return booking.payment_due


def ensure_no_payment_due(db: Session, user: User) -> None:
    due_booking = (
        db.query(Booking.id)
        .filter(
            Booking.user_id == user.id,
            Booking.payment_due.is_(True),
            Booking.status == BookingStatus.COMPLETED,
        )
        .first()
    )
    if due_booking:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="An outstanding charging balance must be paid before booking again.",
        )


def add_business_days(start: datetime, days: int) -> datetime:
    """Return a UTC deadline after the requested number of weekdays."""
    current = start.astimezone(timezone.utc)
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:
            added += 1
    return current
