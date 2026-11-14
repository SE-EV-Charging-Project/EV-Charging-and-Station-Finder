"""
Slot Timeline View Service (SRS §5.2.4 / Page 18 / Page 35 / REQ-F2-23 / CS19-049).

Displays, for a selected station and date, a slot timeline per connector
in which each 15-minute slot is shown as Free, Booked, Blocked or Past.
"""

from datetime import date, datetime, time, timedelta, timezone
from typing import Sequence
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.maintenance import MaintenanceWindow
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.schemas.dashboard import (
    ConnectorTimelineSummary,
    StationSlotTimelineResponse,
    TimelineSlotItem,
    TimelineSlotState,
)
from app.stations.slots import (
    BOOKABLE_SLOT_INTERVAL_MINUTES,
    MAX_SLOT_DAYS_AHEAD,
    does_slot_overlap_window,
    ensure_utc,
    parse_operating_hours,
)

HTTP_422_CODE = 422


def _enum_to_str(val) -> str:
    """Normalize enum or string value to string."""
    if val is None:
        return ""
    if hasattr(val, "value"):
        return str(val.value)
    return str(val)


def validate_slot_timeline_params(
    station_id: int | None = None,
    connector_id: int | None = None,
    target_date: date | None = None,
    status_filter: str | None = None,
    now_utc: datetime | None = None,
) -> tuple[date, TimelineSlotState | None]:
    """
    Validate slot timeline parameters per REQ-F2-23.

    - Must provide station_id or connector_id.
    - target_date defaults to today's date if None.
    - target_date cannot exceed 7 days ahead.
    - status_filter (if provided) must be one of 'Free', 'Booked', 'Blocked', 'Past'.
    """
    if station_id is None and connector_id is None:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail="Must provide station_id or connector_id.",
        )

    ref_now = ensure_utc(now_utc or datetime.now(timezone.utc))
    today = ref_now.date()
    max_date = today + timedelta(days=MAX_SLOT_DAYS_AHEAD)

    effective_date = target_date if target_date is not None else today

    if effective_date > max_date:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail=f"target_date cannot be more than {MAX_SLOT_DAYS_AHEAD} days ahead.",
        )

    parsed_filter: TimelineSlotState | None = None
    if status_filter:
        clean = status_filter.strip().capitalize()
        valid_states = {s.value: s for s in TimelineSlotState}
        if clean not in valid_states:
            raise HTTPException(
                status_code=HTTP_422_CODE,
                detail=f"Invalid status filter '{status_filter}'. Allowed: Free, Booked, Blocked, Past.",
            )
        parsed_filter = valid_states[clean]

    return effective_date, parsed_filter


def resolve_slot_timeline_state(
    slot_start: datetime,
    slot_end: datetime,
    ref_now: datetime,
    *,
    is_charger_oos: bool,
    oos_reason: str | None,
    is_charger_active: bool,
    is_connector_faulted_or_offline: bool,
    connector_status_str: str,
    maintenance_windows: Sequence[MaintenanceWindow],
    bookings: Sequence[Booking],
    charger_id: int,
    connector_id: int,
    connector_type_str: str,
) -> tuple[TimelineSlotState, str | None, int | None, str | None]:
    """
    Resolve slot timeline state into one of (Free, Booked, Blocked, Past)
    per SRS REQ-F2-23 precedence rules:

    1. Past: slot_end <= ref_now
    2. Blocked:
       - Charger out of service
       - Charger inactive
       - Connector Faulted / Offline
       - Overlaps scheduled maintenance window
    3. Booked: Overlaps active/confirmed/held booking for this connector/charger
    4. Free: Available for charging/booking
    """
    # 1. Past slot
    if slot_end <= ref_now:
        return TimelineSlotState.PAST, "Past slot", None, None

    # 2. Blocked by Charger Out-of-Service
    if is_charger_oos:
        reason_text = oos_reason or "Charger out of service"
        return TimelineSlotState.BLOCKED, f"Out of service: {reason_text}", None, None

    # 3. Blocked by Charger Inactive
    if not is_charger_active:
        return TimelineSlotState.BLOCKED, "Charger inactive", None, None

    # 4. Blocked by Connector Faulted / Offline
    if is_connector_faulted_or_offline:
        return TimelineSlotState.BLOCKED, f"Connector {connector_status_str}", None, None

    # 5. Blocked by Scheduled Maintenance Window
    for mw in maintenance_windows:
        if mw.charger_id is None or mw.charger_id == charger_id:
            if does_slot_overlap_window(slot_start, slot_end, mw.start_time, mw.end_time):
                return TimelineSlotState.BLOCKED, f"Maintenance: {mw.title}", None, None

    # 6. Booked by Active/Confirmed/Held booking
    for b in bookings:
        applies = False
        if b.connector_id is not None:
            applies = (b.connector_id == connector_id)
        elif b.charger_id == charger_id:
            if b.vehicle is not None and b.vehicle.connector_type is not None:
                applies = (_enum_to_str(b.vehicle.connector_type) == connector_type_str)
            else:
                applies = True

        if applies and does_slot_overlap_window(slot_start, slot_end, b.start_time, b.end_time):
            b_status = _enum_to_str(b.status)
            return TimelineSlotState.BOOKED, f"Booked: {b_status}", b.id, b_status

    # 7. Free
    return TimelineSlotState.FREE, None, None, None


