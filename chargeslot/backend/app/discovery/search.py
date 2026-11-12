"""
Nearby Station Search and Geospatial Discovery (SRS §5.2.1 / Page 18, 35 / REQ-F2-07).

Implements great-circle Haversine distance calculation and radius-based station filtering
within the driver-selectable range (default 10 km, range 1 to 50 km).
"""

import math
from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User, UserRole
from app.schemas.discovery import NearbyStationItem


EARTH_RADIUS_KM = 6371.0
DEFAULT_SEARCH_RADIUS_KM = 10.0
MIN_SEARCH_RADIUS_KM = 1.0
MAX_SEARCH_RADIUS_KM = 50.0


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Computes the great-circle distance between two geographic coordinates on Earth in kilometers
    using the Haversine formula (REQ-F2-07).
    """
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * (math.sin(delta_lambda / 2.0) ** 2)
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return EARTH_RADIUS_KM * c


def validate_search_params(latitude: float, longitude: float, radius_km: float) -> None:
    """
    Validates geographic coordinates and selectable search radius per SRS REQ-F2-07.
    Rejects out-of-range or malformed values with HTTP 422.
    """
    if latitude < -90.0 or latitude > 90.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Latitude {latitude} is out of valid range [-90.0, 90.0] degrees.",
        )

    if longitude < -180.0 or longitude > 180.0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Longitude {longitude} is out of valid range [-180.0, 180.0] degrees.",
        )

    if radius_km < MIN_SEARCH_RADIUS_KM or radius_km > MAX_SEARCH_RADIUS_KM:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Radius {radius_km} km is out of valid range "
                f"[{MIN_SEARCH_RADIUS_KM}, {MAX_SEARCH_RADIUS_KM}] km (REQ-F2-07)."
            ),
        )


def search_nearby_stations(
    db: Session,
    latitude: float,
    longitude: float,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    limit: int = 50,
    user: User | None = None,
) -> list[NearbyStationItem]:
    """
    Finds and ranks stations within radius_km from (latitude, longitude).
    Enforces visibility gate (REQ-F2-03): drivers only discover approved and active stations.
    Returns stations sorted by ascending distance with connector availability metrics.
    """
    validate_search_params(latitude, longitude, radius_km)

    # Approximate degree deltas for database bounding box pre-filtering
    delta_lat = radius_km / 110.574
    cos_lat = max(math.cos(math.radians(latitude)), 0.001)
    delta_lon = radius_km / (111.320 * cos_lat)

    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    )

    # Driver discovery visibility rule: only approved, active stations are returned (REQ-F2-03 / REQ-F2-07)
    query = query.filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
        Station.latitude >= latitude - delta_lat,
        Station.latitude <= latitude + delta_lat,
        Station.longitude >= longitude - delta_lon,
        Station.longitude <= longitude + delta_lon,
    )

    candidate_stations: Sequence[Station] = query.all()

    results: list[NearbyStationItem] = []

    for station in candidate_stations:
        dist = haversine_distance(latitude, longitude, station.latitude, station.longitude)
        if dist <= radius_km:
            # Aggregate charger & connector statistics
            active_chargers = [
                c for c in station.chargers if c.is_active and not c.is_out_of_service
            ]
            all_connectors: list[Connector] = [
                conn for c in active_chargers for conn in c.connectors
            ]
            avail_connectors = [
                conn for conn in all_connectors if conn.status == ConnectorStatus.AVAILABLE
            ]

            connector_types = sorted(
                list({str(conn.connector_type.value) for conn in all_connectors})
            )
            max_power = (
                max([c.power_kw for c in active_chargers]) if active_chargers else None
            )

            tot = len(all_connectors)
            av = len(avail_connectors)
            if tot == 0:
                c_code = "grey"
                s_label = "Offline"
                b_text = "0/0 Offline"
            elif av == tot:
                c_code = "green"
                s_label = "Available"
                b_text = f"{av}/{tot} Available"
            elif av > 0:
                c_code = "amber"
                s_label = "Partially Available"
                b_text = f"{av}/{tot} Available"
            else:
                c_code = "red"
                s_label = "Occupied"
                b_text = f"0/{tot} Occupied"

            item = NearbyStationItem(
                id=station.id,
                name=station.name,
                address=station.address,
                latitude=station.latitude,
                longitude=station.longitude,
                distance_km=round(dist, 2),
                operating_hours=station.operating_hours,
                amenities=station.amenities or [],
                contact_phone=station.contact_phone,
                contact_email=station.contact_email,
                status=station.status.value,
                is_active=station.is_active,
                total_chargers=len(active_chargers),
                total_connectors=tot,
                available_connectors=av,
                connector_types=connector_types,
                max_power_kw=max_power,
                price_per_kwh=getattr(station, "price_per_kwh", None),
                color_code=c_code,
                status_label=s_label,
                badge_text=b_text,
            )
            results.append(item)

    # Sort results by distance ascending (closest first)
    results.sort(key=lambda s: s.distance_km)

    return results[:limit]

