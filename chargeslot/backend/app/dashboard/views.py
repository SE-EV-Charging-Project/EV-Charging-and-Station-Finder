from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.permissions import enforce_operator_scope
from app.discovery.views import _enum_to_str, compute_station_marker
from app.gateway.ingest import _ensure_utc
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.booking import Booking, BookingStatus
from app.models.charging_session_reading import ChargingSessionReading
from app.models.connector_status_event import ConnectorStatusEvent
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.dashboard import (
    ConnectorLiveStatusItem,
    LiveConnectorStatusDisplayResponse,
    LiveSessionMonitorResponse,
)
from app.stations.moderation import StationModerationService

_CANONICAL_STATUSES: dict[str, ConnectorStatus] = {
    s.value.lower(): s for s in ConnectorStatus
}
_CHARGING_EFFICIENCY = 0.9


def validate_live_status_params(
    station_id: int | None = None,
    connector_id: int | None = None,
    status_filter: str | None = None,
) -> ConnectorStatus | None:
    """
    Validate live status query parameters (REQ-F2-18 / CS19-044).
    Requires at least station_id or connector_id with positive IDs and valid status filter.
    """
    if station_id is None and connector_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Must provide station_id or connector_id.",
        )
    if station_id is not None and station_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id must be a positive integer.",
        )
    if connector_id is not None and connector_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="connector_id must be a positive integer.",
        )

    if status_filter is None:
        return None

    cleaned = status_filter.strip().lower()
    mapped = _CANONICAL_STATUSES.get(cleaned)
    if mapped is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid connector status filter '{status_filter}'. "
                "Expected one of: Available, Occupied, Reserved, Faulted, Offline."
            ),
        )
    return mapped


def _load_authorized_station(
    db: Session,
    user: User,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
) -> tuple[Station, bool]:
    """
    Resolve target Station from station_id/connector_id and enforce role-based visibility
    (BR-01 for drivers, REQ-F1-12 for operators). Returns (station, include_inactive_chargers).
    """
    target_station_id = station_id
    if target_station_id is None:
        row = (
            db.query(Charger.station_id)
            .join(Connector, Connector.charger_id == Charger.id)
            .filter(Connector.id == connector_id)
            .first()
        )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector with ID {connector_id} not found.",
            )
        target_station_id = row[0]

    station = (
        db.query(Station)
        .options(joinedload(Station.chargers).joinedload(Charger.connectors))
        .filter(Station.id == target_station_id)
        .first()
    )
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {target_station_id} not found.",
        )

    if user.role == UserRole.DRIVER:
        if not StationModerationService.is_station_visible_to_drivers(station):
            detail = (
                f"Connector with ID {connector_id} not found."
                if station_id is None
                else f"Station with ID {target_station_id} not found."
            )
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        include_inactive_chargers = False
    else:
        enforce_operator_scope(user, station.operator_id)
        include_inactive_chargers = True

    if connector_id is not None:
        matched_charger = None
        for charger in station.chargers or []:
            if any(conn.id == connector_id for conn in (charger.connectors or [])):
                matched_charger = charger
                break

        if matched_charger is None:
            exists = db.query(Connector.id).filter(Connector.id == connector_id).first()
            if exists is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"Connector {connector_id} does not belong to station {station.id}."
                    ),
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector with ID {connector_id} not found.",
            )

        if not include_inactive_chargers and not matched_charger.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector with ID {connector_id} not found.",
            )

    return station, include_inactive_chargers


def _latest_error_codes_by_connector(
    db: Session, connector_ids: list[int]
) -> dict[int, str | None]:
    """Fetch the most recent gateway error_code (if any) per connector in a single query."""
    if not connector_ids:
        return {}

    events = (
        db.query(ConnectorStatusEvent)
        .filter(ConnectorStatusEvent.connector_id.in_(connector_ids))
        .order_by(
            ConnectorStatusEvent.observed_at.desc(),
            ConnectorStatusEvent.id.desc(),
        )
        .all()
    )
    latest_errors: dict[int, str | None] = {}
    for ev in events:
        if ev.connector_id not in latest_errors:
            latest_errors[ev.connector_id] = ev.error_code
    return latest_errors


