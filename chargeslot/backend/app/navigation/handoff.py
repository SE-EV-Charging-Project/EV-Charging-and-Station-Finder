"""
Navigation Hand-off Service (REQ-F2-26 / CS19-052).

Allows a driver to launch turn-by-turn navigation in external navigation apps
(Google Maps, Apple Maps, Waze, and generic geo: URI) through deep links.
"""

from datetime import datetime, timezone
import urllib.parse
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.navigation.routes import validate_coordinates
from app.schemas.navigation import NavigationAppType, NavigationHandoffResponse


def normalize_app_type(app_type: str | None) -> NavigationAppType:
    """
    Normalizes and validates target navigation application.
    Defaults to NavigationAppType.GOOGLE_MAPS.
    """
    if app_type is None or not str(app_type).strip():
        return NavigationAppType.GOOGLE_MAPS

    normalized = str(app_type).strip().lower()
    try:
        return NavigationAppType(normalized)
    except ValueError:
        valid_apps = ", ".join(f"'{a.value}'" for a in NavigationAppType)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid navigation app_type '{app_type}'. Expected one of: {valid_apps}.",
        )


def build_navigation_links(
    station_name: str,
    dest_lat: float,
    dest_lon: float,
    origin_lat: float | None = None,
    origin_lon: float | None = None,
) -> dict[str, str]:
    """
    Constructs provider-specific deep links for navigation applications.
    """
    encoded_name = urllib.parse.quote(station_name)

    # Google Maps URL
    if origin_lat is not None and origin_lon is not None:
        google_url = (
            f"https://www.google.com/maps/dir/?api=1"
            f"&origin={origin_lat:.6f},{origin_lon:.6f}"
            f"&destination={dest_lat:.6f},{dest_lon:.6f}"
            f"&travelmode=driving"
        )
    else:
        google_url = (
            f"https://www.google.com/maps/dir/?api=1"
            f"&destination={dest_lat:.6f},{dest_lon:.6f}"
            f"&travelmode=driving"
        )

    # Apple Maps URL
    if origin_lat is not None and origin_lon is not None:
        apple_url = (
            f"https://maps.apple.com/?saddr={origin_lat:.6f},{origin_lon:.6f}"
            f"&daddr={dest_lat:.6f},{dest_lon:.6f}&dirflg=d"
        )
    else:
        apple_url = f"https://maps.apple.com/?daddr={dest_lat:.6f},{dest_lon:.6f}&dirflg=d"

    # Waze URL
    waze_url = f"https://waze.com/ul?ll={dest_lat:.6f},{dest_lon:.6f}&navigate=yes"

    # Standard RFC 5870 geo: URI
    geo_uri = f"geo:{dest_lat:.6f},{dest_lon:.6f}?q={dest_lat:.6f},{dest_lon:.6f}({encoded_name})"

    return {
        "google_maps_url": google_url,
        "apple_maps_url": apple_url,
        "waze_url": waze_url,
        "geo_uri": geo_uri,
    }


def generate_navigation_handoff(
    db: Session,
    user: User,
    station_id: int,
    app_type: str | None = None,
    origin_latitude: float | None = None,
    origin_longitude: float | None = None,
) -> NavigationHandoffResponse:
    """
    Generates turn-by-turn navigation deep links to a charging station (REQ-F2-26 / CS19-052).
    """
    selected_app = normalize_app_type(app_type)

    origin_lat: float | None = None
    origin_lon: float | None = None
    if origin_latitude is not None or origin_longitude is not None:
        if origin_latitude is None or origin_longitude is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Both origin latitude and longitude must be provided together.",
            )
        origin_lat, origin_lon = validate_coordinates(origin_latitude, origin_longitude)

    station = db.query(Station).filter(Station.id == station_id).first()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found",
        )

    # RBAC Access Controls
    if user.role == UserRole.DRIVER:
        if station.status != StationStatus.APPROVED or not station.is_active:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found",
            )
    elif user.role == UserRole.OPERATOR:
        if station.operator_id != user.id:
            if station.status != StationStatus.APPROVED or not station.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Permission denied: cannot access another operator's station",
                )
    # Administrator has full access

    links = build_navigation_links(
        station_name=station.name,
        dest_lat=station.latitude,
        dest_lon=station.longitude,
        origin_lat=origin_lat,
        origin_lon=origin_lon,
    )

    if selected_app == NavigationAppType.APPLE_MAPS:
        deep_link = links["apple_maps_url"]
    elif selected_app == NavigationAppType.WAZE:
        deep_link = links["waze_url"]
    elif selected_app == NavigationAppType.GENERIC_GEO:
        deep_link = links["geo_uri"]
    else:
        deep_link = links["google_maps_url"]

    now = datetime.now(timezone.utc)
    return NavigationHandoffResponse(
        station_id=station.id,
        station_name=station.name,
        destination_address=station.address,
        destination_latitude=round(station.latitude, 6),
        destination_longitude=round(station.longitude, 6),
        origin_latitude=round(origin_lat, 6) if origin_lat is not None else None,
        origin_longitude=round(origin_lon, 6) if origin_lon is not None else None,
        app_type=selected_app.value,
        deep_link_url=deep_link,
        google_maps_url=links["google_maps_url"],
        apple_maps_url=links["apple_maps_url"],
        waze_url=links["waze_url"],
        geo_uri=links["geo_uri"],
        generated_at=now,
    )

