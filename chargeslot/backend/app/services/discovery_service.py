from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationSearchResponse,
    NearbyStationItem,
    StationAvailabilityMarkersResponse,
    StationAvailabilityMarker,
    StationFilterResponse,
    StationSortResponse,
    StationSortBy,
    SortOrder,
    StationTextSearchResponse,
    ClusteredMapViewResponse,
    PaginatedStationListResponse,
    StationDetailResponse,
    FavouriteStationActionResponse,
    FavouriteStationListResponse,
    StationReviewCreateResponse,
    StationReviewListResponse,
)
from app.discovery.search import (
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import get_station_markers, get_station_detail
from app.discovery.filters import apply_station_filters
from app.discovery.sorting import search_and_sort_stations
from app.discovery.text_search import search_stations_by_text
from app.discovery.clustering import (
    get_clustered_map_view,
    paginate_items,
    DEFAULT_PAGE_SIZE,
    CLUSTERING_THRESHOLD,
)
from app.discovery.favourites import (
    save_favourite_station,
    remove_favourite_station,
    list_favourite_stations,
)
from app.discovery.reviews import (
    create_station_review,
    list_station_reviews,
)


class DiscoveryService:
    """
    Service layer handling station discovery, map/list views, availability markers,
    and proximity search (REQ-F2-07, REQ-F2-08 / CS19-033, CS19-034 / HLD §Discovery).
    """

    @staticmethod
    def get_nearby_stations(
        db: Session,
        latitude: float,
        longitude: float,
        radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
        limit: int = 50,
        user: User | None = None,
    ) -> NearbyStationSearchResponse:
        """
        Retrieves nearby charging stations within radius_km, formatted for map pins and list rendering.
        """
        stations: list[NearbyStationItem] = search_nearby_stations(
            db=db,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            limit=limit,
            user=user,
        )

        return NearbyStationSearchResponse(
            center_latitude=latitude,
            center_longitude=longitude,
            radius_km=radius_km,
            total_found=len(stations),
            stations=stations,
        )

    @staticmethod
    def get_availability_markers(
        db: Session,
        station_id: int | None = None,
        station_ids: list[int] | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float | None = None,
        user: User | None = None,
    ) -> StationAvailabilityMarkersResponse:
        """
        Retrieves colour-coded availability markers with connector availability metrics
        (REQ-F2-08 / CS19-034).
        """
        markers: list[StationAvailabilityMarker] = get_station_markers(
            db=db,
            station_id=station_id,
            station_ids=station_ids,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            user=user,
        )

        return StationAvailabilityMarkersResponse(
            total=len(markers),
            markers=markers,
        )

    @staticmethod
    def filter_stations(
        db: Session,
        user: User | None = None,
        connector_types: list[str] | None = None,
        min_power_kw: float | None = None,
        available_now: bool | None = None,
        max_price_kwh: float | None = None,
        amenities: list[str] | None = None,
        vehicle_id: int | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
        sort_by: str | None = None,
        sort_order: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> StationFilterResponse:
        """
        Filters stations based on multiple criteria (REQ-F2-09 / CS19-035).
        """
        total, applied, stations = apply_station_filters(
            db=db,
            user=user,
            connector_types=connector_types,
            min_power_kw=min_power_kw,
            available_now=available_now,
            max_price_kwh=max_price_kwh,
            amenities=amenities,
            vehicle_id=vehicle_id,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

        return StationFilterResponse(
            total=total,
            applied_filters=applied,
            stations=stations,
        )

    @staticmethod
    def sort_stations(
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
    ) -> StationSortResponse:
        """
        Sorts stations by distance, price, power, or availability (REQ-F2-10 / CS19-036).
        """
        total, applied_sort_by, applied_sort_order, stations = search_and_sort_stations(
            db=db,
            user=user,
            sort_by=sort_by,
            sort_order=sort_order,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            station_ids=station_ids,
            limit=limit,
            offset=offset,
        )

        return StationSortResponse(
            total=total,
            sort_by=applied_sort_by,
            sort_order=applied_sort_order,
            stations=stations,
        )

    @staticmethod
    def text_search_stations(
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
    ) -> StationTextSearchResponse:
        """
        Searches stations by free-text matching name, address, or area (REQ-F2-11 / CS19-037).
        """
        total, clean_q, stations = search_stations_by_text(
            db=db,
            query=query,
            user=user,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset,
        )

        return StationTextSearchResponse(
            query=clean_q,
            total=total,
            stations=stations,
        )

    @staticmethod
    def get_map_view(
        db: Session,
        user: User | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = 50.0,
        threshold: int = CLUSTERING_THRESHOLD,
    ) -> ClusteredMapViewResponse:
        """
        Retrieves map view stations, clustering markers when >50 stations are in view (REQ-F2-12 / CS19-038).
        """
        return get_clustered_map_view(
            db=db,
            user=user,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            threshold=threshold,
        )

    @staticmethod
    def get_paginated_stations(
        db: Session,
        user: User | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
        latitude: float | None = None,
        longitude: float | None = None,
        radius_km: float = DEFAULT_SEARCH_RADIUS_KM,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> PaginatedStationListResponse:
        """
        Retrieves paginated station list results (20/page by default) per REQ-F2-12 / CS19-038.
        """
        # Fetch all stations matching criteria then slice per page
        total, s_by, s_order, all_stations = search_and_sort_stations(
            db=db,
            user=user,
            sort_by=sort_by or "distance",
            sort_order=sort_order,
            latitude=latitude,
            longitude=longitude,
            radius_km=radius_km,
            limit=1000,
            offset=0,
        )

        items, total_count, total_pages, has_next, has_prev = paginate_items(
            items=all_stations,
            page=page,
            page_size=page_size,
        )

        return PaginatedStationListResponse(
            total=total_count,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
            has_next=has_next,
            has_prev=has_prev,
            items=items,
        )

    @staticmethod
    def get_station_detail(
        db: Session,
        station_id: int,
        user: User,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> StationDetailResponse:
        """
        Return full station detail payload for REQ-F2-13 / SR-F2-03.
        Enforces driver approval/active visibility (BR-01, BR-11) and operator scoping (REQ-F1-12).
        """
        return get_station_detail(
            db=db,
            station_id=station_id,
            user=user,
            latitude=latitude,
            longitude=longitude,
        )

    @staticmethod
    def save_favourite_station(
        db: Session,
        user: User,
        station_id: int,
        latitude: float | None = None,
        longitude: float | None = None,
        ip_address: str | None = None,
    ) -> FavouriteStationActionResponse:
        """
        Save a charging station as a driver favourite (REQ-F2-14).
        """
        return save_favourite_station(
            db=db,
            user=user,
            station_id=station_id,
            latitude=latitude,
            longitude=longitude,
            ip_address=ip_address,
        )

    @staticmethod
    def remove_favourite_station(
        db: Session,
        user: User,
        station_id: int,
        ip_address: str | None = None,
    ) -> FavouriteStationActionResponse:
        """
        Remove a charging station from the driver's favourites (REQ-F2-14).
        """
        return remove_favourite_station(
            db=db,
            user=user,
            station_id=station_id,
            ip_address=ip_address,
        )

    @staticmethod
    def list_favourite_stations(
        db: Session,
        user: User,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> FavouriteStationListResponse:
        """
        List all approved, active favourite stations saved by the driver (REQ-F2-14).
        """
        return list_favourite_stations(
            db=db,
            user=user,
            latitude=latitude,
            longitude=longitude,
        )

    @staticmethod
    def create_station_review(
        db: Session,
        user: User,
        booking_id: int,
        rating: int,
        comment: str | None = None,
        station_id: int | None = None,
        ip_address: str | None = None,
    ) -> StationReviewCreateResponse:
        """
        Submit a 1-5 rating and optional review once per completed charging session (REQ-F2-15).
        """
        return create_station_review(
            db=db,
            user=user,
            booking_id=booking_id,
            rating=rating,
            comment=comment,
            station_id=station_id,
            ip_address=ip_address,
        )

    @staticmethod
    def list_station_reviews(
        db: Session,
        user: User,
        station_id: int,
    ) -> StationReviewListResponse:
        """
        List reviews and aggregated average rating for a station (REQ-F2-15).
        """
        return list_station_reviews(
            db=db,
            user=user,
            station_id=station_id,
        )

