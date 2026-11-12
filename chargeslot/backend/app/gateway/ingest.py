import json
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import enforce_operator_scope
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.connector_status_event import ConnectorStatusEvent
from app.models.station import Station
from app.models.user import User
from app.schemas.gateway import (
    ConnectorStatusEventItem,
    ConnectorStatusHistoryResponse,
    ConnectorStatusIngestResponse,
)
from app.services.audit_service import AuditService

# Maximum allowed clock skew for future-dated telemetry timestamps (seconds)
_MAX_FUTURE_SKEW_SECONDS = 300

# Canonical ChargeSlot + OCPP 1.6J StatusNotification mapping (REQ-F2-17)
_STATUS_MAP: dict[str, ConnectorStatus] = {
    "available": ConnectorStatus.AVAILABLE,
    "occupied": ConnectorStatus.OCCUPIED,
    "preparing": ConnectorStatus.OCCUPIED,
    "charging": ConnectorStatus.OCCUPIED,
    "suspendedevse": ConnectorStatus.OCCUPIED,
    "suspendedev": ConnectorStatus.OCCUPIED,
    "finishing": ConnectorStatus.OCCUPIED,
    "reserved": ConnectorStatus.RESERVED,
    "faulted": ConnectorStatus.FAULTED,
    "offline": ConnectorStatus.OFFLINE,
    "unavailable": ConnectorStatus.OFFLINE,
}


