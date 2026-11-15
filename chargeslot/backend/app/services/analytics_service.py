import csv
from datetime import date, datetime, time, timedelta, timezone
from io import StringIO

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.analytics_snapshot import AnalyticsSnapshot
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector
from app.models.payment_record import PaymentRecord
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.analytics import AnalyticsSummaryResponse

SNAPSHOT_ID = 1
REFRESH_INTERVAL = timedelta(hours=1)
MAX_DATE_RANGE_DAYS = 3660


def refresh_analytics_snapshot(db: Session) -> AnalyticsSnapshot:
    stations = db.query(Station).order_by(Station.id.asc()).all()
    connector_counts: dict[int, int] = {}
    connector_rows = (
        db.query(Charger.station_id, Connector.id)
        .join(Connector, Connector.charger_id == Charger.id)
        .filter(Charger.is_active.is_(True), Charger.is_out_of_service.is_(False))
        .all()
    )
    for station_id, _ in connector_rows:
        connector_counts[station_id] = connector_counts.get(station_id, 0) + 1
    station_rows = [
        {
            "station_id": station.id,
            "name": station.name,
            "operator_id": station.operator_id,
            "active": bool(station.is_active and station.status.value == "approved"),
            "connector_count": connector_counts.get(station.id, 0),
        }
        for station in stations
    ]
    station_by_id = {row["station_id"]: row for row in station_rows}

    completed = (
        db.query(Booking)
        .filter(
            Booking.status == BookingStatus.COMPLETED,
            Booking.session_ended_at.isnot(None),
        )
        .order_by(Booking.session_ended_at.asc(), Booking.id.asc())
        .all()
    )
    completed_ids = [booking.id for booking in completed]
    payments = (
        db.query(PaymentRecord)
        .filter(
            PaymentRecord.booking_id.in_(completed_ids or [-1]),
            PaymentRecord.payment_type.in_(("reservation", "balance", "session", "refund")),
            PaymentRecord.status.in_(("captured", "refunded")),
        )
        .all()
    )
    paid_by_booking: dict[int, int] = {}
    for payment in payments:
        amount = payment.amount_paise
        if payment.payment_type == "refund":
            amount = -amount
        paid_by_booking[payment.booking_id] = (
            paid_by_booking.get(payment.booking_id, 0) + amount
        )

    session_rows = []
    for booking in completed:
        station = station_by_id.get(booking.station_id)
        if station is None:
            continue
        ended_at = _as_utc(booking.session_ended_at)
        started_at = _as_utc(booking.start_time)
        session_rows.append(
            {
                "booking_id": booking.id,
                "driver_id": booking.user_id,
                "station_id": station["station_id"],
                "station_name": station["name"],
                "operator_id": station["operator_id"],
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
                "energy_kwh": max(0.0, float(booking.energy_delivered_kwh or 0)),
                "revenue_paise": max(0, paid_by_booking.get(booking.id, 0)),
            }
        )

    data = {
        "sessions": session_rows,
        "stations": station_rows,
        "user_count": db.query(User.id).count(),
        "station_count": sum(1 for station in station_rows if station["active"]),
    }
    snapshot = db.get(AnalyticsSnapshot, SNAPSHOT_ID)
    if snapshot is None:
        snapshot = AnalyticsSnapshot(id=SNAPSHOT_ID, data=data)
        db.add(snapshot)
    else:
        snapshot.data = data
        snapshot.refreshed_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        snapshot = db.get(AnalyticsSnapshot, SNAPSHOT_ID)
        if snapshot is None:
            raise
        snapshot.data = data
        snapshot.refreshed_at = datetime.now(timezone.utc)
        db.commit()
    db.refresh(snapshot)
    return snapshot


