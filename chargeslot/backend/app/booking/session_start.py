from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.booking.state import transition_booking_status
from app.core.permissions import enforce_operator_scope
from app.gateway.ingest import validate_observed_at
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector, ConnectorStatus
from app.models.charging_session_start_command import (
    ChargingSessionStartCommand,
    SessionStartCommandStatus,
)
from app.models.station import Station
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.schemas.session import (
    GatewaySessionStartResultRequest,
    PendingSessionStartCommandsResponse,
    PendingSessionStartCommand,
    SessionStartCommandResponse,
    SessionStartTransactionRequest,
    SessionStartTransactionResponse,
)


def _role_value(user: User) -> str:
    return user.role.value if isinstance(user.role, UserRole) else str(user.role)


def _command_response(
    command: ChargingSessionStartCommand,
    message: str,
    *,
    retry_available: bool = False,
    alternative_connector_ids: list[int] | None = None,
) -> SessionStartCommandResponse:
    return SessionStartCommandResponse(
        command_id=command.id,
        booking_id=command.booking_id,
        connector_id=command.connector_id,
        status=command.status.value,
        message=message,
        retry_available=retry_available,
        alternative_connector_ids=alternative_connector_ids or [],
    )


def _alternative_connector_ids(
    db: Session,
    booking: Booking,
    *,
    exclude_connector_id: int,
) -> list[int]:
    if booking.charger_id is None or booking.vehicle_id is None:
        return []
    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if vehicle is None:
        return []
    return [
        connector.id
        for connector in (
            db.query(Connector)
            .filter(
                Connector.charger_id == booking.charger_id,
                Connector.connector_type == vehicle.connector_type,
                Connector.status == ConnectorStatus.AVAILABLE,
                Connector.id != exclude_connector_id,
            )
            .order_by(Connector.id.asc())
            .all()
        )
    ]


def request_session_start(
    db: Session,
    *,
    booking_id: int,
    user: User,
    connector_id: int | None = None,
) -> SessionStartCommandResponse:
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id)
        .with_for_update()
        .first()
    )
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found.",
        )
    role = _role_value(user)
    if role not in (UserRole.DRIVER.value, UserRole.ADMIN.value):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking driver or an administrator can start a session.",
        )
    if role == UserRole.DRIVER.value and booking.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found.",
        )
    if booking.status not in (BookingStatus.CONFIRMED, BookingStatus.REASSIGNED):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a confirmed or reassigned booking can start a charging session.",
        )
    if booking.checked_in_at is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Check in before requesting remote session start.",
        )
    if booking.charger_id is None or booking.vehicle_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Booking is missing its charger or vehicle assignment.",
        )

    pending = (
        db.query(ChargingSessionStartCommand)
        .filter(
            ChargingSessionStartCommand.booking_id == booking.id,
            ChargingSessionStartCommand.status.in_(
                [
                    SessionStartCommandStatus.PENDING,
                    SessionStartCommandStatus.ACCEPTED,
                ]
            ),
        )
        .order_by(ChargingSessionStartCommand.id.desc())
        .first()
    )
    if pending is not None:
        return _command_response(
            pending,
            "A remote-start request is already in progress.",
        )

    vehicle = db.query(Vehicle).filter(Vehicle.id == booking.vehicle_id).first()
    if vehicle is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The booking vehicle is no longer available.",
        )
    connector_query = db.query(Connector).filter(
        Connector.charger_id == booking.charger_id,
        Connector.connector_type == vehicle.connector_type,
        Connector.status == ConnectorStatus.AVAILABLE,
    )
    charger = db.query(Charger).filter(Charger.id == booking.charger_id).first()
    if charger is None or not charger.is_active or charger.is_out_of_service:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The assigned charger is not available for session start.",
        )
    if connector_id is not None:
        connector_query = connector_query.filter(Connector.id == connector_id)
    elif booking.connector_id is not None:
        connector_query = connector_query.filter(
            Connector.id == booking.connector_id
        )
    connector = connector_query.order_by(Connector.id.asc()).first()
    if connector is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No available compatible connector; retry with another connector.",
        )

    command = ChargingSessionStartCommand(
        booking_id=booking.id,
        charger_id=booking.charger_id,
        connector_id=connector.id,
        requested_by_user_id=user.id,
        idempotency_key=f"session-start:{booking.id}:{uuid4()}",
        status=SessionStartCommandStatus.PENDING,
    )
    booking.connector_id = connector.id
    db.add(command)
    db.commit()
    db.refresh(command)
    return _command_response(
        command,
        "Remote-start request queued for the charging gateway.",
    )


def get_pending_session_start_commands(
    db: Session,
    *,
    gateway_id: str,
    actor_user: User | None,
    limit: int = 50,
) -> PendingSessionStartCommandsResponse:
    cleaned_gateway_id = gateway_id.strip()
    charger = (
        db.query(Charger)
        .filter(Charger.gateway_id == cleaned_gateway_id)
        .first()
    )
    if charger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charge point gateway '{cleaned_gateway_id}' not found.",
        )
    station = db.query(Station).filter(Station.id == charger.station_id).first()
    if station is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Station for charge point gateway was not found.",
        )
    if actor_user is not None:
        enforce_operator_scope(actor_user, station.operator_id)
    commands = (
        db.query(ChargingSessionStartCommand)
        .filter(
            ChargingSessionStartCommand.charger_id == charger.id,
            ChargingSessionStartCommand.status == SessionStartCommandStatus.PENDING,
        )
        .order_by(
            ChargingSessionStartCommand.requested_at.asc(),
            ChargingSessionStartCommand.id.asc(),
        )
        .limit(limit)
        .all()
    )
    return PendingSessionStartCommandsResponse(
        gateway_id=charger.gateway_id,
        commands=[
            PendingSessionStartCommand(
                command_id=command.id,
                booking_id=command.booking_id,
                connector_id=command.connector_id,
                id_tag=f"CS-{command.booking_id:08d}",
                requested_at=command.requested_at,
            )
            for command in commands
        ],
    )


