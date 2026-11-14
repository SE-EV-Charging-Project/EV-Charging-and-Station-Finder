"""
Navigation Route Module (REQ-F2-25 / CS19-051).

Re-exports route preview service functions from app.navigation.routes.
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

__all__ = [
    "calculate_route_preview",
    "normalize_traffic_condition",
    "validate_coordinates",
    "ROUTING_TIMEOUT_SECONDS",
    "ROAD_DISTANCE_EXPANSION_FACTOR",
    "TRAFFIC_SPEEDS_KMH",
    "FREE_FLOW_SPEED_KMH",
]

