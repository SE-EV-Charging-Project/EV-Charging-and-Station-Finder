from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.booking.qr import verify_checkin_qr_payload
from app.discovery.search import haversine_distance
from app.models.booking import Booking, BookingStatus
from app.models.station import Station
from app.models.user import User, UserRole
from app.schemas.booking import BookingCheckinRequest, BookingCheckinResponse

MAX_CHECKIN_DISTANCE_KM = 0.3


def _verify_qr(payload: str, booking: Booking) -> bool:
    parsed = urlsplit(payload)
    if (
        parsed.scheme != "chargeslot"
        or parsed.netloc != "check-in"
        or parsed.path != f"/{booking.id}"
    ):
        return False
    signatures = parse_qs(parsed.query).get("signature", [])
    return len(signatures) == 1 and verify_checkin_qr_payload(
        booking.id,
        booking.user_id,
        signatures[0],
    )


def check_in_booking(
    db: Session,
    user: User,
    booking_id: int,
    payload: BookingCheckinRequest,
) -> BookingCheckinResponse:
    booking = (
        db.query(Booking)
        .filter(Booking.id == booking_id)
        .with_for_update()
        .first()
    )
    if booking is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with ID {booking_id} not found.",
        )
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking driver or an administrator can check in.",
        )
    if user.role == UserRole.DRIVER and booking.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Booking with ID {booking_id} not found.",
        )
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only a confirmed booking can check in.",
        )
    if booking.checked_in_at is not None:
        return BookingCheckinResponse(
            booking_id=booking.id,
            checked_in_at=booking.checked_in_at,
            message="Booking check-in was already recorded.",
        )

    if payload.qr_code_payload is not None:
        valid_proof = _verify_qr(payload.qr_code_payload, booking)
    else:
        if payload.latitude is None or payload.longitude is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Provide either a QR code payload or both coordinates.",
            )
        station = (
            db.query(Station)
            .filter(Station.id == booking.station_id)
            .first()
            if booking.station_id is not None
            else None
        )
        if station is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Booking station coordinates are unavailable for check-in.",
            )
        valid_proof = (
            haversine_distance(
                payload.latitude,
                payload.longitude,
                station.latitude,
                station.longitude,
            )
            <= MAX_CHECKIN_DISTANCE_KM
        )

    if not valid_proof:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Check-in proof is invalid or the driver is more than 300 metres away.",
        )

    booking.checked_in_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(booking)
    return BookingCheckinResponse(
        booking_id=booking.id,
        checked_in_at=booking.checked_in_at,
        message="Booking check-in recorded.",
    )
