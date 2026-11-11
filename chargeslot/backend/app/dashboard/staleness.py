from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dashboard.views import _load_authorized_station, validate_live_status_params
from app.discovery.views import _enum_to_str
from app.gateway.ingest import _ensure_utc
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.user import User
from app.schemas.dashboard import (
    StaleConnectorStatusItem,
    StaleStatusHandlingResponse,
)

STATUS_UNKNOWN = "Status unknown"
DEFAULT_STALE_THRESHOLD_SECONDS = settings.GATEWAY_STALE_STATUS_LIMIT_SECONDS
_MAX_STALE_THRESHOLD_SECONDS = 86400


def validate_stale_status_params(
    station_id: int | None = None,
    connector_id: int | None = None,
    stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
) -> None:
    """
    Validate query arguments for stale connector status handling (REQ-F2-20 / CS19-046).
    """
    validate_live_status_params(station_id=station_id, connector_id=connector_id)
    if stale_threshold_seconds < 1 or stale_threshold_seconds > _MAX_STALE_THRESHOLD_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"stale_threshold_seconds must be between 1 and {_MAX_STALE_THRESHOLD_SECONDS}."
            ),
        )


def is_connector_stale(
    last_update: datetime | None,
    *,
    now_utc: datetime | None = None,
    threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
) -> tuple[bool, int]:
    """
    Determine whether a connector has had no telemetry update for strictly more than
    threshold_seconds (default: 120 seconds per REQ-F2-20).
    Returns (is_stale, seconds_since_update).
    """
    if last_update is None:
        return True, threshold_seconds + 1

    ref_now = _ensure_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    last_utc = _ensure_utc(last_update)
    elapsed_exact = (ref_now - last_utc).total_seconds()
    elapsed_seconds = max(0, int(elapsed_exact))
    return elapsed_exact > float(threshold_seconds), elapsed_seconds


def resolve_display_status_with_staleness(
    raw_status: ConnectorStatus | str,
    last_update: datetime | None,
    *,
    is_out_of_service: bool = False,
    now_utc: datetime | None = None,
    threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
) -> tuple[str, bool, int, str]:
    """
    Resolve effective display status with REQ-F2-20 fallback:
    - Out-of-service chargers report 'Offline' (REQ-F2-05).
    - Connectors with elapsed time > threshold_seconds report 'Status unknown'
      instead of showing the cached status (REQ-F2-20).
    - Otherwise return the normalized current status.
    Returns (display_status, is_stale, seconds_since_update, status_reason).
    """
    stale, elapsed_seconds = is_connector_stale(
        last_update,
        now_utc=now_utc,
        threshold_seconds=threshold_seconds,
    )
    if is_out_of_service:
        return (
            ConnectorStatus.OFFLINE.value,
            stale,
            elapsed_seconds,
            "Charger marked out of service",
        )

    if stale:
        return (
            STATUS_UNKNOWN,
            True,
            elapsed_seconds,
            f"No update received for more than {threshold_seconds} seconds",
        )

    return (
        _enum_to_str(raw_status),
        False,
        elapsed_seconds,
        "Telemetry update within freshness window",
    )


def get_stale_connector_status_display(
    db: Session,
    user: User,
    *,
    station_id: int | None = None,
    connector_id: int | None = None,
    stale_threshold_seconds: int = DEFAULT_STALE_THRESHOLD_SECONDS,
    stale_only: bool = False,
    now_utc: datetime | None = None,
) -> StaleStatusHandlingResponse:
    """
    Evaluate staleness for each visible connector at a station (or target connector)
    and replace stale statuses with 'Status unknown' (REQ-F2-20 / CS19-046).
    """
    validate_stale_status_params(
        station_id=station_id,
        connector_id=connector_id,
        stale_threshold_seconds=stale_threshold_seconds,
    )
    station, include_inactive_chargers = _load_authorized_station(
        db,
        user,
        station_id=station_id,
        connector_id=connector_id,
    )

    ref_now = _ensure_utc(now_utc) if now_utc is not None else datetime.now(timezone.utc)
    all_items: list[StaleConnectorStatusItem] = []
    stale_count = 0
    fresh_count = 0
    unknown_count = 0
    last_status_update: datetime | None = None

    for charger in sorted(station.chargers or [], key=lambda c: c.id or 0):
        if not include_inactive_chargers and not charger.is_active:
            continue

        for conn in sorted(charger.connectors or [], key=lambda k: k.id or 0):
            is_oos = bool(charger.is_out_of_service)
            (
                effective_status,
                stale,
                seconds_since,
                reason,
            ) = resolve_display_status_with_staleness(
                conn.status,
                conn.last_update,
                is_out_of_service=is_oos,
                now_utc=ref_now,
                threshold_seconds=stale_threshold_seconds,
            )

            if stale:
                stale_count += 1
            else:
                fresh_count += 1
            if effective_status == STATUS_UNKNOWN:
                unknown_count += 1

            last_update_utc = (
                _ensure_utc(conn.last_update) if conn.last_update is not None else None
            )
            if last_update_utc is not None and (
                last_status_update is None or last_update_utc > last_status_update
            ):
                last_status_update = last_update_utc

            all_items.append(
                StaleConnectorStatusItem(
                    connector_id=conn.id,
                    charger_id=charger.id,
                    charger_name=charger.name,
                    station_id=station.id,
                    station_name=station.name,
                    gateway_id=charger.gateway_id,
                    connector_type=_enum_to_str(conn.connector_type),
                    power_kw=float(charger.power_kw),
                    current_type=_enum_to_str(charger.current_type),
                    status=effective_status,
                    is_stale=stale,
                    status_reason=reason,
                    last_update=last_update_utc,
                    seconds_since_update=seconds_since,
                    stale_threshold_seconds=stale_threshold_seconds,
                    is_active=bool(charger.is_active),
                    is_out_of_service=is_oos,
                )
            )

    displayed = all_items
    if connector_id is not None:
        displayed = [item for item in displayed if item.connector_id == connector_id]
    if stale_only:
        displayed = [item for item in displayed if item.is_stale]

    return StaleStatusHandlingResponse(
        station_id=station.id,
        station_name=station.name,
        station_status=_enum_to_str(station.status),
        is_active=bool(station.is_active),
        stale_threshold_seconds=stale_threshold_seconds,
        status_unknown_label=STATUS_UNKNOWN,
        total_connectors=len(all_items),
        fresh_connectors=fresh_count,
        stale_connectors=stale_count,
        unknown_status_connectors=unknown_count,
        last_status_update=last_status_update,
        evaluated_at=ref_now,
        connectors=displayed,
    )

