"""
Navigation, Route Preview, Handoff, and ETA Schemas (REQ-F2-25, REQ-F2-26, REQ-F2-27).

Covers:
- Route preview generation, road distance, travel time with traffic (REQ-F2-25 / CS19-051).
- Turn-by-turn navigation hand-off deep links (REQ-F2-26 / CS19-052).
- Driver ETA versus slot start comparison, late arrival warnings, and reschedule options (REQ-F2-27 / CS19-053).
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


# ---------------------------------------------------------------------------
# Navigation Hand-off Schemas (REQ-F2-26 / CS19-052)
# ---------------------------------------------------------------------------


class NavigationAppType(str, enum.Enum):
    """Supported navigation application target for deep linking (REQ-F2-26)."""

    GOOGLE_MAPS = "google_maps"
    APPLE_MAPS = "apple_maps"
    WAZE = "waze"
    GENERIC_GEO = "generic_geo"


class NavigationHandoffResponse(BaseModel):
    """
    Response model for turn-by-turn navigation hand-off via deep link (REQ-F2-26 / CS19-052).
    Generates standard deep links and URLs for device navigation applications.
    """

    station_id: int = Field(..., description="Target station ID")
    station_name: str = Field(..., description="Target station name")
    destination_address: str = Field(..., description="Target station address")
    destination_latitude: float = Field(..., description="Destination station latitude")
    destination_longitude: float = Field(..., description="Destination station longitude")
    origin_latitude: float | None = Field(default=None, description="Optional driver origin latitude")
    origin_longitude: float | None = Field(default=None, description="Optional driver origin longitude")
    app_type: str = Field(..., description="Selected primary navigation app type")
    deep_link_url: str = Field(..., description="Primary turn-by-turn deep link URL")
    google_maps_url: str = Field(..., description="Google Maps navigation link")
    apple_maps_url: str = Field(..., description="Apple Maps navigation link")
    waze_url: str = Field(..., description="Waze navigation link")
    geo_uri: str = Field(..., description="Standard RFC 5870 geo: URI for device app chooser")
    generated_at: datetime = Field(..., description="Timestamp when deep link was generated")


# ---------------------------------------------------------------------------
# ETA versus Slot Check Schemas (REQ-F2-27 / CS19-053)
# ---------------------------------------------------------------------------


class ETASlotStatus(str, enum.Enum):
    """Projected arrival timeliness relative to slot start and grace period (REQ-F2-27)."""

    ON_TIME = "on_time"
    LATE_WITHIN_GRACE = "late_within_grace"
    LATE_BEYOND_GRACE = "late_beyond_grace"


class RescheduleSlotOption(BaseModel):
    """Potential alternative time slot offered for rescheduling when late (REQ-F2-27)."""

    slot_id: int | None = Field(default=None, description="Unique slot ID if available")
    connector_id: int = Field(..., description="Target connector ID")
    connector_type: str = Field(..., description="Connector standard (e.g. CCS2, Type 2)")
    start_time: datetime = Field(..., description="Proposed slot start time")
    end_time: datetime = Field(..., description="Proposed slot end time")
    available: bool = Field(default=True, description="Whether slot is currently free")


class ETASlotCheckResponse(BaseModel):
    """
    Response model comparing driver ETA with slot start time (REQ-F2-27 / CS19-053).
    Warns driver and provides reschedule, extend, or cancel options when projected late.
    """

    booking_id: int = Field(..., description="Confirmed booking ID")
    booking_status: str = Field(..., description="Current status of the booking")
    station_id: int = Field(..., description="Target charging station ID")
    station_name: str = Field(..., description="Target charging station name")
    connector_id: int | None = Field(default=None, description="Assigned connector ID")
    slot_start_time: datetime = Field(..., description="Scheduled slot start time")
    slot_end_time: datetime = Field(..., description="Scheduled slot end time")
    grace_period_minutes: int = Field(default=15, description="Allowed check-in grace period in minutes (default 15)")
    grace_period_deadline: datetime = Field(..., description="Latest check-in time before no-show (slot_start + grace)")
    current_time: datetime = Field(..., description="Timestamp of evaluation")
    driver_latitude: float = Field(..., description="Driver current latitude")
    driver_longitude: float = Field(..., description="Driver current longitude")
    road_distance_km: float = Field(..., ge=0.0, description="Estimated road distance to station in km")
    estimated_travel_time_minutes: float = Field(..., ge=0.0, description="Estimated driving time in minutes with traffic")
    estimated_arrival_time: datetime = Field(..., description="Projected arrival time at station")
    is_late: bool = Field(..., description="True if projected arrival is after slot start time")
    projected_late_beyond_grace: bool = Field(
        ...,
        description="True if projected arrival exceeds slot start + grace period (triggers warning)",
    )
    delay_minutes: float = Field(..., description="Delay relative to slot start time in minutes (0 if on-time)")
    status: str = Field(..., description="Timeliness classification: on_time, late_within_grace, late_beyond_grace")
    warning_message: str | None = Field(
        default=None,
        description="Warning message presented to driver when running late",
    )
    action_options: list[str] = Field(
        default_factory=list,
        description="Available actions: reschedule, extend, cancel",
    )
    can_reschedule: bool = Field(default=False, description="Whether driver can reschedule to a later slot")
    can_extend: bool = Field(default=False, description="Whether driver can request slot start extension")
    can_cancel: bool = Field(default=False, description="Whether driver can cancel reservation")
    reschedule_options: list[RescheduleSlotOption] = Field(
        default_factory=list,
        description="Alternative available slot options later the same day",
    )
    checked_at: datetime = Field(..., description="Timestamp when check was executed")


# ---------------------------------------------------------------------------
# Route Cache & Fallback Schemas (REQ-F2-28 / CS19-054)
# ---------------------------------------------------------------------------


class CachedRouteResponse(BaseModel):
    """
    Route preview with 2-minute caching and straight-line fallback notice (REQ-F2-28 / CS19-054).
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
    road_distance_km: float = Field(..., ge=0.0, description="Road network distance or straight-line fallback in km")
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
        description="True when maps service is unavailable and straight-line fallback is shown (SR-F2-09 / REQ-F2-28)",
    )
    fallback_mode: str | None = Field(
        default=None,
        description="Fallback mode identifier: 'straight_line' when maps service is unavailable",
    )
    fallback_notice: str | None = Field(
        default=None,
        description="Notice message displayed when maps service is unavailable",
    )
    cache_hit: bool = Field(
        default=False,
        description="True if route was served from 2-minute route cache",
    )
    cache_age_seconds: float = Field(
        default=0.0,
        ge=0.0,
        description="Age of the cached route in seconds",
    )
    cache_ttl_seconds: int = Field(
        default=120,
        description="Cache time-to-live in seconds (120 seconds / 2 minutes per REQ-F2-28)",
    )
    cache_expires_at: datetime = Field(
        ...,
        description="Timestamp when cache entry will expire",
    )
    generated_at: datetime = Field(..., description="Timestamp when route preview was originally calculated")