def record_session_start_command_result(
    db: Session,
    *,
    command_id: int,
    payload: GatewaySessionStartResultRequest,
    actor_user: User | None,
) -> SessionStartCommandResponse:
    command = (
        db.query(ChargingSessionStartCommand)
        .filter(ChargingSessionStartCommand.id == command_id)
        .with_for_update()
        .first()
    )
    if command is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session start command not found.",
        )
    charger = db.query(Charger).filter(Charger.id == command.charger_id).first()
    booking = db.query(Booking).filter(Booking.id == command.booking_id).first()
    if charger is None or booking is None or charger.gateway_id != payload.gateway_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session start command not found for this gateway.",
        )
    if actor_user is not None and booking.station_id is not None:
        station = db.query(Station).filter(Station.id == booking.station_id).first()
        if station is not None:
            enforce_operator_scope(actor_user, station.operator_id)

    target_status = (
        SessionStartCommandStatus.ACCEPTED
        if payload.result == "Accepted"
        else SessionStartCommandStatus.REJECTED
    )
    if command.status == target_status:
        alternatives = (
            _alternative_connector_ids(
                db,
                booking,
                exclude_connector_id=command.connector_id,
            )
            if target_status == SessionStartCommandStatus.REJECTED
            else []
        )
        return _command_response(
            command,
            "Gateway command result was already recorded.",
            retry_available=target_status == SessionStartCommandStatus.REJECTED,
            alternative_connector_ids=alternatives,
        )
    if command.status != SessionStartCommandStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session start command is no longer awaiting a gateway result.",
        )

    command.status = target_status
    command.error_code = payload.error_code
    command.responded_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(command)
    alternatives = (
        _alternative_connector_ids(
            db,
            booking,
            exclude_connector_id=command.connector_id,
        )
        if target_status == SessionStartCommandStatus.REJECTED
        else []
    )
    return _command_response(
        command,
        (
            "Remote start was accepted; waiting for the charging transaction to begin."
            if target_status == SessionStartCommandStatus.ACCEPTED
            else "Remote start was rejected. Retry or select an available compatible connector."
        ),
        retry_available=target_status == SessionStartCommandStatus.REJECTED,
        alternative_connector_ids=alternatives,
    )


def record_session_start_transaction(
    db: Session,
    *,
    payload: SessionStartTransactionRequest,
    actor_user: User | None,
) -> SessionStartTransactionResponse:
    observed_at = validate_observed_at(payload.observed_at)
    command = (
        db.query(ChargingSessionStartCommand)
        .filter(ChargingSessionStartCommand.id == payload.command_id)
        .with_for_update()
        .first()
    )
    if command is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session start command not found.",
        )
    charger = db.query(Charger).filter(Charger.id == command.charger_id).first()
    booking = db.query(Booking).filter(Booking.id == command.booking_id).first()
    if charger is None or booking is None or charger.gateway_id != payload.gateway_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session start command not found for this gateway.",
        )
    if actor_user is not None:
        station = db.query(Station).filter(Station.id == charger.station_id).first()
        if station is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Station for charging gateway was not found.",
            )
        enforce_operator_scope(actor_user, station.operator_id)

    event_key = (
        payload.idempotency_key.strip()
        if payload.idempotency_key and payload.idempotency_key.strip()
        else None
    )
    existing_event = (
        db.query(ChargingSessionStartCommand)
        .filter(
            ChargingSessionStartCommand.start_event_idempotency_key == event_key
        )
        .first()
        if event_key is not None
        else None
    )
    if existing_event is not None:
        if (
            existing_event.id != payload.command_id
            or existing_event.transaction_id != payload.transaction_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session start event ID was already used with different data.",
            )
        return SessionStartTransactionResponse(
            booking_id=booking.id,
            command_id=existing_event.id,
            transaction_id=payload.transaction_id,
            status=booking.status.value,
            started_at=existing_event.started_at or observed_at,
            applied=False,
            idempotent_replay=True,
        )
    if command.status == SessionStartCommandStatus.STARTED:
        if command.transaction_id != payload.transaction_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Session start command already has a different transaction.",
            )
        return SessionStartTransactionResponse(
            booking_id=booking.id,
            command_id=command.id,
            transaction_id=payload.transaction_id,
            status=booking.status.value,
            started_at=command.started_at or observed_at,
            applied=False,
            idempotent_replay=True,
        )
    if command.status not in (
        SessionStartCommandStatus.PENDING,
        SessionStartCommandStatus.ACCEPTED,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Rejected or failed start commands cannot start a session.",
        )
    if (
        booking.status not in (BookingStatus.CONFIRMED, BookingStatus.REASSIGNED)
        or booking.checked_in_at is None
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A checked-in confirmed booking is required to start a session.",
        )

    transition_booking_status(booking, BookingStatus.ACTIVE)
    booking.connector_id = command.connector_id
    booking.session_transaction_id = payload.transaction_id
    command.status = SessionStartCommandStatus.STARTED
    command.transaction_id = payload.transaction_id
    command.start_event_idempotency_key = event_key
    command.started_at = observed_at
    command.responded_at = observed_at
    db.commit()
    db.refresh(booking)
    return SessionStartTransactionResponse(
        booking_id=booking.id,
        command_id=command.id,
        transaction_id=payload.transaction_id,
        status=booking.status.value,
        started_at=observed_at,
    )