def get_analytics_summary(
    db: Session,
    user: User,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: str = "week",
) -> AnalyticsSummaryResponse:
    start, end = _validated_range(start_date, end_date)
    if granularity not in {"week", "month"}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analytics granularity must be week or month.",
        )
    snapshot = _fresh_snapshot(db)
    sessions = _scoped_sessions(snapshot.data["sessions"], user)
    sessions = [
        row
        for row in sessions
        if start <= date.fromisoformat(row["ended_at"][:10]) <= end
    ]
    station_rows = _scoped_stations(snapshot.data["stations"], user)
    summary = _summarize(
        sessions=sessions,
        stations=station_rows,
        user=user,
        start=start,
        end=end,
        granularity=granularity,
        snapshot=snapshot,
        user_count=snapshot.data["user_count"],
        station_count=snapshot.data["station_count"],
    )
    return AnalyticsSummaryResponse.model_validate(summary)


def export_analytics_csv(
    db: Session,
    user: User,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
) -> str:
    start, end = _validated_range(start_date, end_date)
    snapshot = _fresh_snapshot(db)
    sessions = [
        row
        for row in _scoped_sessions(snapshot.data["sessions"], user)
        if start <= date.fromisoformat(row["ended_at"][:10]) <= end
    ]
    output = StringIO(newline="")
    writer = csv.writer(output)
    if user.role == UserRole.DRIVER:
        writer.writerow(
            ["session_date", "booking_id", "station", "energy_kwh", "spend_inr", "co2_saved_kg"]
        )
        for row in sessions:
            writer.writerow(
                [
                    row["ended_at"][:10],
                    row["booking_id"],
                    _safe_csv(row["station_name"]),
                    f'{row["energy_kwh"]:.3f}',
                    f'{row["revenue_paise"] / 100:.2f}',
                    f'{row["energy_kwh"] * settings.CO2_SAVED_KG_PER_KWH:.3f}',
                ]
            )
    else:
        station_rows = _scoped_stations(snapshot.data["stations"], user)
        totals = _aggregate_stations(sessions, station_rows, start, end)
        writer.writerow(
            [
                "station_id",
                "station",
                "sessions",
                "energy_kwh",
                "revenue_inr",
                "utilization_percent",
            ]
        )
        for row in totals:
            writer.writerow(
                [
                    row["station_id"],
                    _safe_csv(row["station"]),
                    row["sessions"],
                    f'{row["energy_kwh"]:.3f}',
                    f'{row["revenue_inr"]:.2f}',
                    f'{row["utilization_percent"]:.2f}',
                ]
            )
    return output.getvalue()


def _fresh_snapshot(db: Session) -> AnalyticsSnapshot:
    snapshot = db.get(AnalyticsSnapshot, SNAPSHOT_ID)
    if snapshot is None or (
        datetime.now(timezone.utc) - _as_utc(snapshot.refreshed_at)
    ) >= REFRESH_INTERVAL:
        return refresh_analytics_snapshot(db)
    return snapshot


def _validated_range(
    start_date: date | None,
    end_date: date | None,
) -> tuple[date, date]:
    today = datetime.now(timezone.utc).date()
    end = end_date or today
    start = start_date or end - timedelta(days=29)
    if start > end:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analytics start_date must be on or before end_date.",
        )
    if end > today:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Analytics end_date cannot be in the future.",
        )
    if (end - start).days + 1 > MAX_DATE_RANGE_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Analytics date range cannot exceed {MAX_DATE_RANGE_DAYS} days.",
        )
    return start, end


def _scoped_sessions(rows: list[dict], user: User) -> list[dict]:
    if user.role == UserRole.ADMIN:
        return list(rows)
    if user.role == UserRole.OPERATOR:
        return [row for row in rows if row["operator_id"] == user.id]
    if user.role == UserRole.DRIVER:
        return [row for row in rows if row["driver_id"] == user.id]
    raise HTTPException(status_code=403, detail="This role cannot view analytics.")


def _scoped_stations(rows: list[dict], user: User) -> list[dict]:
    if user.role == UserRole.ADMIN:
        return [row for row in rows if row["active"]]
    if user.role == UserRole.OPERATOR:
        return [row for row in rows if row["operator_id"] == user.id]
    return []


