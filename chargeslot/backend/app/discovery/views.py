"""
Station Availability Markers and Map View Generation (SRS §5.2.1, §5.2.2 / Page 18, 35 / REQ-F2-08).

Colour-codes each station marker by availability and shows the number of available
connectors out of the total, using a text label as well as colour for accessibility.
"""

from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.schemas.discovery import (
    MarkerColor,
    StationAvailabilityMarker,
)
from app.discovery.search import haversine_distance, validate_search_params


HEX_GREEN = "#4CAF50"
HEX_AMBER = "#FF9800"
HEX_RED = "#F44336"
HEX_GREY = "#9E9E9E"


def compute_station_marker(station: Station) -> StationAvailabilityMarker:
    """
    Computes the availability marker for a station per REQ-F2-08:
    - GREEN (#4CAF50): All connectors available.
    - AMBER (#FF9800): Partially available (some connectors free).
    - RED (#F44336): Fully occupied or reserved (0 available, but working).
    - GREY (#9E9E9E): Offline, faulted, inactive, or no operational connectors.
    Always includes accessible text label and badge text with available/total count.
    """
    # Only active, operational chargers are counted
    active_chargers = [
        c for c in station.chargers if c.is_active and not c.is_out_of_service
    ]
    operational_connectors: list[Connector] = [
        conn for c in active_chargers for conn in c.connectors
    ]

    total = len(operational_connectors)
    available = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.AVAILABLE
    )
    occupied = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.OCCUPIED
    )
    reserved = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.RESERVED
    )
    offline = sum(
        1
        for conn in operational_connectors
        if conn.status in (ConnectorStatus.FAULTED, ConnectorStatus.OFFLINE)
    )

    # Determine colour code, hex, and accessibility label
    if not station.is_active or total == 0:
        color_code = MarkerColor.GREY
        hex_color = HEX_GREY
        status_label = "Offline"
        badge_text = f"0/{total} Offline"
        is_operational = False
    elif available == total:
        color_code = MarkerColor.GREEN
        hex_color = HEX_GREEN
        status_label = "Available"
        badge_text = f"{available}/{total} Available"
        is_operational = True
    elif available > 0:
        color_code = MarkerColor.AMBER
        hex_color = HEX_AMBER
        status_label = "Partially Available"
        badge_text = f"{available}/{total} Available"
        is_operational = True
    elif occupied > 0 or reserved > 0:
        color_code = MarkerColor.RED
        hex_color = HEX_RED
        status_label = "Occupied"
        badge_text = f"0/{total} Occupied"
        is_operational = True
    else:
        color_code = MarkerColor.GREY
        hex_color = HEX_GREY
        status_label = "Offline"
        badge_text = f"0/{total} Offline"
        is_operational = False

    return StationAvailabilityMarker(
        station_id=station.id if station.id is not None else 0,
        name=station.name or "",
        latitude=station.latitude or 0.0,
        longitude=station.longitude or 0.0,
        total_connectors=total,
        available_connectors=available,
        occupied_connectors=occupied,
        reserved_connectors=reserved,
        offline_connectors=offline,
        color_code=color_code,
        hex_color=hex_color,
        status_label=status_label,
        badge_text=badge_text,
        is_operational=is_operational,
    )


def get_station_markers(
    db: Session,
    station_id: int | None = None,
    station_ids: list[int] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    user: User | None = None,
) -> list[StationAvailabilityMarker]:
    """
    Queries stations and generates availability markers with driver visibility gating
    (REQ-F2-03, REQ-F2-08).
    """
    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    )

    # Drivers only see approved and active stations (REQ-F2-03)
    query = query.filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )

    if station_id is not None:
        station = query.filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found or not active.",
            )
        return [compute_station_marker(station)]

    if station_ids:
        query = query.filter(Station.id.in_(station_ids))

    if latitude is not None and longitude is not None:
        rad = radius_km if radius_km is not None else 10.0
        validate_search_params(latitude, longitude, rad)
        stations = query.all()
        markers = []
        for s in stations:
            dist = haversine_distance(latitude, longitude, s.latitude, s.longitude)
            if dist <= rad:
                markers.append(compute_station_marker(s))
        return markers

    stations = query.all()
    return [compute_station_marker(s) for s in stations]