def get_live_connector_status_display(
    db: Session,
    user: User,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
    status_filter: str | None = None,
    apply_stale_fallback: bool = False,
    apply_reserved_status: bool = True,
) -> LiveConnectorStatusDisplayResponse:
    """
    Build the live connector status and last update display response for a station
    or specific connector (REQ-F2-18 / CS19-044).
    """
    canonical_filter = validate_live_status_params(
        station_id=station_id,
        connector_id=connector_id,
        status_filter=status_filter,
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

    now_utc = datetime.now(timezone.utc)
    counts = {s.value: 0 for s in ConnectorStatus}
    unknown_count = 0
    last_status_update: datetime | None = None
    all_items: list[ConnectorLiveStatusItem] = []

    if apply_stale_fallback:
        from app.dashboard.staleness import (
            STATUS_UNKNOWN,
            resolve_display_status_with_staleness,
        )

    for charger, conn in visible_pairs:
        is_oos = bool(charger.is_out_of_service)
        last_update_utc = _ensure_utc(conn.last_update)

        if apply_stale_fallback:
            effective_status, is_stale, seconds_since, _ = resolve_display_status_with_staleness(
                conn.status,
                last_update_utc,
                is_out_of_service=is_oos,
                now_utc=now_utc,
            )
            if effective_status == STATUS_UNKNOWN:
                unknown_count += 1
        else:
            effective_status = (
                ConnectorStatus.OFFLINE.value if is_oos else _enum_to_str(conn.status)
            )
            is_stale = False
            seconds_since = max(0, int((now_utc - last_update_utc).total_seconds()))

        if apply_reserved_status and effective_status not in (
            ConnectorStatus.OFFLINE.value,
            ConnectorStatus.FAULTED.value,
        ):
            from app.dashboard.state import find_confirmed_booking_for_connector
            is_res, _, _ = find_confirmed_booking_for_connector(
                db=db,
                connector=conn,
                charger=charger,
                now_utc=now_utc,
            )
            if is_res:
                effective_status = ConnectorStatus.RESERVED.value

        counts[effective_status] = counts.get(effective_status, 0) + 1
        if last_status_update is None or last_update_utc > last_status_update:
            last_status_update = last_update_utc

        expected_return = (
            _ensure_utc(charger.expected_return_time)
            if charger.expected_return_time is not None
            else None
        )

        all_items.append(
            ConnectorLiveStatusItem(
                connector_id=conn.id,
                charger_id=charger.id,
                charger_name=charger.name,
                station_id=station.id,
                station_name=station.name,
                gateway_id=charger.gateway_id,
                connector_type=_enum_to_str(conn.connector_type),
                power_kw=float(charger.power_kw),
                current_type=_enum_to_str(charger.current_type),
                status=effective_status,
                is_stale=is_stale,
                last_update=last_update_utc,
                seconds_since_update=seconds_since,
                is_active=bool(charger.is_active),
                is_out_of_service=is_oos,
                out_of_service_reason=charger.out_of_service_reason,
                expected_return_time=expected_return,
                latest_error_code=error_map.get(conn.id),
            )
        )

    displayed_items = all_items
    if connector_id is not None:
        displayed_items = [item for item in displayed_items if item.connector_id == connector_id]
    if canonical_filter is not None:
        displayed_items = [
            item for item in displayed_items if item.status == canonical_filter.value
        ]

    return LiveConnectorStatusDisplayResponse(
        station_id=station.id,
        station_name=station.name,
        station_status=_enum_to_str(station.status),
        is_active=bool(station.is_active),
        availability_summary=compute_station_marker(station),
        total_connectors=len(all_items),
        available_connectors=counts[ConnectorStatus.AVAILABLE.value],
        occupied_connectors=counts[ConnectorStatus.OCCUPIED.value],
        reserved_connectors=counts[ConnectorStatus.RESERVED.value],
        faulted_connectors=counts[ConnectorStatus.FAULTED.value],
        offline_connectors=counts[ConnectorStatus.OFFLINE.value],
        unknown_connectors=unknown_count,
        last_status_update=last_status_update,
        retrieved_at=now_utc,
        connectors=displayed_items,
    )


def get_live_session_monitor(
    db: Session,
    user: User,
    booking_id: int,
) -> LiveSessionMonitorResponse:
    """Return the latest meter-backed values for a driver's active booking."""
    booking = (
        db.query(Booking)
        .options(joinedload(Booking.vehicle))
        .filter(Booking.id == booking_id)
        .first()
    )
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Active booking {booking_id} not found.",
        )
    if booking.status != BookingStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Live session monitoring is available only for active bookings.",
        )
    if booking.charger_id is None or booking.station_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The active booking is not linked to a charger and station.",
        )

    station = db.query(Station).filter(Station.id == booking.station_id).first()
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station for the active booking was not found.",
        )
    if user.role == UserRole.DRIVER:
        if booking.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Active booking {booking_id} not found.",
            )
    elif user.role == UserRole.OPERATOR:
        enforce_operator_scope(user, station.operator_id)
    elif user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking driver, station operator, or an administrator can view this session.",
        )

    price_per_kwh = station.price_per_kwh
    if price_per_kwh is not None and price_per_kwh < 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Station tariff must not be negative.",
        )

    now_utc = datetime.now(timezone.utc)
    latest = (
        db.query(ChargingSessionReading)
        .filter(ChargingSessionReading.booking_id == booking.id)
        .order_by(
            ChargingSessionReading.observed_at.desc(),
            ChargingSessionReading.id.desc(),
        )
        .first()
    )
    if latest is None:
        return LiveSessionMonitorResponse(
            booking_id=booking.id,
            connector_id=booking.connector_id,
            charger_id=booking.charger_id,
            has_telemetry=False,
            cost_available=price_per_kwh is not None,
            is_stale=True,
            retrieved_at=now_utc,
        )

    first = (
        db.query(ChargingSessionReading)
        .filter(ChargingSessionReading.booking_id == booking.id)
        .order_by(
            ChargingSessionReading.observed_at.asc(),
            ChargingSessionReading.id.asc(),
        )
        .first()
    )
    if first is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Meter readings for the active booking are temporarily unavailable.",
        )
    energy_kwh = max(0.0, latest.energy_meter_kwh - first.energy_meter_kwh)
    elapsed_seconds = max(
        0, int((now_utc - _ensure_utc(first.observed_at)).total_seconds())
    )
    estimated_soc_pct: float | None = None
    if booking.vehicle is not None:
        if booking.vehicle.battery_kwh <= 0 or not 0 <= booking.start_soc <= 100:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Vehicle battery capacity or booking start charge is invalid.",
            )
        estimated_soc_pct = round(
            min(
                100.0,
                booking.start_soc
                + energy_kwh
                * _CHARGING_EFFICIENCY
                / booking.vehicle.battery_kwh
                * 100,
            ),
            1,
        )

    estimated_cost = (
        round(energy_kwh * price_per_kwh, 2)
        if price_per_kwh is not None
        else None
    )
    last_updated_at = _ensure_utc(latest.observed_at)
    seconds_since_update = max(0, int((now_utc - last_updated_at).total_seconds()))

    return LiveSessionMonitorResponse(
        booking_id=booking.id,
        connector_id=latest.connector_id,
        charger_id=booking.charger_id,
        has_telemetry=True,
        power_kw=latest.power_kw,
        energy_kwh=round(energy_kwh, 3),
        estimated_soc_pct=estimated_soc_pct,
        elapsed_seconds=elapsed_seconds,
        estimated_cost_inr=estimated_cost,
        cost_available=price_per_kwh is not None,
        last_updated_at=last_updated_at,
        is_stale=seconds_since_update > 30,
        retrieved_at=now_utc,
    )

