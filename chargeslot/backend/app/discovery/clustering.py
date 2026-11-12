"""
Station Discovery Pagination and Map Marker Clustering Engine (SRS §5.2.1 / Page 18, 35 / REQ-F2-12 / CS19-038).

Paginates list results (default 20 per page) and clusters map markers when >50 stations are in view.
"""

import math
from typing import Sequence, TypeVar, Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationItem,
    StationClusterItem,
    ClusteredMapViewResponse,
    PaginatedStationListResponse,
)
from app.discovery.search import (
    haversine_distance,
    validate_search_params,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import compute_station_marker

T = TypeVar("T")

DEFAULT_PAGE_SIZE = 20
MIN_PAGE_SIZE = 1
MAX_PAGE_SIZE = 100
CLUSTERING_THRESHOLD = 50
DEFAULT_GRID_SIZE_DEG = 0.05  # ~5.5 km grid cell width at equator


def validate_pagination_params(page: int, page_size: int = DEFAULT_PAGE_SIZE) -> tuple[int, int]:
    """
    Validates page and page_size parameters per REQ-F2-12.
    Rejects page < 1 or page_size out of [1, 100] with HTTP 422.
    """
    if page < 1:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Page number {page} is invalid. Page must be >= 1 (REQ-F2-12).",
        )

    if page_size < MIN_PAGE_SIZE or page_size > MAX_PAGE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Page size {page_size} is out of valid range [{MIN_PAGE_SIZE}, {MAX_PAGE_SIZE}]. "
                f"Default is {DEFAULT_PAGE_SIZE}/page (REQ-F2-12)."
            ),
        )

    return page, page_size


def paginate_items(
    items: Sequence[T],
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
) -> tuple[list[T], int, int, bool, bool]:
    """
    Slices an in-memory list or query result per REQ-F2-12 (20/page default).
    Returns (sliced_items, total_count, total_pages, has_next, has_prev).
    """
    valid_page, valid_page_size = validate_pagination_params(page, page_size)

    total_count = len(items)
    if total_count == 0:
        return [], 0, 1, False, False

    total_pages = max(1, math.ceil(total_count / valid_page_size))
    start_idx = (valid_page - 1) * valid_page_size
    end_idx = start_idx + valid_page_size
    sliced = list(items[start_idx:end_idx])

    has_next = valid_page < total_pages
    has_prev = valid_page > 1

    return sliced, total_count, total_pages, has_next, has_prev


def cluster_stations(
    stations: list[NearbyStationItem],
    threshold: int = CLUSTERING_THRESHOLD,
    grid_size_deg: float = DEFAULT_GRID_SIZE_DEG,
) -> tuple[bool, list[StationClusterItem], list[NearbyStationItem]]:
    """
    Clusters map markers when >50 stations are in view (REQ-F2-12).
    - If total stations <= threshold (50): returns individual station markers (is_clustered=False).
    - If total stations > threshold (50): groups nearby stations into spatial clusters (is_clustered=True).
    """
    total_in_view = len(stations)

    # REQ-F2-12 condition: Only cluster when > 50 stations are in view
    if total_in_view <= threshold:
        return False, [], stations

    # Spatial grid clustering
    grid_cells: dict[tuple[int, int], list[NearbyStationItem]] = {}
    for st in stations:
        cell_x = math.floor(st.longitude / grid_size_deg)
        cell_y = math.floor(st.latitude / grid_size_deg)
        key = (cell_x, cell_y)
        if key not in grid_cells:
            grid_cells[key] = []
        grid_cells[key].append(st)

    clusters: list[StationClusterItem] = []
    unclustered_singles: list[NearbyStationItem] = []
    cluster_idx = 1

    for (cx, cy), cell_stations in grid_cells.items():
        if len(cell_stations) == 1:
            # Single station in this grid cell remains unclustered
            unclustered_singles.append(cell_stations[0])
            continue

        count = len(cell_stations)
        mean_lat = sum(s.latitude for s in cell_stations) / count
        mean_lon = sum(s.longitude for s in cell_stations) / count
        tot_conn = sum(s.total_connectors for s in cell_stations)
        avail_conn = sum(s.available_connectors for s in cell_stations)
        st_ids = [s.id for s in cell_stations]

        # Determine cluster availability color
        if tot_conn == 0:
            c_code = "grey"
        elif avail_conn == 0:
            c_code = "red"
        elif avail_conn == tot_conn:
            c_code = "green"
        else:
            c_code = "amber"

        min_lat = min(s.latitude for s in cell_stations)
        min_lon = min(s.longitude for s in cell_stations)
        max_lat = max(s.latitude for s in cell_stations)
        max_lon = max(s.longitude for s in cell_stations)

        cluster_item = StationClusterItem(
            cluster_id=f"cluster_{cluster_idx}_{cx}_{cy}",
            latitude=round(mean_lat, 6),
            longitude=round(mean_lon, 6),
            station_count=count,
            total_connectors=tot_conn,
            available_connectors=avail_conn,
            color_code=c_code,
            badge_text=f"{avail_conn}/{tot_conn} Available ({count} stations)",
            station_ids=st_ids,
            bounds=[min_lat, min_lon, max_lat, max_lon],
        )
        clusters.append(cluster_item)
        cluster_idx += 1

    return True, clusters, unclustered_singles


def get_clustered_map_view(
    db: Session,
    user: User | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float = 50.0,
    threshold: int = CLUSTERING_THRESHOLD,
    grid_size_deg: float = DEFAULT_GRID_SIZE_DEG,
) -> ClusteredMapViewResponse:
    """
    Retrieves approved active stations in the specified viewport/radius and clusters them
    if station count > threshold (50) per REQ-F2-12.
    """
    has_location = latitude is not None and longitude is not None
    if has_location:
        validate_search_params(latitude, longitude, radius_km)

    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    ).filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )

    candidates: Sequence[Station] = query.all()
    stations_in_view: list[NearbyStationItem] = []

    for station in candidates:
        dist = 0.0
        if has_location:
            dist = haversine_distance(latitude, longitude, station.latitude, station.longitude)
            if dist > radius_km:
                continue

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
        stations_in_view.append(item)

    is_clustered, clusters, individuals = cluster_stations(
        stations=stations_in_view,
        threshold=threshold,
        grid_size_deg=grid_size_deg,
    )

    return ClusteredMapViewResponse(
        is_clustered=is_clustered,
        threshold=threshold,
        total_stations=len(stations_in_view),
        clusters=clusters,
        individual_stations=individuals,
    )