def _ensure_utc(dt: datetime) -> datetime:
    """Normalize naive or tz-aware datetime values into UTC-aware datetimes."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_connector_status(raw_status: str) -> ConnectorStatus:
    """
    Map ChargeSlot canonical status names or OCPP 1.6J StatusNotification states
    to ConnectorStatus. Rejects malformed/unknown values with 422 (NFR-SAFE-06).
    """
    if not raw_status or not raw_status.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Connector status must not be blank.",
        )

    cleaned = raw_status.strip().lower()
    mapped = _STATUS_MAP.get(cleaned)
    if mapped is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Unsupported connector status '{raw_status}'. Expected Available, Occupied, "
                "Reserved, Faulted, Offline, or a valid OCPP 1.6J status."
            ),
        )
    return mapped


def validate_observed_at(observed_at: datetime | None) -> datetime:
    """
    Normalize observed_at to UTC, defaulting to current UTC time when omitted and
    rejecting far-future telemetry timestamps (NFR-SAFE-06).
    """
    now_utc = datetime.now(timezone.utc)
    if observed_at is None:
        return now_utc

    obs_utc = _ensure_utc(observed_at)
    if obs_utc > now_utc + timedelta(seconds=_MAX_FUTURE_SKEW_SECONDS):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Telemetry observed_at timestamp cannot be significantly in the future.",
        )
    return obs_utc


def resolve_connector_target(
    db: Session,
    connector_id: int | None = None,
    gateway_id: str | None = None,
    connector_index: int | None = None,
) -> tuple[Connector, Charger, Station]:
    """
    Resolve target (Connector, Charger, Station) either by ChargeSlot connector_id
    or by OCPP gateway_id + 1-based port index.
    """
    cleaned_gateway_id = gateway_id.strip() if gateway_id and gateway_id.strip() else None

    if cleaned_gateway_id is None:
        if connector_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Must provide connector_id or gateway_id with connector_index.",
            )
        connector = db.query(Connector).filter(Connector.id == connector_id).first()
        if not connector:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Connector {connector_id} not found.",
            )
        charger = db.query(Charger).filter(Charger.id == connector.charger_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charger for connector {connector_id} not found.",
            )
    else:
        charger = db.query(Charger).filter(Charger.gateway_id == cleaned_gateway_id).first()
        if not charger:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Charge point gateway '{cleaned_gateway_id}' not found.",
            )

        charger_connectors = (
            db.query(Connector)
            .filter(Connector.charger_id == charger.id)
            .order_by(Connector.id.asc())
            .all()
        )
        if not charger_connectors:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No connectors registered for gateway '{cleaned_gateway_id}'.",
            )

        if connector_index is not None:
            if connector_index < 1 or connector_index > len(charger_connectors):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Connector index {connector_index} not found on gateway '{cleaned_gateway_id}'.",
                )
            connector = charger_connectors[connector_index - 1]
            if connector_id is not None and connector.id != connector_id:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="connector_id does not match resolved connector_index on gateway.",
                )
        elif connector_id is not None:
            direct_match = next((c for c in charger_connectors if c.id == connector_id), None)
            if direct_match is not None:
                connector = direct_match
            elif 1 <= connector_id <= len(charger_connectors):
                connector = charger_connectors[connector_id - 1]
            else:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Connector {connector_id} not found on gateway '{cleaned_gateway_id}'.",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Must provide connector_index or connector_id when gateway_id is specified.",
            )

    station = db.query(Station).filter(Station.id == charger.station_id).first()
    if not station:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Station for charger {charger.id} not found.",
        )

    return connector, charger, station


def ingest_status(
    db: Session,
    connector_id: int | None,
    state: str,
    observed_at: datetime | None = None,
    *,
    gateway_id: str | None = None,
    connector_index: int | None = None,
    error_code: str | None = None,
    idempotency_key: str | None = None,
    actor_user: User | None = None,
    client_ip: str | None = None,
) -> ConnectorStatusIngestResponse:
    """
    Ingest a connector status telemetry update from the charge point gateway
    (REQ-F2-17 / CS19-043) with status validation, idempotency protection,
    out-of-order stale rejection, and audit logging.
    """
    mapped_status = normalize_connector_status(state)
    obs_utc = validate_observed_at(observed_at)
    cleaned_raw_status = state.strip()
    cleaned_idempotency = (
        idempotency_key.strip() if idempotency_key and idempotency_key.strip() else None
    )
    cleaned_error_code = error_code.strip() if error_code and error_code.strip() else None

    if cleaned_idempotency is not None:
        existing_event = (
            db.query(ConnectorStatusEvent)
            .filter(ConnectorStatusEvent.idempotency_key == cleaned_idempotency)
            .first()
        )
        if existing_event is not None:
            existing_connector, existing_charger, existing_station = resolve_connector_target(
                db, connector_id=existing_event.connector_id
            )
            if actor_user is not None:
                enforce_operator_scope(actor_user, existing_station.operator_id)
            return ConnectorStatusIngestResponse(
                message="Duplicate gateway status message ignored (idempotent replay).",
                connector_id=existing_connector.id,
                charger_id=existing_charger.id,
                station_id=existing_station.id,
                gateway_id=existing_charger.gateway_id,
                previous_status=(
                    existing_event.previous_status.value
                    if existing_event.previous_status
                    else None
                ),
                status=existing_connector.status.value,
                raw_status=existing_event.raw_status,
                observed_at=_ensure_utc(existing_event.observed_at),
                last_update=_ensure_utc(existing_connector.last_update),
                applied=False,
                idempotent_replay=True,
                event_id=existing_event.id,
            )

    connector, charger, station = resolve_connector_target(
        db,
        connector_id=connector_id,
        gateway_id=gateway_id,
        connector_index=connector_index,
    )

    if actor_user is not None:
        enforce_operator_scope(actor_user, station.operator_id)

    latest_event = (
        db.query(ConnectorStatusEvent)
        .filter(ConnectorStatusEvent.connector_id == connector.id)
        .order_by(ConnectorStatusEvent.observed_at.desc(), ConnectorStatusEvent.id.desc())
        .first()
    )
    if latest_event is not None and obs_utc < _ensure_utc(latest_event.observed_at):
        return ConnectorStatusIngestResponse(
            message="Stale status update ignored; newer observation already recorded.",
            connector_id=connector.id,
            charger_id=charger.id,
            station_id=station.id,
            gateway_id=charger.gateway_id,
            previous_status=connector.status.value,
            status=connector.status.value,
            raw_status=cleaned_raw_status,
            observed_at=obs_utc,
            last_update=_ensure_utc(connector.last_update),
            applied=False,
            idempotent_replay=False,
            event_id=None,
        )

    previous_status = connector.status
    connector.status = mapped_status
    connector.last_update = obs_utc

    event = ConnectorStatusEvent(
        connector_id=connector.id,
        charger_id=charger.id,
        gateway_id=charger.gateway_id,
        previous_status=previous_status,
        new_status=mapped_status,
        raw_status=cleaned_raw_status,
        error_code=cleaned_error_code,
        idempotency_key=cleaned_idempotency,
        observed_at=obs_utc,
    )
    db.add(event)
    db.flush()

    AuditService.log_action(
        db=db,
        user_id=actor_user.id if actor_user else None,
        action="GATEWAY_STATUS_INGESTED",
        resource="connector",
        details=json.dumps({
            "connector_id": connector.id,
            "charger_id": charger.id,
            "station_id": station.id,
            "gateway_id": charger.gateway_id,
            "previous_status": previous_status.value if previous_status else None,
            "new_status": mapped_status.value,
            "raw_status": cleaned_raw_status,
            "observed_at": obs_utc.isoformat(),
            "event_id": event.id,
        }),
        ip_address=client_ip,
        commit=False,
    )

    db.commit()
    db.refresh(connector)
    db.refresh(event)

    from app.dashboard.realtime import publish_connector_status_change

    publish_connector_status_change(
        event_id=event.id,
        station=station,
        charger=charger,
        connector=connector,
        previous_status=previous_status,
        new_status=mapped_status,
        raw_status=event.raw_status,
        observed_at=obs_utc,
        error_code=cleaned_error_code,
    )

    return ConnectorStatusIngestResponse(
        message="Connector status ingested successfully.",
        connector_id=connector.id,
        charger_id=charger.id,
        station_id=station.id,
        gateway_id=charger.gateway_id,
        previous_status=previous_status.value if previous_status else None,
        status=connector.status.value,
        raw_status=event.raw_status,
        observed_at=_ensure_utc(event.observed_at),
        last_update=_ensure_utc(connector.last_update),
        applied=True,
        idempotent_replay=False,
        event_id=event.id,
    )


def get_connector_status_history(
    db: Session,
    connector_id: int,
    *,
    limit: int = 50,
    actor_user: User | None = None,
) -> ConnectorStatusHistoryResponse:
    """
    Retrieve chronological telemetry status history for a connector (REQ-F2-17).
    """
    connector, _, station = resolve_connector_target(db, connector_id=connector_id)
    if actor_user is not None:
        enforce_operator_scope(actor_user, station.operator_id)

    base_query = db.query(ConnectorStatusEvent).filter(
        ConnectorStatusEvent.connector_id == connector.id
    )
    total_events = base_query.count()
    events = (
        base_query.order_by(
            ConnectorStatusEvent.observed_at.desc(), ConnectorStatusEvent.id.desc()
        )
        .limit(limit)
        .all()
    )

    items = [
        ConnectorStatusEventItem(
            id=ev.id,
            connector_id=ev.connector_id,
            charger_id=ev.charger_id,
            gateway_id=ev.gateway_id,
            previous_status=ev.previous_status.value if ev.previous_status else None,
            new_status=ev.new_status.value,
            raw_status=ev.raw_status,
            error_code=ev.error_code,
            idempotency_key=ev.idempotency_key,
            observed_at=_ensure_utc(ev.observed_at),
            ingested_at=_ensure_utc(ev.ingested_at),
        )
        for ev in events
    ]

    return ConnectorStatusHistoryResponse(
        connector_id=connector.id,
        current_status=connector.status.value,
        last_update=_ensure_utc(connector.last_update),
        total_events=total_events,
        events=items,
    )