def get_station_slot_timeline(
    db: Session,
    user: User,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
    target_date: date | None = None,
    status_filter: str | None = None,
    now_utc: datetime | None = None,
) -> StationSlotTimelineResponse:
    """
    Generate slot timeline per connector for a selected station and date (REQ-F2-23 / CS19-049).

    Each 15-minute slot is classified as Free, Booked, Blocked, or Past.
    """
    ref_now = ensure_utc(now_utc or datetime.now(timezone.utc))
    effective_date, parsed_filter = validate_slot_timeline_params(
        station_id=station_id,
        connector_id=connector_id,
        target_date=target_date,
        status_filter=status_filter,
        now_utc=ref_now,
    )

    # Resolve station
    target_station_id = station_id
    single_connector_filter = connector_id

    if single_connector_filter is not None and target_station_id is None:
        conn_record = db.execute(
            select(Connector)
            .options(joinedload(Connector.charger))
            .where(Connector.id == single_connector_filter)
        ).scalar_one_or_none()

        if not conn_record or not conn_record.charger:
            raise HTTPException(status_code=404, detail="Connector not found.")
        target_station_id = conn_record.charger.station_id

    station = db.execute(
        select(Station)
        .options(
            joinedload(Station.chargers).joinedload(Charger.connectors),
            joinedload(Station.maintenance_windows),
        )
        .where(Station.id == target_station_id)
    ).unique().scalar_one_or_none()

    if not station:
        raise HTTPException(status_code=404, detail="Station not found.")

    # RBAC & scoping
    if user.role == UserRole.DRIVER:
        if station.status != StationStatus.APPROVED or not station.is_active:
            raise HTTPException(status_code=404, detail="Station not found or inactive.")
    elif user.role == UserRole.OPERATOR:
        if station.operator_id != user.id:
            raise HTTPException(
                status_code=403,
                detail="Access forbidden: You do not operate this station.",
            )

    # Collect chargers
    chargers = list(station.chargers or [])
    if user.role == UserRole.DRIVER:
        chargers = [ch for ch in chargers if ch.is_active]

    # Parse operating hours
    open_time, close_time = parse_operating_hours(station.operating_hours or "24 hours")

    day_start_dt = datetime.combine(effective_date, open_time).replace(tzinfo=timezone.utc)
    day_end_dt = datetime.combine(effective_date, close_time).replace(tzinfo=timezone.utc)
    if close_time == time(23, 59, 59):
        day_end_dt = datetime.combine(effective_date + timedelta(days=1), time(0, 0)).replace(tzinfo=timezone.utc)

    # Fetch active maintenance windows for this day
    m_windows = [
        mw for mw in (station.maintenance_windows or [])
        if does_slot_overlap_window(day_start_dt, day_end_dt, mw.start_time, mw.end_time)
    ]

    # Fetch active bookings for this station on this day
    active_booking_statuses = [
        BookingStatus.CONFIRMED,
        BookingStatus.HELD,
        BookingStatus.ACTIVE,
    ]
    bookings_stmt = (
        select(Booking)
        .options(joinedload(Booking.vehicle))
        .where(
            Booking.station_id == station.id,
            Booking.status.in_(active_booking_statuses),
            Booking.end_time > day_start_dt,
            Booking.start_time < day_end_dt,
        )
    )
    active_bookings = list(db.execute(bookings_stmt).scalars().all())

    # Build timeline per connector
    connector_summaries: list[ConnectorTimelineSummary] = []
    total_timeline_slots = 0
    total_free_slots = 0
    total_booked_slots = 0
    total_blocked_slots = 0
    total_past_slots = 0

    delta = timedelta(minutes=BOOKABLE_SLOT_INTERVAL_MINUTES)

    for ch in chargers:
        ch_oos = ch.is_out_of_service
        ch_active = ch.is_active
        ch_reason = ch.out_of_service_reason

        for cn in ch.connectors or []:
            if single_connector_filter is not None and cn.id != single_connector_filter:
                continue

            conn_status_str = _enum_to_str(cn.status)
            is_hardware_broken = cn.status in (ConnectorStatus.FAULTED, ConnectorStatus.OFFLINE)
            is_operational = not ch_oos and ch_active and not is_hardware_broken

            conn_slots: list[TimelineSlotItem] = []
            conn_free = 0
            conn_booked = 0
            conn_blocked = 0
            conn_past = 0

            cur_start = day_start_dt
            while cur_start + delta <= day_end_dt:
                cur_end = cur_start + delta
                slot_key = f"slot-{station.id}-{ch.id}-{cn.id}-{cur_start.strftime('%Y%m%d%H%M')}"

                slot_state, blocked_reason, booking_id, booking_status = resolve_slot_timeline_state(
                    slot_start=cur_start,
                    slot_end=cur_end,
                    ref_now=ref_now,
                    is_charger_oos=ch_oos,
                    oos_reason=ch_reason,
                    is_charger_active=ch_active,
                    is_connector_faulted_or_offline=is_hardware_broken,
                    connector_status_str=conn_status_str,
                    maintenance_windows=m_windows,
                    bookings=active_bookings,
                    charger_id=ch.id,
                    connector_id=cn.id,
                    connector_type_str=_enum_to_str(cn.connector_type),
                )

                if slot_state == TimelineSlotState.FREE:
                    conn_free += 1
                elif slot_state == TimelineSlotState.BOOKED:
                    conn_booked += 1
                elif slot_state == TimelineSlotState.BLOCKED:
                    conn_blocked += 1
                elif slot_state == TimelineSlotState.PAST:
                    conn_past += 1

                item = TimelineSlotItem(
                    slot_id=slot_key,
                    connector_id=cn.id,
                    charger_id=ch.id,
                    start_time=cur_start,
                    end_time=cur_end,
                    duration_minutes=BOOKABLE_SLOT_INTERVAL_MINUTES,
                    status=slot_state,
                    is_available=(slot_state == TimelineSlotState.FREE),
                    blocked_reason=blocked_reason,
                    booking_id=booking_id,
                    booking_status=booking_status,
                )

                if parsed_filter is None or slot_state == parsed_filter:
                    conn_slots.append(item)

                cur_start += delta

            conn_total = conn_free + conn_booked + conn_blocked + conn_past
            total_timeline_slots += len(conn_slots) if parsed_filter else conn_total
            total_free_slots += conn_free
            total_booked_slots += conn_booked
            total_blocked_slots += conn_blocked
            total_past_slots += conn_past

            connector_summaries.append(
                ConnectorTimelineSummary(
                    connector_id=cn.id,
                    connector_type=_enum_to_str(cn.connector_type),
                    charger_id=ch.id,
                    charger_name=ch.name,
                    power_kw=float(ch.power_kw),
                    current_type=_enum_to_str(ch.current_type),
                    is_operational=is_operational,
                    target_date=effective_date.isoformat(),
                    total_slots=len(conn_slots) if parsed_filter else conn_total,
                    free_slots=conn_free,
                    booked_slots=conn_booked,
                    blocked_slots=conn_blocked,
                    past_slots=conn_past,
                    slots=conn_slots,
                )
            )

    return StationSlotTimelineResponse(
        station_id=station.id,
        station_name=station.name,
        station_status=_enum_to_str(station.status),
        is_active=station.is_active,
        operating_hours=station.operating_hours,
        target_date=effective_date.isoformat(),
        slot_interval_minutes=BOOKABLE_SLOT_INTERVAL_MINUTES,
        total_connectors=len(connector_summaries),
        total_slots=total_timeline_slots,
        total_free_slots=total_free_slots,
        total_booked_slots=total_booked_slots,
        total_blocked_slots=total_blocked_slots,
        total_past_slots=total_past_slots,
        connectors=connector_summaries,
        generated_at=ref_now,
    )
