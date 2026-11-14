from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import enforce_operator_scope
from app.gateway.ingest import _ensure_utc, validate_observed_at
from app.models.booking import Booking, BookingStatus
from app.models.charger import Charger, Connector
from app.models.charging_session_command import (
    ChargingSessionCommand,
    SessionStopCommandStatus,
    SessionStopCommandTrigger,
)
from app.models.charging_session_reading import ChargingSessionReading
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.session import (
    PendingSessionStopCommand,
    PendingSessionStopCommandsResponse,
    SessionStopCommandResponse,
    SessionStopTransactionRequest,
    SessionStopTransactionResponse,
)


def _role_value(user: User) -> str:
    return user.role.value if isinstance(user.role, UserRole) else str(user.role)


def _command_response(
    command: ChargingSessionCommand,
    *,
    message: str,
    already_requested: bool = False,
) -> SessionStopCommandResponse:
    return SessionStopCommandResponse(
        command_id=command.id,
        booking_id=command.booking_id,
        connector_id=command.connector_id,
        transaction_id=command.transaction_id,
        trigger=command.trigger.value,
        status=command.status.value,
        requested_at=_ensure_utc(command.requested_at),
        message=message,
        already_requested=already_requested,
    )


def request_session_stop(
    db: Session,
    *,
    booking_id: int,
    user: User,
) -> SessionStopCommandResponse:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found."
        )

    role = _role_value(user)
    if role not in {UserRole.DRIVER.value, UserRole.ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking driver or an administrator can stop this session.",
        )
    if role == UserRole.DRIVER.value and booking.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found."
        )
    if booking.status != BookingStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an active charging session can be stopped.",
        )

    reading = (
        db.query(ChargingSessionReading)
        .filter(
            ChargingSessionReading.booking_id == booking.id,
            ChargingSessionReading.transaction_id.isnot(None),
        )
        .order_by(
            ChargingSessionReading.observed_at.desc(),
            ChargingSessionReading.id.desc(),
        )
        .first()
    )
    if reading is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The active OCPP transaction ID is not available yet.",
        )

    connector_id = booking.connector_id or reading.connector_id
    if connector_id != reading.connector_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The active OCPP transaction does not match the booking connector.",
        )

    existing = (
        db.query(ChargingSessionCommand)
        .filter(
            ChargingSessionCommand.booking_id == booking.id,
            ChargingSessionCommand.transaction_id == reading.transaction_id,
            ChargingSessionCommand.status.in_(
                [
                    SessionStopCommandStatus.PENDING,
                    SessionStopCommandStatus.ACCEPTED,
                ]
            ),
        )
        .order_by(ChargingSessionCommand.id.desc())
        .first()
    )
    if existing is not None:
        return _command_response(
            existing,
            message="A stop request is already queued or accepted for this session.",
            already_requested=True,
        )

    command = ChargingSessionCommand(
        booking_id=booking.id,
        charger_id=reading.charger_id,
        connector_id=connector_id,
        transaction_id=reading.transaction_id,
        trigger=SessionStopCommandTrigger.DRIVER,
        status=SessionStopCommandStatus.PENDING,
        requested_by_user_id=user.id,
    )
    db.add(command)
    db.commit()
    db.refresh(command)
    return _command_response(command, message="Session stop request queued.")


def _resolve_gateway(
    db: Session, gateway_id: str, actor_user: User | None
) -> tuple[Charger, Station]:
    cleaned_gateway_id = gateway_id.strip()
    charger = db.query(Charger).filter(Charger.gateway_id == cleaned_gateway_id).first()
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
    return charger, station


def get_pending_session_stop_commands(
    db: Session,
    *,
    gateway_id: str,
    actor_user: User | None,
    limit: int,
) -> PendingSessionStopCommandsResponse:
    charger, _ = _resolve_gateway(db, gateway_id, actor_user)
    commands = (
        db.query(ChargingSessionCommand)
        .filter(
            ChargingSessionCommand.charger_id == charger.id,
            ChargingSessionCommand.status == SessionStopCommandStatus.PENDING,
        )
        .order_by(ChargingSessionCommand.requested_at.asc(), ChargingSessionCommand.id.asc())
        .limit(limit)
        .all()
    )
    return PendingSessionStopCommandsResponse(
        gateway_id=charger.gateway_id,
        commands=[
            PendingSessionStopCommand(
                command_id=command.id,
                booking_id=command.booking_id,
                connector_id=command.connector_id,
                transaction_id=command.transaction_id,
                trigger=command.trigger.value,
                requested_at=_ensure_utc(command.requested_at),
            )
            for command in commands
        ],
    )


