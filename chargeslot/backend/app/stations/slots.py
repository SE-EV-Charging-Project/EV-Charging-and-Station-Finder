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

