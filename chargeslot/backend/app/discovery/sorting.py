"""
Station Discovery Sorting Engine (SRS §5.2.1 / Page 18, 35 / REQ-F2-10).

Allows station discovery results to be sorted by:
- distance: Ascending by default (nearest first).
- price: Ascending by default (cheapest tariff per kWh first).
- power: Descending by default (fastest charging power in kW first).
- availability: Descending by default (most available operational connectors first).
"""

from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationItem,
    StationSortBy,
    SortOrder,
)
from app.discovery.search import (
    haversine_distance,
    validate_search_params,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import compute_station_marker


DEFAULT_SORT_ORDERS: dict[StationSortBy, SortOrder] = {
    StationSortBy.DISTANCE: SortOrder.ASC,
    StationSortBy.PRICE: SortOrder.ASC,
    StationSortBy.POWER: SortOrder.DESC,
    StationSortBy.AVAILABILITY: SortOrder.DESC,
}


def validate_sort_params(
    sort_by: str | StationSortBy,
    sort_order: str | SortOrder | None = None,
) -> tuple[StationSortBy, SortOrder]:
    """
    Validates sort_by criteria and sort_order per REQ-F2-10.
    Rejects unrecognized criteria or directions with HTTP 422 Unprocessable Entity.
    """
    # 1. Validate sort_by
    if isinstance(sort_by, StationSortBy):
        clean_sort_by = sort_by
    else:
        raw_sort_by = str(sort_by).strip().lower()
        try:
            clean_sort_by = StationSortBy(raw_sort_by)
        except ValueError:
            valid_keys = ", ".join([e.value for e in StationSortBy])
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid sort field '{sort_by}'. Supported sort fields are: {valid_keys} (REQ-F2-10).",
            )

    # 2. Validate or default sort_order
    if sort_order is None:
        clean_sort_order = DEFAULT_SORT_ORDERS[clean_sort_by]
    elif isinstance(sort_order, SortOrder):
        clean_sort_order = sort_order
    else:
        raw_order = str(sort_order).strip().lower()
        try:
            clean_sort_order = SortOrder(raw_order)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid sort order '{sort_order}'. Supported sort orders are: 'asc', 'desc'.",
            )

    return clean_sort_by, clean_sort_order


def sort_station_items(
    items: list[NearbyStationItem],
    sort_by: str | StationSortBy = StationSortBy.DISTANCE,
    sort_order: str | SortOrder | None = None,
) -> tuple[list[NearbyStationItem], str, str]:
    """
    Sorts a collection of NearbyStationItem instances by the requested criteria and order.
    Returns (sorted_items, sort_by_name, sort_order_name).
    """
    clean_sort_by, clean_sort_order = validate_sort_params(sort_by, sort_order)
    is_desc = clean_sort_order == SortOrder.DESC

    if clean_sort_by == StationSortBy.DISTANCE:
        # Distance: null/0 handled gracefully, secondary sort by id
        items.sort(
            key=lambda s: (s.distance_km, s.id),
            reverse=is_desc,
        )

    elif clean_sort_by == StationSortBy.PRICE:
        # Price: None values sent to end of list regardless of direction
        def price_sort_key(s: NearbyStationItem):
            if s.price_per_kwh is None:
                # If ascending, inf puts None at the end. If descending, -inf puts None at the end.
                return (float("inf") if not is_desc else -float("inf"), s.id)
            return (s.price_per_kwh, s.distance_km, s.id)

        items.sort(key=price_sort_key, reverse=is_desc)

    elif clean_sort_by == StationSortBy.POWER:
        # Power: max charger power in kW. If None, treated as 0 kW or end of list
        def power_sort_key(s: NearbyStationItem):
            if s.max_power_kw is None:
                return (-float("inf") if is_desc else float("inf"), s.id)
            return (s.max_power_kw, -s.distance_km if is_desc else s.distance_km, s.id)

        items.sort(key=power_sort_key, reverse=is_desc)

    elif clean_sort_by == StationSortBy.AVAILABILITY:
        # Availability: number of available connectors first, then ratio or distance
        def availability_sort_key(s: NearbyStationItem):
            ratio = (
                (s.available_connectors / s.total_connectors)
                if s.total_connectors > 0
                else 0.0
            )
            return (
                s.available_connectors,
                ratio,
                -s.distance_km if is_desc else s.distance_km,
                s.id,
            )

        items.sort(key=availability_sort_key, reverse=is_desc)

    return items, clean_sort_by.value, clean_sort_order.value


def search_and_sort_stations(
    db: Session,
    user: User | None = None,
    sort_by: str | StationSortBy = StationSortBy.DISTANCE,
    sort_order: str | SortOrder | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
    station_ids: list[int] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[int, str, str, list[NearbyStationItem]]:
    """
    Queries approved, active stations (REQ-F2-03) and sorts them per REQ-F2-10.
    Supports distance, price, power, and availability sorting with optional geospatial radius bounding.
    """
    clean_sort_by, clean_sort_order = validate_sort_params(sort_by, sort_order)

    has_location = latitude is not None and longitude is not None
    if has_location:
        validate_search_params(latitude, longitude, radius_km)

    # Visibility Gate (REQ-F2-03): Only APPROVED and is_active stations are visible for discovery
    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    ).filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )

    if station_ids:
        query = query.filter(Station.id.in_(station_ids))

    candidates: Sequence[Station] = query.all()
    station_items: list[NearbyStationItem] = []

    for station in candidates:
        dist = 0.0
        if has_location:
            dist = haversine_distance(latitude, longitude, station.latitude, station.longitude)
            if dist > radius_km:
                continue

        # Extract active operational chargers and connectors
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
        station_items.append(item)

    # Sort matching stations
    sorted_items, s_by, s_order = sort_station_items(
        items=station_items,
        sort_by=clean_sort_by,
        sort_order=clean_sort_order,
    )

    total_count = len(sorted_items)
    paginated_items = sorted_items[offset : offset + limit]

    return total_count, s_by, s_order, paginated_items

