"""Road-distance based station reachability filtering (REQ-F3-04 / CS19-058)."""

import math

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.booking.battery import compute_usable_range, get_target_vehicle
from app.core.config import settings
from app.discovery.filters import apply_station_filters
from app.discovery.search import haversine_distance
from app.models.user import User
from app.schemas.discovery import StationFilterResponse

ROUTING_TIMEOUT_SECONDS = 5.0
MAX_DESTINATIONS_PER_REQUEST = 49


def get_road_distances_km(
    origin_latitude: float,
    origin_longitude: float,
    destinations: list[tuple[int, float, float]],
) -> dict[int, float | None]:
    """Fetch road distances from a self-hosted OSRM-compatible table service."""
    distances_by_station: dict[int, float | None] = {}
    base_url = settings.ROUTING_SERVICE_URL.rstrip("/")

    try:
        with httpx.Client(timeout=ROUTING_TIMEOUT_SECONDS) as client:
            for start in range(0, len(destinations), MAX_DESTINATIONS_PER_REQUEST):
                batch = destinations[start : start + MAX_DESTINATIONS_PER_REQUEST]
                coordinates = [(origin_longitude, origin_latitude)] + [
                    (longitude, latitude)
                    for _, latitude, longitude in batch
                ]
                coordinates_path = ";".join(
                    f"{longitude:.6f},{latitude:.6f}"
                    for longitude, latitude in coordinates
                )
                destination_indexes = ";".join(
                    str(index) for index in range(1, len(coordinates))
                )
                response = client.get(
                    f"{base_url}/table/v1/driving/{coordinates_path}",
                    params={
                        "sources": "0",
                        "destinations": destination_indexes,
                        "annotations": "distance",
                    },
                )
                if response.status_code != status.HTTP_200_OK:
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="Road routing service returned an unsuccessful response.",
                    )

                try:
                    payload = response.json()
                except ValueError as exc:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Road routing service returned invalid JSON.",
                    ) from exc

                if not isinstance(payload, dict):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Road routing service returned an invalid response.",
                    )

                if payload.get("code") == "NoTable":
                    distances_by_station.update(
                        (station_id, None) for station_id, _, _ in batch
                    )
                    continue
                if payload.get("code") != "Ok":
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Road routing service could not calculate distances.",
                    )

                matrix = payload.get("distances")
                if (
                    not isinstance(matrix, list)
                    or len(matrix) != 1
                    or not isinstance(matrix[0], list)
                    or len(matrix[0]) != len(batch)
                ):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail="Road routing service returned an invalid distance matrix.",
                    )

                for (station_id, _, _), distance_meters in zip(batch, matrix[0]):
                    if distance_meters is None:
                        distances_by_station[station_id] = None
                        continue
                    if isinstance(distance_meters, bool) or not isinstance(
                        distance_meters, (int, float)
                    ):
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Road routing service returned an invalid distance.",
                        )
                    try:
                        numeric_distance = float(distance_meters)
                    except OverflowError as exc:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Road routing service returned an invalid distance.",
                        ) from exc
                    if not math.isfinite(numeric_distance) or numeric_distance < 0:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail="Road routing service returned an invalid distance.",
                        )
                    distances_by_station[station_id] = numeric_distance / 1000.0
    except (httpx.RequestError, httpx.InvalidURL) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Road routing service is unavailable.",
        ) from exc

    return distances_by_station


def find_reachable_stations(
    db: Session,
    user: User,
    vehicle_id: int,
    latitude: float,
    longitude: float,
    limit: int = 50,
    offset: int = 0,
) -> StationFilterResponse:
    """Return compatible stations whose road distance is within the vehicle's usable range."""
    vehicle = get_target_vehicle(db=db, user=user, vehicle_id=vehicle_id)
    if vehicle.current_soc is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Enter the vehicle's current battery level before filtering reachable stations.",
        )

    usable_range_km = compute_usable_range(
        battery_kwh=vehicle.battery_kwh,
        consumption_kwh_100km=vehicle.consumption_kwh_100km,
        current_soc=vehicle.current_soc,
    )
    _, applied_filters, compatible_stations = apply_station_filters(
        db=db,
        user=user,
        vehicle_id=vehicle_id,
        limit=None,
        offset=0,
    )
    reachable_candidates = []
    for station in compatible_stations:
        straight_line_distance_km = haversine_distance(
            latitude,
            longitude,
            station.latitude,
            station.longitude,
        )
        if straight_line_distance_km <= usable_range_km:
            reachable_candidates.append((station, straight_line_distance_km))

    road_distances = get_road_distances_km(
        origin_latitude=latitude,
        origin_longitude=longitude,
        destinations=[
            (station.id, station.latitude, station.longitude)
            for station, _ in reachable_candidates
        ],
    ) if reachable_candidates else {}

    reachable_stations = []
    for station, straight_line_distance_km in reachable_candidates:
        if station.id not in road_distances:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Road routing service omitted a requested station distance.",
            )
        road_distance_km = road_distances[station.id]
        if road_distance_km is None or road_distance_km > usable_range_km:
            continue
        reachable_stations.append(
            (
                road_distance_km,
                station.model_copy(
                    update={
                        "distance_km": round(straight_line_distance_km, 2),
                        "road_distance_km": round(road_distance_km, 2),
                    }
                ),
            )
        )

    reachable_stations.sort(key=lambda result: (result[0], result[1].id))
    applied_filters.update(
        {
            "origin_latitude": latitude,
            "origin_longitude": longitude,
            "usable_range_km": usable_range_km,
            "distance_metric": "road",
        }
    )
    stations = [
        station
        for _, station in reachable_stations[offset : offset + limit]
    ]
    return StationFilterResponse(
        total=len(reachable_stations),
        applied_filters=applied_filters,
        stations=stations,
    )
