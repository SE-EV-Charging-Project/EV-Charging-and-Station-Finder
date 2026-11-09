from sqlalchemy.orm import Session
from app.models.user import User
from app.schemas.discovery import NearbyStationSearchResponse, NearbyStationItem
from app.discovery.search import (
    search_nearby_stations,
    DEFAULT_SEARCH_RADIUS_KM,
)


class DiscoveryService:
    """
    Service layer handling station discovery, map/list views, and proximity search
    (REQ-F2-07 / CS19-033 / HLD §Discovery).
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

