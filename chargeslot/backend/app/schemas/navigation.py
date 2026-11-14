"""
Navigation and Route Preview Schemas (REQ-F2-25 / CS19-051).

Covers route preview generation, road distance, estimated travel time with
traffic, waypoints, and routing fallbacks.
"""

import enum
from datetime import datetime
from pydantic import BaseModel, Field


class TrafficCondition(str, enum.Enum):
    """Current traffic condition classification (REQ-F2-25)."""

    LOW = "low"
    NORMAL = "normal"
    HEAVY = "heavy"
    SEVERE = "severe"


class RouteWaypoint(BaseModel):
    """A waypoint along the computed navigation route."""

    step_index: int = Field(..., description="0-based waypoint index along the route")
    instruction: str = Field(..., description="Navigation direction or waypoint label")
    latitude: float = Field(..., description="Waypoint latitude [-90, 90]")
    longitude: float = Field(..., description="Waypoint longitude [-180, 180]")
    distance_km: float = Field(..., ge=0.0, description="Cumulative or step distance in km")
    duration_minutes: float = Field(..., ge=0.0, description="Estimated duration in minutes for this segment")


class RoutePreviewResponse(BaseModel):
    """
    Route preview response from driver location to a station (REQ-F2-25 / CS19-051).
    Displays route geometry, road distance, and travel time under current traffic.
    """

    station_id: int = Field(..., description="Target station ID")
    station_name: str = Field(..., description="Target station name")
    station_address: str = Field(..., description="Target station address")
    station_status: str = Field(..., description="Station approval status")
    is_active: bool = Field(..., description="Whether station is active")
    origin_latitude: float = Field(..., description="Driver origin latitude")
    origin_longitude: float = Field(..., description="Driver origin longitude")
    destination_latitude: float = Field(..., description="Station destination latitude")
    destination_longitude: float = Field(..., description="Station destination longitude")
    straight_line_distance_km: float = Field(..., ge=0.0, description="Great-circle distance in km")
    road_distance_km: float = Field(..., ge=0.0, description="Road network distance in km")
    estimated_travel_time_minutes: float = Field(..., ge=0.0, description="Estimated travel time in minutes")
    traffic_condition: str = Field(..., description="Current traffic state: low, normal, heavy, severe")
    traffic_delay_minutes: float = Field(..., ge=0.0, description="Delay attributed to traffic in minutes")
    average_speed_kmh: float = Field(..., ge=0.0, description="Estimated average speed in km/h")
    route_geometry: list[list[float]] = Field(
        default_factory=list,
        description="List of [latitude, longitude] coordinates tracing the route path",
    )
    waypoints: list[RouteWaypoint] = Field(
        default_factory=list,
        description="Turn-by-turn or preview waypoints along the route",
    )
    is_fallback: bool = Field(
        default=False,
        description="True if external routing service was unreachable and simulated road fallback was used (SR-F2-09)",
    )
    fallback_notice: str | None = Field(
        default=None,
        description="Notice message when fallback routing is active",
    )
    generated_at: datetime = Field(..., description="Timestamp when route preview was calculated")

