"""
Estimated Wait Time Service (SRS §5.2.4 / Page 18 / Page 35 / REQ-F2-24 / CS19-050).

Displays an estimated wait time when all compatible connectors at a station are occupied,
calculated from the expected end of the active sessions.
"""

from datetime import datetime, timedelta, timezone
from typing import Sequence
from fastapi import HTTPException
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, joinedload

from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.connector_status_event import ConnectorStatusEvent
from app.models.maintenance import MaintenanceWindow
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.models.vehicle import ConnectorType, Vehicle
from app.schemas.dashboard import (
    CompatibleConnectorWaitItem,
    EstimatedWaitTimeResponse,
)
from app.stations.slots import does_slot_overlap_window, ensure_utc

DEFAULT_SESSION_ESTIMATE_MINUTES = 30
HTTP_422_CODE = 422


def _enum_to_str(val) -> str:
    """Normalize enum or string value to string."""
    if val is None:
        return ""
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def normalize_connector_type(raw_type: str | None) -> str | None:
    """
    Validate and normalize connector type string against ConnectorType enum.
    """
    if raw_type is None:
        return None
    clean = raw_type.strip()
    valid_map = {e.value.lower(): e.value for e in ConnectorType}
    # Also handle underscore/hyphen variants (e.g. 'Type_2', 'Type-2', 'TYPE2')
    valid_map["type2"] = ConnectorType.TYPE_2.value
    valid_map["type 2"] = ConnectorType.TYPE_2.value
    valid_map["type_2"] = ConnectorType.TYPE_2.value
    valid_map["type-2"] = ConnectorType.TYPE_2.value
    valid_map["ccs2"] = ConnectorType.CCS2.value
    valid_map["ccs 2"] = ConnectorType.CCS2.value
    valid_map["ccs_2"] = ConnectorType.CCS2.value
    valid_map["chademo"] = ConnectorType.CHADEMO.value
    valid_map["gbt"] = ConnectorType.GBT.value
    valid_map["gb/t"] = ConnectorType.GBT.value

    normalized = valid_map.get(clean.lower())
    if not normalized:
        valid_options = ", ".join(sorted(set(e.value for e in ConnectorType)))
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail=f"Invalid connector_type '{raw_type}'. Supported: {valid_options}.",
        )
    return normalized


def validate_wait_time_params(
    station_id: int | None,
    vehicle_id: int | None = None,
    connector_type: str | None = None,
) -> tuple[int, str | None]:
    """
    Validate parameters for estimated wait time request.
    """
    if station_id is None or station_id <= 0:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail="station_id must be a valid positive integer.",
        )

    norm_connector = normalize_connector_type(connector_type)
    return station_id, norm_connector


def calculate_connector_remaining_minutes(
    connector_id: int,
    charger_id: int,
    connector_type_str: str,
    active_bookings: Sequence[Booking],
    latest_event: ConnectorStatusEvent | None,
    ref_now: datetime,
    default_session_minutes: int = DEFAULT_SESSION_ESTIMATE_MINUTES,
) -> tuple[datetime, float, int | None]:
    """
    Compute expected end time and remaining minutes for an occupied connector.
    Calculated from active session / booking end time, or latest gateway event.
    """
    # 1. Match direct active booking on this connector (or charger with matching connector type)
    matched_booking: Booking | None = None
    for b in active_bookings:
        applies = False
        if b.connector_id is not None:
            applies = (b.connector_id == connector_id)
        elif b.charger_id == charger_id:
            if b.vehicle is not None and b.vehicle.connector_type is not None:
                applies = (_enum_to_str(b.vehicle.connector_type) == connector_type_str)
            else:
                applies = True

        if applies:
            matched_booking = b
            break

    if matched_booking is not None:
        end_time = ensure_utc(matched_booking.end_time)
        remaining = max(0.0, (end_time - ref_now).total_seconds() / 60.0)
        return end_time, remaining, matched_booking.id

    # 2. Estimate from gateway telemetry observation time
    if latest_event is not None and latest_event.observed_at is not None:
        event_time = ensure_utc(latest_event.observed_at)
        expected_end = event_time + timedelta(minutes=default_session_minutes)
        if expected_end > ref_now:
            remaining = (expected_end - ref_now).total_seconds() / 60.0
            return expected_end, max(0.0, remaining), None
        else:
            # Overran estimated time, assume buffer of 5 minutes
            buffer_end = ref_now + timedelta(minutes=5)
            return buffer_end, 5.0, None

    # 3. Default fallback session duration
    fallback_end = ref_now + timedelta(minutes=default_session_minutes)
    return fallback_end, float(default_session_minutes), None


