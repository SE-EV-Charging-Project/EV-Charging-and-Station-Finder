"""
Slot Generation and Availability Management (SRS §5.2.4 / Page 35 / REQ-F2-06).

Ensures that slots are generated only within opening hours and never overlap
with scheduled maintenance windows.
"""
from datetime import datetime, date, time, timedelta, timezone
from typing import Sequence
from app.models.maintenance import MaintenanceWindow
from app.schemas.maintenance import SlotItem


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime object is timezone-aware UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def does_slot_overlap_window(
    slot_start: datetime,
    slot_end: datetime,
    window_start: datetime,
    window_end: datetime,
) -> bool:
    """
    Check if a slot [slot_start, slot_end) overlaps with a maintenance window [window_start, window_end).
    Two non-empty intervals overlap if and only if: max(start1, start2) < min(end1, end2).
    """
    s_start = ensure_utc(slot_start)
    s_end = ensure_utc(slot_end)
    w_start = ensure_utc(window_start)
    w_end = ensure_utc(window_end)

    return max(s_start, w_start) < min(s_end, w_end)


def filter_slots_by_maintenance(
    slots: Sequence[SlotItem],
    maintenance_windows: Sequence[MaintenanceWindow],
) -> tuple[list[SlotItem], list[SlotItem]]:
    """
    Given a sequence of slots and maintenance windows for a station,
    partitions slots into (available_slots, removed_slots).

    If a slot overlaps with any maintenance window affecting its charger
    (or affecting the entire station if charger_id is None), it is removed from availability.
    """
    available_slots: list[SlotItem] = []
    removed_slots: list[SlotItem] = []

    for slot in slots:
        overlapping_window: MaintenanceWindow | None = None

        for window in maintenance_windows:
            # Check if window applies to this slot's charger or entire station
            if window.charger_id is None or slot.charger_id is None or window.charger_id == slot.charger_id:
                if does_slot_overlap_window(slot.start_time, slot.end_time, window.start_time, window.end_time):
                    overlapping_window = window
                    break

        if overlapping_window is not None:
            # Slot is removed from availability per REQ-F2-06
            removed_slot = SlotItem(
                charger_id=slot.charger_id,
                start_time=slot.start_time,
                end_time=slot.end_time,
                is_available=False,
                blocked_reason=f"Maintenance: {overlapping_window.title} (ID #{overlapping_window.id})",
            )
            removed_slots.append(removed_slot)
        else:
            available_slots.append(
                SlotItem(
                    charger_id=slot.charger_id,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    is_available=True,
                    blocked_reason=None,
                )
            )

    return available_slots, removed_slots


def parse_operating_hours(operating_hours: str) -> tuple[time, time]:
    """
    Parse opening hours string (e.g. '08:00 - 20:00', '08:00-22:00', '24 hours').
    Defaults to 00:00 to 23:59 for '24 hours' or unparseable formats.
    """
    clean = (operating_hours or "").strip().lower()
    if not clean or "24 hour" in clean or clean == "all day":
        return time(0, 0), time(23, 59, 59)

    parts = clean.split("-")
    if len(parts) == 2:
        try:
            start_parts = [int(p) for p in parts[0].strip().split(":")]
            end_parts = [int(p) for p in parts[1].strip().split(":")]
            start_time = time(start_parts[0], start_parts[1])
            end_time = time(end_parts[0], end_parts[1])
            return start_time, end_time
        except Exception:
            pass

    return time(0, 0), time(23, 59, 59)


