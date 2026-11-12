"""
Favourite Stations Module
Requirement: REQ-F2-14 (Favourite stations)
SRS Architecture Reference: HLD §Discovery, SDD §Discovery
Code File Reference: discovery/favourites.py (SRS Page 35)
Story ID: CS19-040
Test Case ID: TC-F2-14, STC-F2-14
"""

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.discovery.search import haversine_distance, validate_search_params
from app.discovery.views import compute_station_marker, compute_station_rating_summary
from app.models.charger import Charger
from app.models.favourite import FavouriteStation
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.discovery import (
    FavouriteStationActionResponse,
    FavouriteStationItem,
    FavouriteStationListResponse,
)
from app.services.audit_service import AuditService
from app.stations.moderation import StationModerationService


def _ensure_driver_access(user: User) -> None:
    """Restrict favourite-station operations to authenticated drivers (and admins)."""
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only drivers can manage favourite stations (REQ-F2-14).",
        )


def validate_favourite_params(
    station_id: int | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """
    Validate favourite-station parameters (REQ-F2-14).
    Rejects non-positive station IDs and unpaired or out-of-range coordinates.
    """
    if station_id is not None and station_id <= 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="station_id must be a positive integer.",
        )
    if (latitude is None) != (longitude is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Both latitude and longitude must be provided together.",
        )
    if latitude is not None and longitude is not None:
        validate_search_params(latitude, longitude, 1.0)


def _load_station_for_favourite(db: Session, station_id: int) -> Station | None:
    return (
        db.query(Station)
        .options(
            joinedload(Station.chargers).joinedload(Charger.connectors),
            joinedload(Station.reviews),
        )
        .filter(Station.id == station_id)
        .first()
    )


def build_favourite_station_item(
    fav: FavouriteStation,
    latitude: float | None = None,
    longitude: float | None = None,
) -> FavouriteStationItem:
    """Build a FavouriteStationItem summary DTO from a FavouriteStation ORM record."""
    station = fav.station
    distance_km = (
        round(haversine_distance(latitude, longitude, station.latitude, station.longitude), 2)
        if latitude is not None and longitude is not None
        else None
    )
    avg_rating, total_reviews = compute_station_rating_summary(station)
    marker = compute_station_marker(station)
    status_str = station.status.value if hasattr(station.status, "value") else str(station.status)

    return FavouriteStationItem(
        station_id=station.id,
        name=station.name,
        address=station.address,
        latitude=station.latitude,
        longitude=station.longitude,
        distance_km=distance_km,
        operating_hours=station.operating_hours,
        amenities=list(station.amenities) if isinstance(station.amenities, list) else [],
        price_per_kwh=station.price_per_kwh,
        average_rating=avg_rating,
        total_reviews=total_reviews,
        status=status_str,
        is_active=bool(station.is_active),
        availability_marker=marker,
        favourited_at=fav.created_at,
    )


def save_favourite_station(
    db: Session,
    user: User,
    station_id: int,
    latitude: float | None = None,
    longitude: float | None = None,
    ip_address: str | None = None,
) -> FavouriteStationActionResponse:
    """
    Save an approved, active charging station to the driver's favourites (REQ-F2-14).
    Idempotent if the station is already favourited by the driver.
    """
    _ensure_driver_access(user)
    validate_favourite_params(station_id=station_id, latitude=latitude, longitude=longitude)

    station = _load_station_for_favourite(db, station_id)
    if not station or not StationModerationService.is_station_visible_to_drivers(station):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found.",
        )

    existing = (
        db.query(FavouriteStation)
        .filter(
            FavouriteStation.user_id == user.id,
            FavouriteStation.station_id == station_id,
        )
        .first()
    )
    if existing:
        existing.station = station
        return FavouriteStationActionResponse(
            message="Station is already saved in favourites.",
            station_id=station_id,
            is_favourite=True,
            favourite=build_favourite_station_item(existing, latitude=latitude, longitude=longitude),
        )

    fav = FavouriteStation(user_id=user.id, station_id=station_id)
    db.add(fav)
    db.flush()

    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="FAVOURITE_STATION_ADDED",
        resource=f"station:{station_id}",
        details=f"Driver saved station {station.name} (ID {station_id}) as favourite",
        ip_address=ip_address,
        commit=False,
    )
    db.commit()
    db.refresh(fav)
    fav.station = station

    return FavouriteStationActionResponse(
        message="Station added to favourites.",
        station_id=station_id,
        is_favourite=True,
        favourite=build_favourite_station_item(fav, latitude=latitude, longitude=longitude),
    )


def remove_favourite_station(
    db: Session,
    user: User,
    station_id: int,
    ip_address: str | None = None,
) -> FavouriteStationActionResponse:
    """
    Remove a saved station from the driver's favourites (REQ-F2-14).
    Only the owning driver's saved record can be removed.
    """
    _ensure_driver_access(user)
    validate_favourite_params(station_id=station_id)

    fav = (
        db.query(FavouriteStation)
        .filter(
            FavouriteStation.user_id == user.id,
            FavouriteStation.station_id == station_id,
        )
        .first()
    )
    if not fav:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station {station_id} is not in your favourite stations.",
        )

    db.delete(fav)
    AuditService.log_action(
        db=db,
        user_id=user.id,
        action="FAVOURITE_STATION_REMOVED",
        resource=f"station:{station_id}",
        details=f"Driver removed station ID {station_id} from favourites",
        ip_address=ip_address,
        commit=False,
    )
    db.commit()

    return FavouriteStationActionResponse(
        message="Station removed from favourites.",
        station_id=station_id,
        is_favourite=False,
        favourite=None,
    )


def list_favourite_stations(
    db: Session,
    user: User,
    latitude: float | None = None,
    longitude: float | None = None,
) -> FavouriteStationListResponse:
    """
    List all approved, active favourite stations saved by the authenticated driver (REQ-F2-14).
    """
    _ensure_driver_access(user)
    validate_favourite_params(latitude=latitude, longitude=longitude)

    favourites = (
        db.query(FavouriteStation)
        .options(
            joinedload(FavouriteStation.station)
            .joinedload(Station.chargers)
            .joinedload(Charger.connectors),
            joinedload(FavouriteStation.station).joinedload(Station.reviews),
        )
        .filter(FavouriteStation.user_id == user.id)
        .order_by(FavouriteStation.created_at.desc(), FavouriteStation.id.desc())
        .all()
    )

    items = [
        build_favourite_station_item(fav, latitude=latitude, longitude=longitude)
        for fav in favourites
        if fav.station and StationModerationService.is_station_visible_to_drivers(fav.station)
    ]

    return FavouriteStationListResponse(
        total=len(items),
        stations=items,
    )

