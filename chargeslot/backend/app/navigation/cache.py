"""
Route Cache and Fallback Service (REQ-F2-28 / CS19-054).

Caches route preview results for identical origin and destination pairs for up to 2 minutes
(120 seconds). When the maps service is unavailable, provides straight-line distance with
an explanatory notice so navigation and station discovery continue uninterrupted (SR-F2-09).
"""

from datetime import datetime, timedelta, timezone
import threading
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.discovery.search import haversine_distance
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.routes import (
    FREE_FLOW_SPEED_KMH,
    TRAFFIC_SPEEDS_KMH,
    calculate_route_preview,
    normalize_traffic_condition,
    validate_coordinates,
)
from app.schemas.navigation import (
    CachedRouteResponse,
    RouteWaypoint,
    TrafficCondition,
)

ROUTE_CACHE_TTL_SECONDS = 120  # 2 minutes cache TTL per REQ-F2-28
FALLBACK_NOTICE_TEXT = (
    "Notice: Maps routing service is unavailable. Showing straight-line distance fallback "
    "(REQ-F2-28 / SR-F2-09)."
)

# In-memory thread-safe route cache: key -> (payload_dict, cached_at, expires_at)
_cache_lock = threading.Lock()
_route_cache: dict[tuple, tuple[dict, datetime, datetime]] = {}


def clear_route_cache() -> None:
    """Clears all cached route entries (useful for testing and admin resets)."""
    with _cache_lock:
        _route_cache.clear()


def make_cache_key(
    station_id: int,
    origin_lat: float,
    origin_lon: float,
    traffic: str,
) -> tuple:
    """Constructs a deterministic cache lookup key."""
    return (
        station_id,
        round(origin_lat, 5),
        round(origin_lon, 5),
        traffic.strip().lower(),
    )


def _build_straight_line_fallback(
    station: Station,
    origin_lat: float,
    origin_lon: float,
    traffic: TrafficCondition,
    now: datetime,
) -> dict:
    """
    Constructs straight-line distance fallback payload when maps routing service is unavailable
    per REQ-F2-28 and SR-F2-09.
    """
    straight_line_dist = round(
        haversine_distance(origin_lat, origin_lon, station.latitude, station.longitude),
        2,
    )
    speed_kmh = TRAFFIC_SPEEDS_KMH[traffic]

    if straight_line_dist <= 0.001:
        road_distance = 0.0
        duration_minutes = 0.0
        traffic_delay = 0.0
        geometry = [[origin_lat, origin_lon]]
        waypoints = [
            RouteWaypoint(
                step_index=0,
                instruction=f"Arrived at destination: {station.name}",
                latitude=round(origin_lat, 6),
                longitude=round(origin_lon, 6),
                distance_km=0.0,
                duration_minutes=0.0,
            )
        ]
    else:
        road_distance = straight_line_dist  # REQ-F2-28: show straight-line distance
        duration_minutes = round((road_distance / speed_kmh) * 60.0, 1)
        free_flow_mins = (road_distance / FREE_FLOW_SPEED_KMH) * 60.0
        traffic_delay = max(0.0, round(duration_minutes - free_flow_mins, 1))

        geometry = [
            [round(origin_lat, 6), round(origin_lon, 6)],
            [round(station.latitude, 6), round(station.longitude, 6)],
        ]
        waypoints = [
            RouteWaypoint(
                step_index=0,
                instruction="Depart current location (direct straight-line trajectory)",
                latitude=round(origin_lat, 6),
                longitude=round(origin_lon, 6),
                distance_km=0.0,
                duration_minutes=0.0,
            ),
            RouteWaypoint(
                step_index=1,
                instruction=f"Arrive at destination: {station.name}",
                latitude=round(station.latitude, 6),
                longitude=round(station.longitude, 6),
                distance_km=road_distance,
                duration_minutes=duration_minutes,
            ),
        ]

    return {
        "station_id": station.id,
        "station_name": station.name,
        "station_address": station.address,
        "station_status": station.status.value if hasattr(station.status, "value") else str(station.status),
        "is_active": bool(station.is_active),
        "origin_latitude": round(origin_lat, 6),
        "origin_longitude": round(origin_lon, 6),
        "destination_latitude": round(station.latitude, 6),
        "destination_longitude": round(station.longitude, 6),
        "straight_line_distance_km": straight_line_dist,
        "road_distance_km": road_distance,
        "estimated_travel_time_minutes": duration_minutes,
        "traffic_condition": traffic.value,
        "traffic_delay_minutes": traffic_delay,
        "average_speed_kmh": speed_kmh,
        "route_geometry": geometry,
        "waypoints": waypoints,
        "is_fallback": True,
        "fallback_mode": "straight_line",
        "fallback_notice": FALLBACK_NOTICE_TEXT,
        "cache_ttl_seconds": ROUTE_CACHE_TTL_SECONDS,
        "generated_at": now,
    }


