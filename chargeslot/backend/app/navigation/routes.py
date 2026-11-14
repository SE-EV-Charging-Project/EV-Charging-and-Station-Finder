"""
Navigation and Route Preview Service (REQ-F2-25 / CS19-051).

Implements route preview from the driver's location to a charging station,
showing the route geometry, road distance, and estimated travel time with current traffic.
Includes fallback handling when external routing is unavailable (SR-F2-09).
"""

from datetime import datetime, timezone
import math
import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.discovery.search import haversine_distance
from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.schemas.navigation import (
    RoutePreviewResponse,
    RouteWaypoint,
    TrafficCondition,
)

ROUTING_TIMEOUT_SECONDS = 3.0
ROAD_DISTANCE_EXPANSION_FACTOR = 1.25

# Base speeds (km/h) for various traffic conditions
TRAFFIC_SPEEDS_KMH: dict[TrafficCondition, float] = {
    TrafficCondition.LOW: 50.0,
    TrafficCondition.NORMAL: 35.0,
    TrafficCondition.HEAVY: 20.0,
    TrafficCondition.SEVERE: 12.0,
}

# Free-flow reference speed (km/h) used to calculate delay
FREE_FLOW_SPEED_KMH = 50.0


def validate_coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    """
    Validate geographic coordinates within standard ranges.
    Latitude: [-90.0, 90.0]
    Longitude: [-180.0, 180.0]
    """
    if latitude is None or longitude is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Latitude and longitude coordinates are required.",
        )
    if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Latitude and longitude must be numeric decimal values.",
        )
    if not (-90.0 <= latitude <= 90.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Latitude {latitude} out of valid range [-90.0, 90.0].",
        )
    if not (-180.0 <= longitude <= 180.0):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Longitude {longitude} out of valid range [-180.0, 180.0].",
        )
    return float(latitude), float(longitude)


def normalize_traffic_condition(traffic_condition: str | None) -> TrafficCondition:
    """
    Parse and normalize traffic condition query parameter.
    Defaults to TrafficCondition.NORMAL.
    """
    if traffic_condition is None or not str(traffic_condition).strip():
        return TrafficCondition.NORMAL

    normalized = str(traffic_condition).strip().lower()
    try:
        return TrafficCondition(normalized)
    except ValueError:
        valid_conditions = ", ".join(f"'{c.value}'" for c in TrafficCondition)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid traffic condition '{traffic_condition}'. Expected one of: {valid_conditions}.",
        )


def _generate_synthetic_waypoints(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    station_name: str,
    road_distance_km: float,
    total_duration_minutes: float,
) -> tuple[list[list[float]], list[RouteWaypoint]]:
    """
    Generates synthetic route geometry and preview waypoints when external routing
    engine is not active or during fallback (SR-F2-09).
    """
    if road_distance_km <= 0.001:
        geometry = [[origin_lat, origin_lon]]
        waypoints = [
            RouteWaypoint(
                step_index=0,
                instruction=f"Current location is at destination: {station_name}",
                latitude=round(origin_lat, 6),
                longitude=round(origin_lon, 6),
                distance_km=0.0,
                duration_minutes=0.0,
            )
        ]
        return geometry, waypoints

    steps_count = 5
    geometry: list[list[float]] = []
    waypoints: list[RouteWaypoint] = []

    instructions = [
        "Depart from current location toward station",
        "Continue along primary arterial corridor",
        "Follow EV charging signage toward destination precinct",
        "Turn into charging station access driveway",
        f"Arrive at destination: {station_name}",
    ]

    for i in range(steps_count):
        fraction = i / (steps_count - 1)
        # Interpolate coordinates
        curr_lat = round(origin_lat + fraction * (dest_lat - origin_lat), 6)
        curr_lon = round(origin_lon + fraction * (dest_lon - origin_lon), 6)
        geometry.append([curr_lat, curr_lon])

        step_distance = round(fraction * road_distance_km, 2)
        step_duration = round(fraction * total_duration_minutes, 1)

        waypoints.append(
            RouteWaypoint(
                step_index=i,
                instruction=instructions[i],
                latitude=curr_lat,
                longitude=curr_lon,
                distance_km=step_distance,
                duration_minutes=step_duration,
            )
        )

    return geometry, waypoints


