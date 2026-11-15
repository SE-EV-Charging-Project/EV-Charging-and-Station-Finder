import hashlib
import hmac

from app.core.config import settings


def make_checkin_qr_payload(booking_id: int, owner_id: int) -> str:
    message = f"{booking_id}:{owner_id}".encode("utf-8")
    signature = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()
    return f"chargeslot://check-in/{booking_id}?signature={signature}"


def verify_checkin_qr_payload(
    booking_id: int,
    owner_id: int,
    signature: str,
) -> bool:
    expected_payload = make_checkin_qr_payload(booking_id, owner_id)
    expected_signature = expected_payload.partition("signature=")[2]
    return hmac.compare_digest(expected_signature, signature)