def record_session_stop_command_result(
    db: Session,
    *,
    command_id: int,
    gateway_id: str,
    result: str,
    error_code: str | None,
    actor_user: User | None,
) -> SessionStopCommandResponse:
    charger, _ = _resolve_gateway(db, gateway_id, actor_user)
    command = (
        db.query(ChargingSessionCommand)
        .filter(ChargingSessionCommand.id == command_id)
        .first()
    )
    if command is None or command.charger_id != charger.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Stop command not found."
        )

    target_status = (
        SessionStopCommandStatus.ACCEPTED
        if result == SessionStopCommandStatus.ACCEPTED.value
        else SessionStopCommandStatus.REJECTED
    )
    if command.status == SessionStopCommandStatus.COMPLETED:
        if target_status == SessionStopCommandStatus.ACCEPTED:
            return _command_response(
                command,
                message="The session has already been confirmed stopped.",
                already_requested=True,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A completed stop command cannot be changed to Rejected.",
        )
    if command.status != SessionStopCommandStatus.PENDING:
        if command.status == target_status:
            return _command_response(
                command,
                message="Duplicate gateway command result ignored.",
                already_requested=True,
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The stop command already has a different gateway result.",
        )

    command.status = target_status
    command.responded_at = datetime.now(_ensure_utc(command.requested_at).tzinfo)
    command.error_code = error_code.strip() if error_code and error_code.strip() else None
    db.commit()
    db.refresh(command)
    return _command_response(
        command,
        message=(
            "Gateway accepted the stop command."
            if target_status == SessionStopCommandStatus.ACCEPTED
            else "Gateway rejected the stop command."
        ),
    )


def maybe_queue_target_energy_stop(
    db: Session,
    *,
    booking: Booking,
    latest_reading: ChargingSessionReading,
) -> tuple[bool, ChargingSessionCommand | None, str | None]:
    target_kwh = booking.est_energy_kwh
    if target_kwh is None or target_kwh <= 0:
        return False, None, None

    first_reading = (
        db.query(ChargingSessionReading)
        .filter(
            ChargingSessionReading.booking_id == booking.id,
            ChargingSessionReading.connector_id == latest_reading.connector_id,
        )
        .order_by(
            ChargingSessionReading.observed_at.asc(),
            ChargingSessionReading.id.asc(),
        )
        .first()
    )
    if first_reading is None:
        return False, None, None

    energy_delivered = max(
        0.0, latest_reading.energy_meter_kwh - first_reading.energy_meter_kwh
    )
    if energy_delivered < target_kwh:
        return False, None, None

    transaction_reading = latest_reading
    if transaction_reading.transaction_id is None:
        transaction_reading = (
            db.query(ChargingSessionReading)
            .filter(
                ChargingSessionReading.booking_id == booking.id,
                ChargingSessionReading.connector_id == latest_reading.connector_id,
                ChargingSessionReading.transaction_id.isnot(None),
            )
            .order_by(
                ChargingSessionReading.observed_at.desc(),
                ChargingSessionReading.id.desc(),
            )
            .first()
        )
    if transaction_reading is None:
        return (
            True,
            None,
            "Target energy reached, but no OCPP transaction ID is available to queue a stop.",
        )

    existing = (
        db.query(ChargingSessionCommand)
        .filter(
            ChargingSessionCommand.booking_id == booking.id,
            ChargingSessionCommand.transaction_id == transaction_reading.transaction_id,
        )
        .order_by(ChargingSessionCommand.id.desc())
        .first()
    )
    if existing is not None:
        return True, existing, None

    command = ChargingSessionCommand(
        booking_id=booking.id,
        charger_id=transaction_reading.charger_id,
        connector_id=transaction_reading.connector_id,
        transaction_id=transaction_reading.transaction_id,
        trigger=SessionStopCommandTrigger.TARGET_ENERGY,
        status=SessionStopCommandStatus.PENDING,
    )
    db.add(command)
    db.flush()
    return True, command, None


