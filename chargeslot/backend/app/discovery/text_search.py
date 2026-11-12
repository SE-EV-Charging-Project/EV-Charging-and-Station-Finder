"""
Station Free-Text Search Engine (SRS §5.2.1 / Page 18, 35 / REQ-F2-11 / CS19-037).

Allows charging stations to be searched by name, address, or geographic area.
Enforces the visibility gate (REQ-F2-03) and supports optional proximity filtering.
"""

from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.schemas.discovery import NearbyStationItem
from app.discovery.search import (
    haversine_distance,
    validate_search_params,
)
from app.discovery.views import compute_station_marker
from app.discovery.sorting import sort_station_items


MAX_QUERY_LENGTH = 100


def validate_text_search_query(query: str | None) -> str:
    """
    Validates text search query string per REQ-F2-11.
    Rejects empty, whitespace-only, or overly long queries with HTTP 422.
    """
    if query is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query cannot be empty or null (REQ-F2-11).",
        )

    clean = query.strip()
    if not clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Search query cannot be empty or only whitespace (REQ-F2-11).",
        )

    if len(clean) > MAX_QUERY_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Search query cannot exceed {MAX_QUERY_LENGTH} characters.",
        )

    return clean


def search_stations_by_text(
    db: Session,
    query: str,
    user: User | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    sort_by: str | None = None,
    sort_order: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, str, list[NearbyStationItem]]:
    """
    Performs case-insensitive free-text search on station name, address, or area (REQ-F2-11).
    Enforces visibility gate (REQ-F2-03): drivers only discover approved and active stations.
    """
    clean_query = validate_text_search_query(query)

    has_location = latitude is not None and longitude is not None
    if has_location and radius_km is not None:
        validate_search_params(latitude, longitude, radius_km)

    search_pattern = f"%{clean_query}%"

    # Base query with visibility gate (REQ-F2-03) and text search filter (REQ-F2-11)
    db_query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    ).filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
        or_(
            Station.name.ilike(search_pattern),
            Station.address.ilike(search_pattern),
        ),
    )

    candidates: Sequence[Station] = db_query.all()
    matching_items: list[NearbyStationItem] = []

    for station in candidates:
        dist = 0.0
        if has_location:
            dist = haversine_distance(latitude, longitude, station.latitude, station.longitude)
            if radius_km is not None and dist > radius_km:
                continue

        # Aggregate active chargers and connectors
        active_chargers = [
            c for c in station.chargers if c.is_active and not c.is_out_of_service
        ]
        all_connectors: list[Connector] = [
            conn for c in active_chargers for conn in c.connectors
        ]
        avail_connectors = [
            conn for conn in all_connectors if conn.status == ConnectorStatus.AVAILABLE
        ]

        connector_types_display = sorted(
            list(
                {
                    conn.connector_type.value
                    if hasattr(conn.connector_type, "value")
                    else str(conn.connector_type)
                    for conn in all_connectors
                }
            )
        )
        max_p_display = (
            max([c.power_kw for c in active_chargers]) if active_chargers else None
        )

        marker = compute_station_marker(station)

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
            total_connectors=len(all_connectors),
            available_connectors=len(avail_connectors),
            connector_types=connector_types_display,
            max_power_kw=max_p_display,
            price_per_kwh=getattr(station, "price_per_kwh", None),
            color_code=marker.color_code.value,
            status_label=marker.status_label,
            badge_text=marker.badge_text,
        )
        matching_items.append(item)

    # Sort matching items
    if sort_by is not None:
        matching_items, _, _ = sort_station_items(
            items=matching_items,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    elif has_location:
        matching_items.sort(key=lambda s: s.distance_km)
    else:
        # Relevance: stations where name starts with query first, then name contains, then address
        q_lower = clean_query.lower()
        matching_items.sort(
            key=lambda s: (
                0 if s.name.lower().startswith(q_lower)
                else (1 if q_lower in s.name.lower() else 2),
                s.name.lower(),
                s.id,
            )
        )

    total_count = len(matching_items)
    paginated_items = matching_items[offset : offset + limit]

    return total_count, clean_query, paginated_items

