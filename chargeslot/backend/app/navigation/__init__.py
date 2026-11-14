"""
Navigation Module (REQ-F2-25 / REQ-F2-26 / REQ-F2-27 / REQ-F2-28).

Provides route preview, navigation hand-off, arrival estimation, and route caching/fallbacks.
"""

from app.navigation.routes import (
    calculate_route_preview,
    normalize_traffic_condition,
    validate_coordinates,
    ROUTING_TIMEOUT_SECONDS,
    ROAD_DISTANCE_EXPANSION_FACTOR,
    TRAFFIC_SPEEDS_KMH,
    FREE_FLOW_SPEED_KMH,
)
from app.navigation.handoff import (
    generate_navigation_handoff,
    build_navigation_links,
    normalize_app_type,
)
from app.navigation.eta import (
    check_driver_eta_versus_slot,
    find_reschedule_options,
    DEFAULT_GRACE_PERIOD_MINUTES,
)

__all__ = [
    "calculate_route_preview",
    "normalize_traffic_condition",
    "validate_coordinates",
    "ROUTING_TIMEOUT_SECONDS",
    "ROAD_DISTANCE_EXPANSION_FACTOR",
    "TRAFFIC_SPEEDS_KMH",
    "FREE_FLOW_SPEED_KMH",
    "generate_navigation_handoff",
    "build_navigation_links",
    "normalize_app_type",
    "check_driver_eta_versus_slot",
    "find_reschedule_options",
    "DEFAULT_GRACE_PERIOD_MINUTES",
]