def generate_available_slots_for_day(
    target_date: date,
    operating_hours: str,
    maintenance_windows: Sequence[MaintenanceWindow],
    charger_id: int | None = None,
    slot_duration_minutes: int = 30,
) -> tuple[list[SlotItem], list[SlotItem]]:
    """
    Generates time slots for a specific day within operating hours,
    and removes any slots overlapping with maintenance windows (SRS §5.2.4).
    """
    open_time, close_time = parse_operating_hours(operating_hours)

    start_dt = datetime.combine(target_date, open_time).replace(tzinfo=timezone.utc)
    # If close_time is 23:59:59 or end of day, round up
    end_dt = datetime.combine(target_date, close_time).replace(tzinfo=timezone.utc)
    if close_time == time(23, 59, 59):
        end_dt = datetime.combine(target_date + timedelta(days=1), time(0, 0)).replace(tzinfo=timezone.utc)

    candidate_slots: list[SlotItem] = []
    current_start = start_dt
    delta = timedelta(minutes=slot_duration_minutes)

    while current_start + delta <= end_dt:
        candidate_slots.append(
            SlotItem(
                charger_id=charger_id,
                start_time=current_start,
                end_time=current_start + delta,
                is_available=True,
            )
        )
        current_start += delta

    return filter_slots_by_maintenance(candidate_slots, maintenance_windows)


BOOKABLE_SLOT_INTERVAL_MINUTES = 15
MAX_SLOT_DAYS_AHEAD = 7
MIN_SLOT_DAYS_AHEAD = 1
HTTP_422_CODE = 422


def validate_slot_generation_params(
    station_id: int | None = None,
    connector_id: int | None = None,
    days_ahead: int = MAX_SLOT_DAYS_AHEAD,
    target_date: date | None = None,
    now_utc: datetime | None = None,
) -> tuple[date, date, int]:
    """
    Validate slot generation parameters per SRS REQ-F2-22 (up to 7 days ahead).
    Returns (start_date, end_date, effective_days_ahead).
    """
    from fastapi import HTTPException

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
    if days_ahead < MIN_SLOT_DAYS_AHEAD or days_ahead > MAX_SLOT_DAYS_AHEAD:
        raise HTTPException(
            status_code=HTTP_422_CODE,
            detail=f"days_ahead must be between {MIN_SLOT_DAYS_AHEAD} and {MAX_SLOT_DAYS_AHEAD} days.",
        )

    ref_now = ensure_utc(now_utc or datetime.now(timezone.utc))
    today = ref_now.date()
    max_date = today + timedelta(days=MAX_SLOT_DAYS_AHEAD)

    if target_date is not None:
        if target_date < today:
            raise HTTPException(
                status_code=HTTP_422_CODE,
                detail="target_date cannot be in the past.",
            )
        if target_date > max_date:
            raise HTTPException(
                status_code=HTTP_422_CODE,
                detail=f"target_date cannot be more than {MAX_SLOT_DAYS_AHEAD} days ahead.",
            )
        return target_date, target_date, 1

    end_date = today + timedelta(days=days_ahead - 1)
    return today, end_date, days_ahead


