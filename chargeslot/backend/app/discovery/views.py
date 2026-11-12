"""
Station Availability Markers and Map View Generation (SRS §5.2.1, §5.2.2 / Page 18, 35 / REQ-F2-08).

Colour-codes each station marker by availability and shows the number of available
connectors out of the total, using a text label as well as colour for accessibility.
"""

from datetime import datetime
from typing import Sequence
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.core.permissions import enforce_operator_scope
from app.models.station import Station, StationStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User, UserRole
from app.schemas.discovery import (
    MarkerColor,
    StationAvailabilityMarker,
    StationDetailChargerItem,
    StationDetailConnectorItem,
    StationDetailResponse,
    StationOperatorSummary,
)
from app.discovery.search import haversine_distance, validate_search_params
from app.stations.moderation import StationModerationService


HEX_GREEN = "#4CAF50"
HEX_AMBER = "#FF9800"
HEX_RED = "#F44336"
HEX_GREY = "#9E9E9E"


def compute_station_marker(station: Station) -> StationAvailabilityMarker:
    """
    Computes the availability marker for a station per REQ-F2-08:
    - GREEN (#4CAF50): All connectors available.
    - AMBER (#FF9800): Partially available (some connectors free).
    - RED (#F44336): Fully occupied or reserved (0 available, but working).
    - GREY (#9E9E9E): Offline, faulted, inactive, or no operational connectors.
    Always includes accessible text label and badge text with available/total count.
    """
    # Only active, operational chargers are counted
    active_chargers = [
        c for c in station.chargers if c.is_active and not c.is_out_of_service
    ]
    operational_connectors: list[Connector] = [
        conn for c in active_chargers for conn in c.connectors
    ]

    total = len(operational_connectors)
    available = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.AVAILABLE
    )
    occupied = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.OCCUPIED
    )
    reserved = sum(
        1 for conn in operational_connectors if conn.status == ConnectorStatus.RESERVED
    )
    offline = sum(
        1
        for conn in operational_connectors
        if conn.status in (ConnectorStatus.FAULTED, ConnectorStatus.OFFLINE)
    )

    # Determine colour code, hex, and accessibility label
    if not station.is_active or total == 0:
        color_code = MarkerColor.GREY
        hex_color = HEX_GREY
        status_label = "Offline"
        badge_text = f"0/{total} Offline"
        is_operational = False
    elif available == total:
        color_code = MarkerColor.GREEN
        hex_color = HEX_GREEN
        status_label = "Available"
        badge_text = f"{available}/{total} Available"
        is_operational = True
    elif available > 0:
        color_code = MarkerColor.AMBER
        hex_color = HEX_AMBER
        status_label = "Partially Available"
        badge_text = f"{available}/{total} Available"
        is_operational = True
    elif occupied > 0 or reserved > 0:
        color_code = MarkerColor.RED
        hex_color = HEX_RED
        status_label = "Occupied"
        badge_text = f"0/{total} Occupied"
        is_operational = True
    else:
        color_code = MarkerColor.GREY
        hex_color = HEX_GREY
        status_label = "Offline"
        badge_text = f"0/{total} Offline"
        is_operational = False

    return StationAvailabilityMarker(
        station_id=station.id if station.id is not None else 0,
        name=station.name or "",
        latitude=station.latitude or 0.0,
        longitude=station.longitude or 0.0,
        total_connectors=total,
        available_connectors=available,
        occupied_connectors=occupied,
        reserved_connectors=reserved,
        offline_connectors=offline,
        color_code=color_code,
        hex_color=hex_color,
        status_label=status_label,
        badge_text=badge_text,
        is_operational=is_operational,
    )


def get_station_markers(
    db: Session,
    station_id: int | None = None,
    station_ids: list[int] | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    radius_km: float | None = None,
    user: User | None = None,
) -> list[StationAvailabilityMarker]:
    """
    Queries stations and generates availability markers with driver visibility gating
    (REQ-F2-03, REQ-F2-08).
    """
    query = db.query(Station).options(
        joinedload(Station.chargers).joinedload(Charger.connectors)
    )

    # Drivers only see approved and active stations (REQ-F2-03)
    query = query.filter(
        Station.status == StationStatus.APPROVED,
        Station.is_active.is_(True),
    )

    if station_id is not None:
        station = query.filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found or not active.",
            )
        return [compute_station_marker(station)]

    if station_ids:
        query = query.filter(Station.id.in_(station_ids))

    if latitude is not None and longitude is not None:
        rad = radius_km if radius_km is not None else 10.0
        validate_search_params(latitude, longitude, rad)
        stations = query.all()
        markers = []
        for s in stations:
            dist = haversine_distance(latitude, longitude, s.latitude, s.longitude)
            if dist <= rad:
                markers.append(compute_station_marker(s))
        return markers

    stations = query.all()
    return [compute_station_marker(s) for s in stations]


def _enum_to_str(value) -> str:
    return value.value if hasattr(value, "value") else str(value)


def validate_station_detail_params(
    station_id: int,
    latitude: float | None = None,
    longitude: float | None = None,
) -> None:
    """
    Validate station detail query parameters (REQ-F2-13).
    Requires a positive station_id and paired coordinate bounds when provided.
    """
    if station_id <= 0:
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


def compute_station_rating_summary(station: Station) -> tuple[float | None, int]:
    """
    Compute average rating [1..5] and total review count when reviews exist on the station
    (REQ-F2-13 / SR-F2-03). Returns (None, 0) when no reviews are recorded.
    """
    reviews = getattr(station, "reviews", None)
    if not reviews:
        return None, 0

    ratings: list[float] = []
    for review in reviews:
        raw = getattr(review, "rating", review)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        score = float(raw)
        if 1.0 <= score <= 5.0:
            ratings.append(score)

    if not ratings:
        return None, 0
    return round(sum(ratings) / len(ratings), 2), len(ratings)