def get_station_estimated_wait_time(
    db: Session,
    user: User,
    *,
    station_id: int,
    vehicle_id: int | None = None,
    connector_type: str | None = None,
    now_utc: datetime | None = None,
    default_session_minutes: int = DEFAULT_SESSION_ESTIMATE_MINUTES,
) -> EstimatedWaitTimeResponse:
    """
    Display estimated wait time when all compatible connectors at a station are occupied
    (REQ-F2-24 / CS19-050).
    """
    ref_now = ensure_utc(now_utc or datetime.now(timezone.utc))
    valid_station_id, explicit_conn_type = validate_wait_time_params(
        station_id=station_id,
        vehicle_id=vehicle_id,
        connector_type=connector_type,
    )

    # Resolve target compatibility filter
    target_connector_type: str | None = explicit_conn_type
    matched_vehicle: Vehicle | None = None

    if vehicle_id is not None:
        matched_vehicle = db.execute(
            select(Vehicle).where(Vehicle.id == vehicle_id)
        ).scalar_one_or_none()

        if not matched_vehicle:
            raise HTTPException(status_code=404, detail="Vehicle not found.")

        # Tenancy check: Drivers can only query for their own vehicle
        if user.role == UserRole.DRIVER and matched_vehicle.user_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Access forbidden: Vehicle does not belong to you.",
            )

        target_connector_type = _enum_to_str(matched_vehicle.connector_type)
    elif user.role == UserRole.DRIVER and target_connector_type is None:
        # Check if driver has a default vehicle
        default_veh = db.execute(
            select(Vehicle).where(Vehicle.user_id == user.id, Vehicle.is_default == True)
        ).scalar_one_or_none()
        if default_veh is not None:
            matched_vehicle = default_veh
            target_connector_type = _enum_to_str(default_veh.connector_type)

    # Fetch station with eager loading
    station = db.execute(
        select(Station)
        .options(
            joinedload(Station.chargers).joinedload(Charger.connectors),
            joinedload(Station.maintenance_windows),
        )
        .where(Station.id == valid_station_id)
    ).unique().scalar_one_or_none()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found.")

    # Scoping & RBAC
    if user.role == UserRole.DRIVER:
        if station.status != StationStatus.APPROVED or not station.is_active:
            raise HTTPException(status_code=404, detail="Station not found or inactive.")
    elif user.role == UserRole.OPERATOR:
        if station.operator_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Access forbidden: You do not operate this station.",
            )

    chargers = list(station.chargers or [])
    if user.role == UserRole.DRIVER:
        chargers = [ch for ch in chargers if ch.is_active]

    # Fetch active bookings on this station
    active_statuses = [
        BookingStatus.ACTIVE,
        BookingStatus.CONFIRMED,
        BookingStatus.HELD,
    ]
    bookings_stmt = (
        select(Booking)
        .options(joinedload(Booking.vehicle))
        .where(
            Booking.station_id == station.id,
            Booking.status.in_(active_statuses),
            Booking.end_time > ref_now,
            Booking.start_time <= ref_now + timedelta(minutes=15),
        )
    )
    active_bookings = list(db.execute(bookings_stmt).scalars().all())

    # Fetch maintenance windows overlapping ref_now
    m_windows = [
        mw for mw in (station.maintenance_windows or [])
        if does_slot_overlap_window(ref_now, ref_now + timedelta(minutes=1), mw.start_time, mw.end_time)
    ]

    # Evaluate compatible connectors
    compatible_items: list[CompatibleConnectorWaitItem] = []
    available_compatible = 0
    occupied_compatible = 0
    unavailable_count = 0

    earliest_available_dt: datetime | None = None
    min_wait_minutes: float | None = None
    earliest_free_conn_id: int | None = None

    for ch in chargers:
        ch_oos = ch.is_out_of_service
        ch_active = ch.is_active

        for cn in ch.connectors or []:
            conn_type_str = _enum_to_str(cn.connector_type)

            # Filter by compatibility if specified
            if target_connector_type is not None:
                # Compare normalized
                if conn_type_str.lower() != target_connector_type.lower():
                    continue

            # Check if charger is under maintenance
            in_maintenance = any(
                mw.charger_id is None or mw.charger_id == ch.id
                for mw in m_windows
            )

            is_broken = cn.status in (ConnectorStatus.FAULTED, ConnectorStatus.OFFLINE)
            is_operational = not ch_oos and ch_active and not is_broken and not in_maintenance

            # Check active booking currently occupying or reserved on this connector
            matching_booking = next(
                (
                    b for b in active_bookings
                    if (b.connector_id == cn.id)
                    or (b.charger_id == ch.id and (b.connector_id is None or b.connector_id == cn.id))
                ),
                None,
            )

            is_occupied = False
            is_available = False
            expected_end_dt: datetime | None = None
            remaining_mins: float | None = None
            b_id: int | None = None
            session_start_dt: datetime | None = None

            if not is_operational:
                unavailable_count += 1
            elif cn.status == ConnectorStatus.AVAILABLE and matching_booking is None:
                is_available = True
                available_compatible += 1
            else:
                # Connector is occupied or reserved with active booking
                is_occupied = True
                occupied_compatible += 1

                # Find latest gateway telemetry event for this connector
                latest_ev = db.execute(
                    select(ConnectorStatusEvent)
                    .where(
                        ConnectorStatusEvent.connector_id == cn.id,
                        ConnectorStatusEvent.new_status == ConnectorStatus.OCCUPIED,
                    )
                    .order_by(desc(ConnectorStatusEvent.observed_at))
                    .limit(1)
                ).scalar_one_or_none()

                expected_end_dt, remaining_mins, b_id = calculate_connector_remaining_minutes(
                    connector_id=cn.id,
                    charger_id=ch.id,
                    connector_type_str=conn_type_str,
                    active_bookings=active_bookings,
                    latest_event=latest_ev,
                    ref_now=ref_now,
                    default_session_minutes=default_session_minutes,
                )

                if matching_booking is not None:
                    session_start_dt = ensure_utc(matching_booking.start_time)
                elif latest_ev is not None:
                    session_start_dt = ensure_utc(latest_ev.observed_at)

                if min_wait_minutes is None or remaining_mins < min_wait_minutes:
                    min_wait_minutes = remaining_mins
                    earliest_available_dt = expected_end_dt
                    earliest_free_conn_id = cn.id

            compatible_items.append(
                CompatibleConnectorWaitItem(
                    connector_id=cn.id,
                    charger_id=ch.id,
                    charger_name=ch.name,
                    connector_type=conn_type_str,
                    power_kw=float(ch.power_kw),
                    current_type=_enum_to_str(ch.current_type),
                    status=_enum_to_str(cn.status),
                    is_operational=is_operational,
                    is_available=is_available,
                    is_occupied=is_occupied,
                    active_booking_id=b_id,
                    session_start_time=session_start_dt,
                    expected_end_time=expected_end_dt,
                    remaining_minutes=round(remaining_mins, 1) if remaining_mins is not None else None,
                )
            )

    total_compatible = len(compatible_items)

    # Determine final wait time and message
    if total_compatible == 0:
        all_occupied = False
        est_wait = None
        message = (
            f"No compatible connectors for '{target_connector_type}' found at station '{station.name}'."
            if target_connector_type
            else f"No connectors found at station '{station.name}'."
        )
    elif available_compatible > 0:
        all_occupied = False
        est_wait = 0.0
        earliest_available_dt = ref_now
        message = (
            f"{available_compatible} compatible connector(s) available now. No wait time required."
        )
    elif occupied_compatible > 0 and available_compatible == 0:
        # All compatible connectors are occupied per REQ-F2-24
        all_occupied = True
        est_wait = round(min_wait_minutes, 1) if min_wait_minutes is not None else float(default_session_minutes)
        rounded_wait = int(round(est_wait))
        message = (
            f"All compatible connectors are occupied. Estimated wait time: {rounded_wait} minute(s)."
        )
    else:
        # All compatible connectors are out of service or in maintenance
        all_occupied = False
        est_wait = None
        message = "All compatible connectors are currently faulted, offline, or under maintenance. No wait estimate available."

    return EstimatedWaitTimeResponse(
        station_id=station.id,
        station_name=station.name,
        station_status=_enum_to_str(station.status),
        is_active=station.is_active,
        vehicle_id=matched_vehicle.id if matched_vehicle else None,
        vehicle_connector_type=target_connector_type,
        total_compatible_connectors=total_compatible,
        available_compatible_connectors=available_compatible,
        occupied_compatible_connectors=occupied_compatible,
        unavailable_connectors=unavailable_count,
        all_compatible_occupied=all_occupied,
        estimated_wait_minutes=est_wait,
        expected_available_at=earliest_available_dt,
        earliest_free_connector_id=earliest_free_conn_id,
        message=message,
        calculated_at=ref_now,
        connectors=compatible_items,
    )