def record_session_stop_transaction(
    db: Session,
    *,
    payload: SessionStopTransactionRequest,
    actor_user: User | None,
) -> SessionStopTransactionResponse:
    charger, _ = _resolve_gateway(db, payload.gateway_id, actor_user)
    observed_at = validate_observed_at(payload.observed_at)
    idempotency_key = (
        payload.idempotency_key.strip()
        if payload.idempotency_key and payload.idempotency_key.strip()
        else None
    )

    if idempotency_key is not None:
        previous = (
            db.query(Booking)
            .filter(Booking.stop_event_idempotency_key == idempotency_key)
            .first()
        )
        if previous is not None:
            if (
                previous.charger_id != charger.id
                or previous.session_transaction_id != payload.transaction_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="StopTransaction message ID has already been used for another session.",
                )
            return SessionStopTransactionResponse(
                booking_id=previous.id,
                transaction_id=payload.transaction_id,
                status=previous.status.value,
                session_ended_at=_ensure_utc(previous.session_ended_at),
                meter_stop_wh=previous.meter_stop_wh,
                applied=False,
                idempotent_replay=True,
            )

    completed = (
        db.query(Booking)
        .filter(
            Booking.charger_id == charger.id,
            Booking.session_transaction_id == payload.transaction_id,
            Booking.status == BookingStatus.COMPLETED,
            Booking.session_ended_at.isnot(None),
        )
        .order_by(Booking.session_ended_at.desc())
        .first()
    )
    if completed is not None:
        return SessionStopTransactionResponse(
            booking_id=completed.id,
            transaction_id=payload.transaction_id,
            status=completed.status.value,
            session_ended_at=_ensure_utc(completed.session_ended_at),
            meter_stop_wh=completed.meter_stop_wh,
            applied=False,
            idempotent_replay=True,
        )

    readings = (
        db.query(ChargingSessionReading)
        .filter(
            ChargingSessionReading.charger_id == charger.id,
            ChargingSessionReading.transaction_id == payload.transaction_id,
        )
        .all()
    )
    booking_ids = {reading.booking_id for reading in readings}
    bookings = (
        db.query(Booking)
        .filter(
            Booking.id.in_(booking_ids or {-1}),
            Booking.status == BookingStatus.ACTIVE,
        )
        .all()
    )
    matching_bookings = [
        booking
        for booking in bookings
        if booking.connector_id is None
        or any(
            reading.booking_id == booking.id
            and reading.connector_id == booking.connector_id
            for reading in readings
        )
    ]
    if not matching_bookings:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active booking matches this OCPP transaction.",
        )
    if len(matching_bookings) != 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="StopTransaction matches more than one active booking.",
        )

    booking = matching_bookings[0]
    booking.status = BookingStatus.COMPLETED
    booking.session_ended_at = observed_at
    booking.session_transaction_id = payload.transaction_id
    booking.meter_stop_wh = payload.meter_stop_wh
    booking.stop_event_idempotency_key = idempotency_key
    commands = (
        db.query(ChargingSessionCommand)
        .filter(
            ChargingSessionCommand.booking_id == booking.id,
            ChargingSessionCommand.transaction_id == payload.transaction_id,
            ChargingSessionCommand.status != SessionStopCommandStatus.COMPLETED,
        )
        .all()
    )
    for command in commands:
        command.status = SessionStopCommandStatus.COMPLETED
        command.responded_at = observed_at
    db.commit()
    db.refresh(booking)
    return SessionStopTransactionResponse(
        booking_id=booking.id,
        transaction_id=payload.transaction_id,
        status=booking.status.value,
        session_ended_at=_ensure_utc(booking.session_ended_at),
        meter_stop_wh=booking.meter_stop_wh,
        applied=True,
        idempotent_replay=False,
    )
