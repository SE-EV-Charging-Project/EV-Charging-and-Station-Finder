from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.discovery import (
    NearbyStationSearchResponse,
    NearbyStationItem,
    StationAvailabilityMarkersResponse,
    StationAvailabilityMarker,
)
from app.discovery.search import (
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import get_station_markers


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