def _try_external_routing(
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    station_name: str,
    traffic: TrafficCondition,
) -> tuple[float, float, float, float, list[list[float]], list[RouteWaypoint]] | None:
    """
    Attempts to fetch route details from an OSRM-compatible routing service if reachable.
    Returns (road_distance_km, duration_minutes, traffic_delay_minutes, avg_speed, geometry, waypoints) or None.
    """
    base_url = settings.ROUTING_SERVICE_URL.rstrip("/")
    if not base_url:
        return None

    try:
        url = f"{base_url}/route/v1/driving/{origin_lon:.6f},{origin_lat:.6f};{dest_lon:.6f},{dest_lat:.6f}"
        params = {
            "overview": "full",
            "geometries": "geojson",
            "steps": "true",
        }
        with httpx.Client(timeout=ROUTING_TIMEOUT_SECONDS) as client:
            resp = client.get(url, params=params)
            if resp.status_code != status.HTTP_200_OK:
                return None
            data = resp.json()
            if data.get("code") != "Ok" or not data.get("routes"):
                return None

            primary_route = data["routes"][0]
            road_distance_meters = float(primary_route.get("distance", 0.0))
            free_flow_seconds = float(primary_route.get("duration", 0.0))

            road_distance_km = round(road_distance_meters / 1000.0, 2)
            base_duration_minutes = free_flow_seconds / 60.0

            # Apply traffic factor
            speed_kmh = TRAFFIC_SPEEDS_KMH[traffic]
            if road_distance_km > 0 and speed_kmh > 0:
                adjusted_duration_minutes = round((road_distance_km / speed_kmh) * 60.0, 1)
                free_flow_minutes = (road_distance_km / FREE_FLOW_SPEED_KMH) * 60.0
                traffic_delay_minutes = max(0.0, round(adjusted_duration_minutes - free_flow_minutes, 1))
            else:
                adjusted_duration_minutes = 0.0
                traffic_delay_minutes = 0.0

            # Extract geometry coordinates: geojson is [lon, lat], convert to [lat, lon]
            geometry_coords = []
            if "geometry" in primary_route and "coordinates" in primary_route["geometry"]:
                for lon, lat in primary_route["geometry"]["coordinates"]:
                    geometry_coords.append([round(lat, 6), round(lon, 6)])

            # Extract waypoints from legs/steps
            waypoints: list[RouteWaypoint] = []
            step_idx = 0
            if "legs" in primary_route:
                for leg in primary_route["legs"]:
                    for step in leg.get("steps", []):
                        maneuver = step.get("maneuver", {})
                        location = maneuver.get("location", [dest_lon, dest_lat])
                        step_dist_km = round(step.get("distance", 0.0) / 1000.0, 2)
                        step_dur_mins = round(step.get("duration", 0.0) / 60.0, 1)
                        instruction = maneuver.get("instruction") or step.get("name") or "Continue"
                        waypoints.append(
                            RouteWaypoint(
                                step_index=step_idx,
                                instruction=instruction,
                                latitude=round(location[1], 6),
                                longitude=round(location[0], 6),
                                distance_km=step_dist_km,
                                duration_minutes=step_dur_mins,
                            )
                        )
                        step_idx += 1

            if not geometry_coords:
                geometry_coords = [[origin_lat, origin_lon], [dest_lat, dest_lon]]

            if not waypoints:
                _, waypoints = _generate_synthetic_waypoints(
                    origin_lat,
                    origin_lon,
                    dest_lat,
                    dest_lon,
                    station_name,
                    road_distance_km,
                    adjusted_duration_minutes,
                )

            return (
                road_distance_km,
                adjusted_duration_minutes,
                traffic_delay_minutes,
                speed_kmh,
                geometry_coords,
                waypoints,
            )

    except Exception:
        # Fall back gracefully to local deterministic calculations
        return None