def get_cached_route_preview(
    db: Session,
    user: User,
    station_id: int,
    origin_latitude: float,
    origin_longitude: float,
    traffic_condition: str | None = None,
    force_fresh: bool = False,
    simulate_maps_unavailable: bool = False,
    current_time: datetime | None = None,
) -> CachedRouteResponse:
    """
    Retrieves route preview with 2-minute caching and straight-line fallback (REQ-F2-28 / CS19-054).

    Enforces:
    - Coordinate validation [-90, 90] and [-180, 180].
    - RBAC access controls: drivers only see approved active stations (REQ-F2-03).
    - 2-minute cache hit evaluation for identical origin-destination coordinates.
    - Fallback to straight-line distance with explanatory notice if maps service is unavailable (SR-F2-09).
    """
    origin_lat, origin_lon = validate_coordinates(origin_latitude, origin_longitude)
    traffic = normalize_traffic_condition(traffic_condition)

    now = current_time if current_time is not None else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found",
        )

    # RBAC Access Controls
    if user.role == UserRole.DRIVER:
        if station.status != StationStatus.APPROVED or not station.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found",
            )
    elif user.role == UserRole.OPERATOR:
        if station.operator_id != user.id:
            if station.status != StationStatus.APPROVED or not station.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Permission denied: cannot access another operator's station",
                )
    # Admin has full access

    cache_key = make_cache_key(station.id, origin_lat, origin_lon, traffic.value)

    # Check cache
    if not force_fresh and not simulate_maps_unavailable:
        with _cache_lock:
            if cache_key in _route_cache:
                data_dict, cached_at, expires_at = _route_cache[cache_key]
                if now < expires_at:
                    age_seconds = max(0.0, round((now - cached_at).total_seconds(), 1))
                    return CachedRouteResponse(
                        **data_dict,
                        cache_hit=True,
                        cache_age_seconds=age_seconds,
                    )

    # Cache miss, expired, or force_fresh: compute fresh route
    if simulate_maps_unavailable:
        base_payload = _build_straight_line_fallback(
            station=station,
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            traffic=traffic,
            now=now,
        )
    else:
        try:
            # Standard route preview
            preview = calculate_route_preview(
                db=db,
                user=user,
                station_id=station.id,
                origin_latitude=origin_lat,
                origin_longitude=origin_lon,
                traffic_condition=traffic.value,
            )
            base_payload = preview.model_dump()
            base_payload["fallback_mode"] = "straight_line" if preview.is_fallback else None
            if preview.is_fallback:
                base_payload["fallback_notice"] = FALLBACK_NOTICE_TEXT
                base_payload["road_distance_km"] = base_payload["straight_line_distance_km"]
        except Exception:
            # Maps service unavailable / routing engine error -> fallback (SR-F2-09)
            base_payload = _build_straight_line_fallback(
                station=station,
                origin_lat=origin_lat,
                origin_lon=origin_lon,
                traffic=traffic,
                now=now,
            )

    cached_at = now
    expires_at = cached_at + timedelta(seconds=ROUTE_CACHE_TTL_SECONDS)
    base_payload["generated_at"] = now
    base_payload["cache_ttl_seconds"] = ROUTE_CACHE_TTL_SECONDS
    base_payload["cache_expires_at"] = expires_at

    with _cache_lock:
        _route_cache[cache_key] = (base_payload, cached_at, expires_at)

    return CachedRouteResponse(
        **base_payload,
        cache_hit=False,
        cache_age_seconds=0.0,
    )
