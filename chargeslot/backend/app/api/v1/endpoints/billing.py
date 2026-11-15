from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.invoice_service import generate_invoice

router = APIRouter(prefix="/billing", tags=["Billing"])


@router.get(
    "/bookings/{booking_id}/invoice",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_booking_invoice(
    booking_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    pdf = generate_invoice(db, current_user, booking_id)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="chargeslot-invoice-{booking_id}.pdf"'
        },
    )