def _build_connector_item(
    charger: Charger,
    connector: Connector,
) -> tuple[StationDetailConnectorItem, bool]:
    """Build a connector detail item and indicate whether it is currently available."""
    is_oos = bool(getattr(charger, "is_out_of_service", False))
    effective_status = (
        ConnectorStatus.OFFLINE.value if is_oos else _enum_to_str(connector.status)
    )
    item = StationDetailConnectorItem(
        id=connector.id,
        charger_id=charger.id,
        charger_name=charger.name,
        connector_type=_enum_to_str(connector.connector_type),
        power_kw=float(charger.power_kw),
        current_type=_enum_to_str(charger.current_type),
        status=effective_status,
        last_update=getattr(connector, "last_update", None),
        is_out_of_service=is_oos,
        out_of_service_reason=getattr(charger, "out_of_service_reason", None),
        expected_return_time=getattr(charger, "expected_return_time", None),
    )
    is_available = (not is_oos) and (effective_status == ConnectorStatus.AVAILABLE.value)
    return item, is_available


def build_station_detail(
    station: Station,
    include_inactive_chargers: bool = False,
    latitude: float | None = None,
    longitude: float | None = None,
) -> StationDetailResponse:
    """
    Assemble the complete station detail DTO from a Station ORM instance (REQ-F2-13 / SR-F2-03).
    """
    operator_user = getattr(station, "operator", None)
    operator_summary = StationOperatorSummary(
        id=station.operator_id,
        name=operator_user.name if operator_user else f"Operator #{station.operator_id}",
        organization=operator_user.operator_organization if operator_user else None,
        contact_phone=station.contact_phone or (operator_user.phone if operator_user else None),
        contact_email=station.contact_email or (operator_user.email if operator_user else None),
    )

    charger_items: list[StationDetailChargerItem] = []
    flat_connectors: list[StationDetailConnectorItem] = []
    available_connectors = 0
    latest_update: datetime | None = None

    sorted_chargers = sorted(
        station.chargers or [],
        key=lambda c: getattr(c, "id", 0) or 0,
    )
    for charger in sorted_chargers:
        if not include_inactive_chargers and not getattr(charger, "is_active", True):
            continue

        charger_connectors: list[StationDetailConnectorItem] = []
        sorted_connectors = sorted(
            charger.connectors or [],
            key=lambda conn: getattr(conn, "id", 0) or 0,
        )
        for connector in sorted_connectors:
            conn_item, is_available = _build_connector_item(charger, connector)
            charger_connectors.append(conn_item)
            flat_connectors.append(conn_item)
            if is_available:
                available_connectors += 1
            if conn_item.last_update is not None and (
                latest_update is None or conn_item.last_update > latest_update
            ):
                latest_update = conn_item.last_update

        charger_items.append(
            StationDetailChargerItem(
                id=charger.id,
                name=charger.name,
                power_kw=float(charger.power_kw),
                current_type=_enum_to_str(charger.current_type),
                is_active=bool(charger.is_active),
                is_out_of_service=bool(getattr(charger, "is_out_of_service", False)),
                out_of_service_reason=getattr(charger, "out_of_service_reason", None),
                expected_return_time=getattr(charger, "expected_return_time", None),
                connectors=charger_connectors,
            )
        )

    distance_km = (
        round(haversine_distance(latitude, longitude, station.latitude, station.longitude), 2)
        if latitude is not None and longitude is not None
        else None
    )
    avg_rating, total_reviews = compute_station_rating_summary(station)
    marker = compute_station_marker(station)

    return StationDetailResponse(
        id=station.id,
        name=station.name,
        address=station.address,
        latitude=station.latitude,
        longitude=station.longitude,
        distance_km=distance_km,
        operator=operator_summary,
        amenities=list(station.amenities) if isinstance(station.amenities, list) else [],
        operating_hours=station.operating_hours,
        contact_phone=station.contact_phone,
        contact_email=station.contact_email,
        price_per_kwh=station.price_per_kwh,
        average_rating=avg_rating,
        total_reviews=total_reviews,
        status=_enum_to_str(station.status),
        is_active=bool(station.is_active),
        availability_marker=marker,
        total_connectors=len(flat_connectors),
        available_connectors=available_connectors,
        connectors=flat_connectors,
        chargers=charger_items,
        last_status_update=latest_update,
        created_at=getattr(station, "created_at", None),
        updated_at=getattr(station, "updated_at", None),
    )


def get_station_detail(
    db: Session,
    station_id: int,
    user: User,
    latitude: float | None = None,
    longitude: float | None = None,
) -> StationDetailResponse:
    """
    Fetch and authorize full station detail for REQ-F2-13 / SR-F2-03.
    - Drivers only see approved, active stations (404 otherwise, BR-01) and active chargers (BR-11).
    - Operators are scoped to their own stations (403 otherwise, REQ-F1-12).
    - Admins may inspect any station.
    """
    validate_station_detail_params(station_id, latitude, longitude)

    station = (
        db.query(Station)
        .options(
            joinedload(Station.operator),
            joinedload(Station.chargers).joinedload(Charger.connectors),
            joinedload(Station.reviews),
        )
        .filter(Station.id == station_id)
        .first()
    )
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station with ID {station_id} not found.",
        )

    if user.role == UserRole.DRIVER:
        if not StationModerationService.is_station_visible_to_drivers(station):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )
        include_inactive_chargers = False
    else:
        enforce_operator_scope(user, station.operator_id)
        include_inactive_chargers = True

    return build_station_detail(
        station=station,
        include_inactive_chargers=include_inactive_chargers,
        latitude=latitude,
        longitude=longitude,
    )