def generate_station_bookable_slots(
    db,
    user,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
    days_ahead: int = MAX_SLOT_DAYS_AHEAD,
    target_date: date | None = None,
    available_only: bool = False,
    now_utc: datetime | None = None,
):
    """
    Generate bookable 15-minute slots for every connector up to 7 days ahead
    (REQ-F2-22 / CS19-048 / SW Architecture GET /api/v1/stations/slot-generation).
    """
    from app.dashboard.views import _load_authorized_station
    from app.discovery.views import _enum_to_str
    from app.models.booking import Booking, BookingStatus
    from app.models.booking_slot_claim import BookingSlotClaim
    from app.models.charger import Charger, Connector, ConnectorStatus
    from app.models.maintenance import MaintenanceWindow
    from app.models.vehicle import Vehicle
    from app.schemas.station import (
        BookableSlotItem,
        ConnectorSlotsSummary,
        StationBookableSlotsResponse,
    )

    start_date, end_date, effective_days = validate_slot_generation_params(
        station_id=station_id,
        connector_id=connector_id,
        days_ahead=days_ahead,
        target_date=target_date,
        now_utc=now_utc,
    )

    station, include_inactive = _load_authorized_station(
        db,
        user,
        station_id=station_id,
        connector_id=connector_id,
    )

    ref_now = ensure_utc(now_utc or datetime.now(timezone.utc))
    open_time, close_time = parse_operating_hours(station.operating_hours)

    # Determine overall time bounds
    range_start = datetime.combine(start_date, time(0, 0)).replace(tzinfo=timezone.utc)
    range_end = datetime.combine(end_date + timedelta(days=1), time(0, 0)).replace(tzinfo=timezone.utc)

    # Query overlapping maintenance windows
    m_windows = (
        db.query(MaintenanceWindow)
        .filter(
            MaintenanceWindow.station_id == station.id,
            MaintenanceWindow.start_time < range_end,
            MaintenanceWindow.end_time > range_start,
        )
        .all()
    )

    # Query overlapping active bookings
    active_bookings = (
        db.query(Booking)
        .outerjoin(Vehicle, Vehicle.id == Booking.vehicle_id)
        .filter(
            Booking.station_id == station.id,
            Booking.status.in_(
                [BookingStatus.HELD, BookingStatus.CONFIRMED, BookingStatus.ACTIVE]
            ),
            Booking.start_time < range_end,
            Booking.end_time > range_start,
        )
        .all()
    )

    # Query atomic slot claims if any
    slot_claims = (
        db.query(BookingSlotClaim)
        .filter(
            BookingSlotClaim.slot_start_time >= range_start,
            BookingSlotClaim.slot_start_time < range_end,
        )
        .all()
    )
    claimed_slots = {(sc.charger_id, ensure_utc(sc.slot_start_time)) for sc in slot_claims}

    # Filter target connectors
    chargers_list = sorted(station.chargers or [], key=lambda c: c.id or 0)
    visible_pairs: list[tuple[Charger, Connector]] = []
    for ch in chargers_list:
        if not include_inactive and not ch.is_active:
            continue
        for cn in sorted(ch.connectors or [], key=lambda k: k.id or 0):
            if connector_id is not None and cn.id != connector_id:
                continue
            visible_pairs.append((ch, cn))

    total_station_slots = 0
    total_station_avail = 0
    total_station_booked = 0
    total_station_blocked = 0
    delta = timedelta(minutes=BOOKABLE_SLOT_INTERVAL_MINUTES)

    connector_summaries: list[ConnectorSlotsSummary] = []

    # Generate dates in range
    num_days = (end_date - start_date).days + 1
    dates_list = [start_date + timedelta(days=i) for i in range(num_days)]

    for ch, cn in visible_pairs:
        is_oos = bool(ch.is_out_of_service)
        conn_status_str = _enum_to_str(cn.status)
        is_hardware_broken = conn_status_str in (ConnectorStatus.FAULTED.value, ConnectorStatus.OFFLINE.value)
        is_operational = not is_oos and not is_hardware_broken and bool(ch.is_active)

        conn_slots: list[BookableSlotItem] = []
        conn_avail_count = 0
        conn_booked_count = 0
        conn_blocked_count = 0

        for cur_date in dates_list:
            day_start = datetime.combine(cur_date, open_time).replace(tzinfo=timezone.utc)
            if close_time == time(23, 59, 59):
                day_end = datetime.combine(cur_date + timedelta(days=1), time(0, 0)).replace(tzinfo=timezone.utc)
            else:
                day_end = datetime.combine(cur_date, close_time).replace(tzinfo=timezone.utc)

            cur_slot_start = day_start
            while cur_slot_start + delta <= day_end:
                cur_slot_end = cur_slot_start + delta
                slot_key = f"conn_{cn.id}_{int(cur_slot_start.timestamp())}"

                is_available = True
                is_booked = False
                is_maintenance = False
                is_past = False
                blocked_reason = None
                matched_booking_id = None
                matched_booking_status = None

                # 1. Past check
                if cur_slot_end <= ref_now:
                    is_available = False
                    is_past = True
                    blocked_reason = "Past slot"

                # 2. Charger Out-of-Service
                elif is_oos:
                    is_available = False
                    reason_text = ch.out_of_service_reason or "Charger out of service"
                    blocked_reason = f"Out of service: {reason_text}"

                # 3. Charger Inactive
                elif not ch.is_active:
                    is_available = False
                    blocked_reason = "Charger inactive"

                # 4. Connector Faulted or Offline
                elif is_hardware_broken:
                    is_available = False
                    blocked_reason = f"Connector {conn_status_str}"

                # 5. Maintenance window overlap
                else:
                    for mw in m_windows:
                        if mw.charger_id is None or mw.charger_id == ch.id:
                            if does_slot_overlap_window(cur_slot_start, cur_slot_end, mw.start_time, mw.end_time):
                                is_available = False
                                is_maintenance = True
                                blocked_reason = f"Maintenance: {mw.title}"
                                break

                # 6. Booking overlap
                if is_available:
                    # Check atomic claims
                    if (ch.id, cur_slot_start) in claimed_slots:
                        is_available = False
                        is_booked = True
                        blocked_reason = "Booked"

                    if not is_booked:
                        for b in active_bookings:
                            # Direct connector match or charger match
                            applies_to_conn = False
                            if b.connector_id is not None:
                                applies_to_conn = (b.connector_id == cn.id)
                            elif b.charger_id == ch.id:
                                if b.vehicle is not None and b.vehicle.connector_type is not None:
                                    applies_to_conn = (_enum_to_str(b.vehicle.connector_type) == _enum_to_str(cn.connector_type))
                                else:
                                    applies_to_conn = True

                            if applies_to_conn and does_slot_overlap_window(
                                cur_slot_start, cur_slot_end, b.start_time, b.end_time
                            ):
                                is_available = False
                                is_booked = True
                                matched_booking_id = b.id
                                matched_booking_status = _enum_to_str(b.status)
                                blocked_reason = f"Booked: {matched_booking_status}"
                                break

                # Metrics update
                if is_available:
                    conn_avail_count += 1
                elif is_booked:
                    conn_booked_count += 1
                else:
                    conn_blocked_count += 1

                item = BookableSlotItem(
                    slot_id=slot_key,
                    station_id=station.id,
                    charger_id=ch.id,
                    charger_name=ch.name,
                    connector_id=cn.id,
                    connector_type=_enum_to_str(cn.connector_type),
                    power_kw=float(ch.power_kw),
                    current_type=_enum_to_str(ch.current_type),
                    start_time=cur_slot_start,
                    end_time=cur_slot_end,
                    duration_minutes=BOOKABLE_SLOT_INTERVAL_MINUTES,
                    is_available=is_available,
                    is_bookable=is_available,
                    is_booked=is_booked,
                    is_maintenance=is_maintenance,
                    is_past=is_past,
                    blocked_reason=blocked_reason,
                    booking_id=matched_booking_id,
                    booking_status=matched_booking_status,
                )

                if not available_only or is_available:
                    conn_slots.append(item)

                cur_slot_start += delta

        total_station_slots += len(conn_slots) if available_only else (conn_avail_count + conn_booked_count + conn_blocked_count)
        total_station_avail += conn_avail_count
        total_station_booked += conn_booked_count
        total_station_blocked += conn_blocked_count

        connector_summaries.append(
            ConnectorSlotsSummary(
                connector_id=cn.id,
                connector_type=_enum_to_str(cn.connector_type),
                charger_id=ch.id,
                charger_name=ch.name,
                power_kw=float(ch.power_kw),
                current_type=_enum_to_str(ch.current_type),
                is_operational=is_operational,
                total_slots=len(conn_slots) if available_only else (conn_avail_count + conn_booked_count + conn_blocked_count),
                available_slots=conn_avail_count,
                booked_slots=conn_booked_count,
                blocked_slots=conn_blocked_count,
                slots=conn_slots,
            )
        )

    return StationBookableSlotsResponse(
        station_id=station.id,
        station_name=station.name,
        operating_hours=station.operating_hours,
        slot_interval_minutes=BOOKABLE_SLOT_INTERVAL_MINUTES,
        days_ahead=effective_days,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        total_connectors=len(connector_summaries),
        total_slots=total_station_slots,
        total_available_slots=total_station_avail,
        total_booked_slots=total_station_booked,
        total_blocked_slots=total_station_blocked,
        connectors=connector_summaries,
        generated_at=ref_now,
    )


