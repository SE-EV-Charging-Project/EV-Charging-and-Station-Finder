from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.booking import Booking, BookingStatus
from app.models.payment_record import PaymentRecord
from app.models.station import Station
from app.models.user import User, UserRole


def _escape_pdf_text(value: str) -> bytes:
    cleaned = "".join(
        character if character.isprintable() and character not in "\r\n" else " "
        for character in value
    )
    return (
        cleaned.encode("cp1252", errors="replace")
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )


def _render_pdf(lines: list[str]) -> bytes:
    text_commands = [b"BT /F1 12 Tf 50 760 Td"]
    for index, line in enumerate(lines):
        if index:
            text_commands.append(b"0 -20 Td")
        text_commands.extend((b"(", _escape_pdf_text(line), b") Tj"))
    text_commands.append(b"ET")
    stream = b" ".join(text_commands)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for object_number, content in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{object_number} 0 obj\n".encode("ascii"))
        output.extend(content)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)


def generate_invoice(db: Session, user: User, booking_id: int) -> bytes:
    booking = db.query(Booking).filter(Booking.id == booking_id).first()
    if booking is None:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if user.role not in (UserRole.DRIVER, UserRole.ADMIN):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the booking driver or an administrator can access this invoice.",
        )
    if user.role == UserRole.DRIVER and booking.user_id != user.id:
        raise HTTPException(status_code=404, detail="Booking not found.")
    if booking.status != BookingStatus.COMPLETED or booking.payment_due:
        raise HTTPException(
            status_code=409,
            detail="An invoice is available only after the completed session is paid.",
        )

    captured = (
        db.query(PaymentRecord.id)
        .filter(
            PaymentRecord.booking_id == booking.id,
            PaymentRecord.status == "captured",
            PaymentRecord.payment_type.in_(("reservation", "balance", "session")),
        )
        .first()
    )
    if captured is None:
        raise HTTPException(
            status_code=409,
            detail="An invoice is available only after payment has been captured.",
        )
    station = (
        db.query(Station).filter(Station.id == booking.station_id).first()
        if booking.station_id is not None
        else None
    )
    ended_at = booking.session_ended_at or datetime.now(timezone.utc)
    if ended_at.tzinfo is None:
        ended_at = ended_at.replace(tzinfo=timezone.utc)
    total = (
        booking.energy_cost_amount
        + booking.idle_fee_amount
        + booking.tax_amount
    )
    lines = [
        "ChargeSlot - Tax Invoice",
        f"Invoice: CS-{booking.id:08d}",
        f"Issued: {ended_at.astimezone(timezone.utc).isoformat()}",
        f"Booking: {booking.id}",
        f"Station: {station.name if station else 'Station unavailable'}",
        f"Energy: {booking.energy_delivered_kwh:.3f} kWh",
        f"Energy charges: INR {booking.energy_cost_amount:.2f}",
        f"Idle fee: INR {booking.idle_fee_amount:.2f}",
        f"Taxes: INR {booking.tax_amount:.2f}",
        f"Reservation fee credit: INR {booking.reservation_fee_paid_amount:.2f}",
        f"Amount paid: INR {total:.2f}",
        "Currency: INR",
    ]
    return _render_pdf(lines)
