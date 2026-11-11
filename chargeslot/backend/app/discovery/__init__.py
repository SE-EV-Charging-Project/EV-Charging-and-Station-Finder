from app.discovery.search import (
    haversine_distance,
    validate_search_params,
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
    MIN_SEARCH_RADIUS_KM,
    MAX_SEARCH_RADIUS_KM,
)
from app.discovery.views import (
    compute_station_marker,
    get_station_markers,
    validate_station_detail_params,
    compute_station_rating_summary,
    build_station_detail,
    get_station_detail,
    HEX_GREEN,
    HEX_AMBER,
    HEX_RED,
    HEX_GREY,
)
from app.discovery.filters import apply_station_filters
from app.discovery.sorting import (
    sort_station_items,
    validate_sort_params,
    search_and_sort_stations,
    DEFAULT_SORT_ORDERS,
)
from app.discovery.text_search import (
    search_stations_by_text,
    validate_text_search_query,
)
from app.discovery.clustering import (
    paginate_items,
    validate_pagination_params,
    cluster_stations,
    get_clustered_map_view,
    DEFAULT_PAGE_SIZE,
    CLUSTERING_THRESHOLD,
)

__all__ = [
    "haversine_distance",
    "validate_search_params",
    "search_nearby_stations",
    "DEFAULT_SEARCH_RADIUS_KM",
    "MIN_SEARCH_RADIUS_KM",
    "MAX_SEARCH_RADIUS_KM",
    "compute_station_marker",
    "get_station_markers",
    "validate_station_detail_params",
    "compute_station_rating_summary",
    "build_station_detail",
    "get_station_detail",
    "HEX_GREEN",
    "HEX_AMBER",
    "HEX_RED",
    "HEX_GREY",
    "apply_station_filters",
    "sort_station_items",
    "validate_sort_params",
    "search_and_sort_stations",
    "DEFAULT_SORT_ORDERS",
    "search_stations_by_text",
    "validate_text_search_query",
    "paginate_items",
    "validate_pagination_params",
    "cluster_stations",
    "get_clustered_map_view",
    "DEFAULT_PAGE_SIZE",
    "CLUSTERING_THRESHOLD",
]

