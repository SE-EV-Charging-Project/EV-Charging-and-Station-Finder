from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationSearchResponse,
    NearbyStationItem,
    StationAvailabilityMarkersResponse,
    StationAvailabilityMarker,
    StationFilterResponse,
)
from app.discovery.search import (
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import get_station_markers
from app.discovery.filters import apply_station_filters


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
            limit=limit,
            offset=offset,
        )

        return StationFilterResponse(
            total=total,
            applied_filters=applied,
            stations=stations,
        )