def calculate_route_preview(
    db: Session,
    user: User,
    station_id: int,
    origin_latitude: float,
    origin_longitude: float,
    traffic_condition: str | None = None,
    departure_time: datetime | None = None,
) -> RoutePreviewResponse:
    """
    Calculates route preview from driver origin coordinates to destination station (REQ-F2-25 / CS19-051).

    Enforces:
    - Coordinate validation [-90, 90] and [-180, 180].
    - Station existence & RBAC access boundaries (REQ-F1-12, REQ-F2-01, REQ-F2-03).
    - Road distance & traffic-adjusted travel time.
    - Fallback road estimation and straight-line notice if external routing is offline (SR-F2-09).
    """
    origin_lat, origin_lon = validate_coordinates(origin_latitude, origin_longitude)
    traffic = normalize_traffic_condition(traffic_condition)

    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found",
        )

    # RBAC Access Controls
    if user.role == UserRole.DRIVER:
        # Drivers can only preview routes to approved, active stations (REQ-F2-03)
        if station.status != StationStatus.APPROVED or not station.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found",
            )
    elif user.role == UserRole.OPERATOR:
        # Operators can view their own stations regardless of status, or approved active stations.
        # Accessing another operator's unapproved/inactive station is forbidden.
        if station.operator_id != user.id:
            if station.status != StationStatus.APPROVED or not station.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Permission denied: cannot access another operator's station",
                )
    # Administrator has full preview access to all stations.

    straight_line_dist = round(
        haversine_distance(origin_lat, origin_lon, station.latitude, station.longitude),
        2,
    )

    external_result = _try_external_routing(
        origin_lat=origin_lat,
        origin_lon=origin_lon,
        dest_lat=station.latitude,
        dest_lon=station.longitude,
        station_name=station.name,
        traffic=traffic,
    )

    if external_result is not None:
        (
            road_distance_km,
            estimated_duration_minutes,
            traffic_delay_minutes,
            avg_speed_kmh,
            geometry,
            waypoints,
        ) = external_result
        is_fallback = False
        fallback_notice = None
    else:
        # Fallback road estimation (SR-F2-09)
        is_fallback = True
        fallback_notice = (
            "Maps routing service is temporarily unavailable. Showing calculated road distance "
            "and traffic estimate (SR-F2-09)."
        )

        if straight_line_dist <= 0.001:
            road_distance_km = 0.0
            estimated_duration_minutes = 0.0
            traffic_delay_minutes = 0.0
            avg_speed_kmh = TRAFFIC_SPEEDS_KMH[traffic]
        else:
            road_distance_km = round(straight_line_dist * ROAD_DISTANCE_EXPANSION_FACTOR, 2)
            avg_speed_kmh = TRAFFIC_SPEEDS_KMH[traffic]
            estimated_duration_minutes = round((road_distance_km / avg_speed_kmh) * 60.0, 1)

            free_flow_minutes = (road_distance_km / FREE_FLOW_SPEED_KMH) * 60.0
            traffic_delay_minutes = max(0.0, round(estimated_duration_minutes - free_flow_minutes, 1))

        geometry, waypoints = _generate_synthetic_waypoints(
            origin_lat=origin_lat,
            origin_lon=origin_lon,
            dest_lat=station.latitude,
            dest_lon=station.longitude,
            station_name=station.name,
            road_distance_km=road_distance_km,
            total_duration_minutes=estimated_duration_minutes,
        )

    now = datetime.now(timezone.utc)
    return RoutePreviewResponse(
        station_id=station.id,
        station_name=station.name,
        station_address=station.address,
        station_status=station.status.value if hasattr(station.status, "value") else str(station.status),
        is_active=bool(station.is_active),
        origin_latitude=origin_lat,
        origin_longitude=origin_lon,
        destination_latitude=round(station.latitude, 6),
        destination_longitude=round(station.longitude, 6),
        straight_line_distance_km=straight_line_dist,
        road_distance_km=road_distance_km,
        estimated_travel_time_minutes=estimated_duration_minutes,
        traffic_condition=traffic.value,
        traffic_delay_minutes=traffic_delay_minutes,
        average_speed_kmh=avg_speed_kmh,
        route_geometry=geometry,
        waypoints=waypoints,
        is_fallback=is_fallback,
        fallback_notice=fallback_notice,
        generated_at=now,
    )

