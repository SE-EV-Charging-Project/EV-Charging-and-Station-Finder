"""
Booking package (SRS §5.3 / Feature 3: Battery-Aware Booking and Auto-Booking).
"""

from app.booking.battery import (
    compute_charging_cost,
    compute_charging_time_minutes,
    compute_slot_length_minutes,
    compute_usable_range,
    estimate_charging_cost,
    enter_battery_level,
    estimate_charging_time,
    get_vehicle_battery,
)
from app.booking.validators import validate_battery_level_input, get_battery_rules

__all__ = [
    "enter_battery_level",
    "get_vehicle_battery",
    "compute_usable_range",
    "compute_charging_time_minutes",
    "compute_slot_length_minutes",
    "compute_charging_cost",
    "estimate_charging_time",
    "estimate_charging_cost",
    "validate_battery_level_input",
    "get_battery_rules",
]
