"""
Dashboard connector reservation state resolver (REQ-F2-21 / CS19-047 / SDD §Dashboard).
Evaluates confirmed bookings starting within 15 minutes to display Reserved status on connectors.
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from app.dashboard.views import (
    _latest_error_codes_by_connector,
    _load_authorized_station,
)
from app.discovery.views import _enum_to_str
from app.gateway.ingest import _ensure_utc
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.dashboard import (
    ReservedConnectorStatusItem,
    ReservedStatusResponse,
)

DEFAULT_RESERVATION_WINDOW_MINUTES = 15
MIN_RESERVATION_WINDOW_MINUTES = 1
MAX_RESERVATION_WINDOW_MINUTES = 120
HTTP_422_CODE = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", status.HTTP_422_UNPROCESSABLE_ENTITY)


def validate_reserved_status_params(
    station_id: int | None = None,
    connector_id: int | None = None,
    window_minutes: int = DEFAULT_RESERVATION_WINDOW_MINUTES,
) -> None:
    """
    Validate query parameters for reserved connector status evaluation
    (REQ-F2-21 / CS19-047).
    """
    if station_id is None and connector_id is None:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail="Must provide station_id or connector_id.",
        )
    if station_id is not None and station_id <= 0:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail="station_id must be a positive integer.",
        )
    if connector_id is not None and connector_id <= 0:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail="connector_id must be a positive integer.",
        )
    if window_minutes < MIN_RESERVATION_WINDOW_MINUTES or window_minutes > MAX_RESERVATION_WINDOW_MINUTES:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail=(
                f"window_minutes must be between {MIN_RESERVATION_WINDOW_MINUTES} "
                f"and {MAX_RESERVATION_WINDOW_MINUTES} minutes."
            ),
        )


def find_confirmed_booking_for_connector(
    db: Session,
    connector: Connector,
    charger: Charger | None = None,
    *,
    now_utc: datetime | None = None,
    window_minutes: int = DEFAULT_RESERVATION_WINDOW_MINUTES,
) -> tuple[bool, Booking | None, float | None]:
    """
    Check if a connector has an active confirmed booking starting within the next
    window_minutes (default 15 minutes per REQ-F2-21).
    Returns (is_reserved, matching_booking, minutes_until_booking).
    """
    now = now_utc or datetime.now(timezone.utc)
    now = _ensure_utc(now)
    window_end = now + timedelta(minutes=window_minutes)

    # 1. Direct match on connector_id
    direct_match = (
        db.query(Booking)
        .filter(
            Booking.connector_id == connector.id,
            Booking.status == BookingStatus.CONFIRMED,
            or_(
                and_(Booking.start_time >= now, Booking.start_time <= window_end),
                and_(Booking.start_time <= now, Booking.end_time > now),
            ),
        )
        .order_by(Booking.start_time.asc())
        .first()
    )
    if direct_match is not None:
        start_utc = _ensure_utc(direct_match.start_time)
        diff_sec = (start_utc - now).total_seconds()
        minutes_until = max(0.0, round(diff_sec / 60.0, 1))
        return True, direct_match, minutes_until

    # 2. Match via charger_id when connector_id is unset on booking
    target_charger_id = charger.id if charger is not None else connector.charger_id
    charger_bookings = (
        db.query(Booking)
        .outerjoin(Vehicle, Vehicle.id == Booking.vehicle_id)
        .filter(
            Booking.charger_id == target_charger_id,
            Booking.connector_id.is_(None),
            Booking.status == BookingStatus.CONFIRMED,
            or_(
                and_(Booking.start_time >= now, Booking.start_time <= window_end),
                and_(Booking.start_time <= now, Booking.end_time > now),
            ),
        )
        .order_by(Booking.start_time.asc())
        .all()
    )

    for b in charger_bookings:
        # If booking has a vehicle with a connector type, match compatibility
        if b.vehicle is not None and b.vehicle.connector_type is not None:
            v_type = _enum_to_str(b.vehicle.connector_type)
            c_type = _enum_to_str(connector.connector_type)
            if v_type != c_type:
                continue

        start_utc = _ensure_utc(b.start_time)
        diff_sec = (start_utc - now).total_seconds()
        minutes_until = max(0.0, round(diff_sec / 60.0, 1))
        return True, b, minutes_until

    return False, None, None


def resolve_connector_reserved_status(
    connector: Connector,
    charger: Charger,
    *,
    is_reserved: bool,
    now_utc: datetime | None = None,
) -> str:
    """
    Resolve the displayed connector status considering charger out-of-service,
    hardware faults/offline, and booking reservation state (REQ-F2-21).
    """
    if charger.is_out_of_service:
        return ConnectorStatus.OFFLINE.value

    raw = _enum_to_str(connector.status)
    if raw in (ConnectorStatus.FAULTED.value, ConnectorStatus.OFFLINE.value):
        return raw

    if is_reserved:
        return ConnectorStatus.RESERVED.value

    return raw


def get_reserved_status_display(
    db: Session,
    user: User,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
    window_minutes: int = DEFAULT_RESERVATION_WINDOW_MINUTES,
    reserved_only: bool = False,
    now_utc: datetime | None = None,
) -> ReservedStatusResponse:
    """
    Retrieve and evaluate Reserved status for connectors at a station or specific
    connector based on confirmed bookings starting within window_minutes (REQ-F2-21 / CS19-047).
    """
    validate_reserved_status_params(
        station_id=station_id,
        connector_id=connector_id,
        window_minutes=window_minutes,
    )
    station, include_inactive_chargers = _load_authorized_station(
        db,
        user,
        station_id=station_id,
        connector_id=connector_id,
    )

    visible_pairs: list[tuple[Charger, Connector]] = []
    for charger in sorted(station.chargers or [], key=lambda c: c.id or 0):
        if not include_inactive_chargers and not charger.is_active:
            continue
        for conn in sorted(charger.connectors or [], key=lambda k: k.id or 0):
            visible_pairs.append((charger, conn))

    error_map = _latest_error_codes_by_connector(
        db, [conn.id for _, conn in visible_pairs]
    )

    now = _ensure_utc(now_utc or datetime.now(timezone.utc))
    counts = {s.value: 0 for s in ConnectorStatus}
    last_status_update: datetime | None = None
    all_items: list[ReservedConnectorStatusItem] = []

    for charger, conn in visible_pairs:
        last_update_utc = _ensure_utc(conn.last_update)
        if last_status_update is None or last_update_utc > last_status_update:
            last_status_update = last_update_utc

        seconds_since = max(0, int((now - last_update_utc).total_seconds()))
        is_oos = bool(charger.is_out_of_service)

        is_reserved, booking, minutes_until = find_confirmed_booking_for_connector(
            db=db,
            connector=conn,
            charger=charger,
            now_utc=now,
            window_minutes=window_minutes,
        )

        display_status = resolve_connector_reserved_status(
            conn,
            charger,
            is_reserved=is_reserved,
            now_utc=now,
        )

        counts[display_status] = counts.get(display_status, 0) + 1

        all_items.append(
            ReservedConnectorStatusItem(
                connector_id=conn.id,
                charger_id=charger.id,
                charger_name=charger.name,
                station_id=station.id,
                station_name=station.name,
                gateway_id=charger.gateway_id,
                connector_type=_enum_to_str(conn.connector_type),
                power_kw=float(charger.power_kw),
                current_type=_enum_to_str(charger.current_type),
                raw_status=_enum_to_str(conn.status),
                status=display_status,
                is_reserved=is_reserved,
                reservation_window_minutes=window_minutes,
                booking_id=booking.id if booking else None,
                booking_user_id=booking.user_id if booking else None,
                booking_vehicle_id=booking.vehicle_id if booking else None,
                booking_start_time=_ensure_utc(booking.start_time) if booking else None,
                booking_end_time=_ensure_utc(booking.end_time) if booking else None,
                minutes_until_booking=minutes_until,
                last_update=last_update_utc,
                seconds_since_update=seconds_since,
                is_active=bool(charger.is_active),
                is_out_of_service=is_oos,
                out_of_service_reason=charger.out_of_service_reason,
                expected_return_time=(
                    _ensure_utc(charger.expected_return_time)
                    if charger.expected_return_time
                    else None
                ),
                latest_error_code=error_map.get(conn.id),
            )
        )

    displayed_items = all_items
    if connector_id is not None:
        displayed_items = [item for item in displayed_items if item.connector_id == connector_id]
    if reserved_only:
        displayed_items = [item for item in displayed_items if item.is_reserved]

    return ReservedStatusResponse(
        station_id=station.id,
        station_name=station.name,
        station_status=_enum_to_str(station.status),
        is_active=bool(station.is_active),
        reservation_window_minutes=window_minutes,
        total_connectors=len(all_items),
        reserved_connectors=counts[ConnectorStatus.RESERVED.value],
        available_connectors=counts[ConnectorStatus.AVAILABLE.value],
        occupied_connectors=counts[ConnectorStatus.OCCUPIED.value],
        faulted_connectors=counts[ConnectorStatus.FAULTED.value],
        offline_connectors=counts[ConnectorStatus.OFFLINE.value],
        unknown_connectors=0,
        last_status_update=last_status_update,
        evaluated_at=now,
        connectors=displayed_items,
    )