def _summarize(
    *,
    sessions: list[dict],
    stations: list[dict],
    user: User,
    start: date,
    end: date,
    granularity: str,
    snapshot: AnalyticsSnapshot,
    user_count: int,
    station_count: int,
) -> dict:
    session_count = len(sessions)
    energy = sum(row["energy_kwh"] for row in sessions)
    revenue_paise = sum(row["revenue_paise"] for row in sessions)
    trends: dict[str, dict] = {}
    for row in sessions:
        session_day = date.fromisoformat(row["ended_at"][:10])
        bucket = _bucket(session_day, granularity)
        trend = trends.setdefault(
            bucket,
            {
                "period": bucket,
                "sessions": 0,
                "energy_kwh": 0.0,
                "spend_inr": 0.0,
            },
        )
        trend["sessions"] += 1
        trend["energy_kwh"] += row["energy_kwh"]
        trend["spend_inr"] += row["revenue_paise"] / 100

    if user.role == UserRole.DRIVER:
        stations_for_summary = {
            row["station_id"]: {
                "station_id": row["station_id"],
                "name": row["station_name"],
                "connector_count": 0,
            }
            for row in sessions
        }
        station_metrics = _aggregate_stations(
            sessions,
            list(stations_for_summary.values()),
            start,
            end,
        )
    else:
        station_metrics = _aggregate_stations(sessions, stations, start, end)
    top_stations = sorted(
        (row for row in station_metrics if row["sessions"]),
        key=lambda row: (-row["sessions"], -row["energy_kwh"], row["station_id"]),
    )[:5]
    totals: dict[str, int | float] = {
        "sessions": session_count,
        "energy_kwh": round(energy, 3),
        "spend_inr": round(revenue_paise / 100, 2),
        "revenue_inr": round(revenue_paise / 100, 2),
        "co2_saved_kg": round(energy * settings.CO2_SAVED_KG_PER_KWH, 3),
    }
    if user.role == UserRole.ADMIN:
        totals.update({"users": user_count, "stations": station_count})
    return {
        "scope": {
            UserRole.DRIVER: "driver",
            UserRole.OPERATOR: "operator",
            UserRole.ADMIN: "platform",
        }[user.role],
        "start_date": start,
        "end_date": end,
        "refreshed_at": snapshot.refreshed_at,
        "totals": totals,
        "trends": sorted(trends.values(), key=lambda row: row["period"]),
        "top_stations": top_stations if user.role == UserRole.DRIVER else [],
        "stations": station_metrics if user.role != UserRole.DRIVER else [],
    }


def _aggregate_stations(
    sessions: list[dict],
    stations: list[dict],
    start: date,
    end: date,
) -> list[dict]:
    start_at = datetime.combine(start, time.min, tzinfo=timezone.utc)
    end_at = datetime.combine(end + timedelta(days=1), time.min, tzinfo=timezone.utc)
    period_hours = (end_at - start_at).total_seconds() / 3600
    result = []
    for station in stations:
        selected = [
            row for row in sessions if row["station_id"] == station["station_id"]
        ]
        used_minutes = 0.0
        for row in selected:
            session_start = max(_as_utc(datetime.fromisoformat(row["started_at"])), start_at)
            session_end = min(_as_utc(datetime.fromisoformat(row["ended_at"])), end_at)
            used_minutes += max(0.0, (session_end - session_start).total_seconds() / 60)
        connector_count = int(station["connector_count"])
        available_minutes = period_hours * 60 * connector_count
        result.append(
            {
                "station_id": station["station_id"],
                "station": station["name"],
                "sessions": len(selected),
                "energy_kwh": round(sum(row["energy_kwh"] for row in selected), 3),
                "revenue_inr": round(
                    sum(row["revenue_paise"] for row in selected) / 100, 2
                ),
                "utilization_percent": round(
                    min(100.0, used_minutes / available_minutes * 100)
                    if available_minutes
                    else 0.0,
                    2,
                ),
            }
        )
    return result


def _bucket(day: date, granularity: str) -> str:
    if granularity == "month":
        return day.replace(day=1).isoformat()
    return (day - timedelta(days=day.weekday())).isoformat()


def _safe_csv(value: str) -> str:
    cleaned = value.replace("\r", " ").replace("\n", " ")
    if cleaned.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + cleaned
    return cleaned


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(
        timezone.utc
    )
