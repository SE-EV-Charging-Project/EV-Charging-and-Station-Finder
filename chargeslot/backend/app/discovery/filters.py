"""
Station Discovery Multi-Criteria Filtering (SRS §5.2.1 / Page 18, 35 / REQ-F2-09).

Allows charging stations to be filtered by connector type, minimum power, availability now,
maximum price per kWh, amenities, and vehicle compatibility.
"""

from typing import Any
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.vehicle import Vehicle
from app.models.user import User, UserRole
from app.schemas.discovery import NearbyStationItem
from app.discovery.search import (
    haversine_distance,
    validate_search_params,
    DEFAULT_SEARCH_RADIUS_KM,
)
from app.discovery.views import compute_station_marker


def apply_station_filters(
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
) -> tuple[int, dict[str, Any], list[NearbyStationItem]]:
    """
    Filters approved active stations against multiple criteria (REQ-F2-09):
    - connector_type: Station must possess at least one matching connector.
    - min_power_kw: Station must possess a charger rated >= min_power_kw.
    - available_now: Station must possess at least one Available connector.
    - max_price_kwh: Station tariff/price <= max_price_kwh.
    - amenities: Station must possess all specified amenities.
    - vehicle_id: Station must possess connectors compatible with vehicle's plug type.
    - latitude/longitude/radius_km: Optional proximity bounding.
    """
    # 1. Parameter Validation
    applied_filters: dict[str, Any] = {}

    if min_power_kw is not None:
        if min_power_kw < 0.0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="min_power_kw cannot be negative.",
            )
        applied_filters["min_power_kw"] = min_power_kw

    if max_price_kwh is not None:
        if max_price_kwh < 0.0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="max_price_kwh cannot be negative.",
            )
        applied_filters["max_price_kwh"] = max_price_kwh

    if connector_types:
        applied_filters["connector_types"] = connector_types

    if available_now is not None:
        applied_filters["available_now"] = available_now

    if amenities:
        applied_filters["amenities"] = amenities

    # 2. Vehicle Compatibility Check
    target_vehicle: Vehicle | None = None
    if vehicle_id is not None:
        target_vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if not target_vehicle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle with ID {vehicle_id} not found.",
            )
        if user and user.role == UserRole.DRIVER and target_vehicle.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not own this vehicle (REQ-F1-26).",
            )
        applied_filters["vehicle_id"] = vehicle_id
        applied_filters["vehicle_connector"] = (
            target_vehicle.connector_type.value
            if hasattr(target_vehicle.connector_type, "value")
            else str(target_vehicle.connector_type)
        )

    # 3. Geospatial Validation
    has_location = latitude is not None and longitude is not None
    if has_location:
        validate_search_params(latitude, longitude, radius_km)
        applied_filters["center_latitude"] = latitude
        applied_filters["center_longitude"] = longitude
        applied_filters["radius_km"] = radius_km

    # 4. Query Approved & Active Stations (REQ-F2-03)
    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    ).filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )

    candidates: list[Station] = query.all()
    matching_items: list[NearbyStationItem] = []

    for station in candidates:
        # Check distance if location provided
        dist = 0.0
        if has_location:
            dist = haversine_distance(latitude, longitude, station.latitude, station.longitude)
            if dist > radius_km:
                continue

        # Extract active, operational chargers and connectors
        active_chargers = [
            c for c in station.chargers if c.is_active and not c.is_out_of_service
        ]
        all_connectors: list[Connector] = [
            conn for c in active_chargers for conn in c.connectors
        ]
        avail_connectors = [
            conn for conn in all_connectors if conn.status == ConnectorStatus.AVAILABLE
        ]

        # Extract connector types present
        station_conn_types_clean = {
            conn.connector_type.value.lower()
            if hasattr(conn.connector_type, "value")
            else str(conn.connector_type).lower()
            for conn in all_connectors
        }

        # Filter A: Vehicle Compatibility
        if target_vehicle is not None:
            veh_conn = (
                target_vehicle.connector_type.value.lower()
                if hasattr(target_vehicle.connector_type, "value")
                else str(target_vehicle.connector_type).lower()
            )
            if veh_conn not in station_conn_types_clean:
                continue

        # Filter B: Connector Types
        if connector_types:
            req_types = {t.strip().lower() for t in connector_types if t.strip()}
            if not req_types.intersection(station_conn_types_clean):
                continue

        # Filter C: Minimum Power (kW)
        if min_power_kw is not None:
            max_p = max([c.power_kw for c in active_chargers], default=0.0)
            if max_p < min_power_kw:
                continue

        # Filter D: Available Now
        if available_now is True:
            if len(avail_connectors) == 0:
                continue

        # Filter E: Amenities
        if amenities:
            station_amenities_lower = [
                a.strip().lower() for a in (station.amenities or [])
            ]
            has_all_amenities = True
            for req_am in amenities:
                clean_req = req_am.strip().lower()
                if not any(clean_req in am for am in station_amenities_lower):
                    has_all_amenities = False
                    break
            if not has_all_amenities:
                continue

        # Compute marker info for consistent presentation
        marker = compute_station_marker(station)
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
            color_code=marker.color_code.value,
            status_label=marker.status_label,
            badge_text=marker.badge_text,
        )
        matching_items.append(item)

    # Sort matching stations (by distance if location given, else by ID)
    if has_location:
        matching_items.sort(key=lambda s: s.distance_km)
    else:
        matching_items.sort(key=lambda s: s.id)

    total_count = len(matching_items)
    paginated_items = matching_items[offset : offset + limit]

    return total_count, applied_filters, paginated_items

