from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_operator
from app.db.session import get_db
from app.models.user import User
from app.schemas.billing import StationTariffResponse, StationTariffUpdate
from app.services.tariff_service import TariffService

router = APIRouter(prefix="/stations", tags=["Station tariffs"])


@router.get(
    "/{station_id}/tariff",
    response_model=StationTariffResponse,
)
def get_station_tariff(
    station_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StationTariffResponse:
    return TariffService.get_tariff(db, current_user, station_id)


@router.put(
    "/{station_id}/tariff",
    response_model=StationTariffResponse,
    status_code=status.HTTP_200_OK,
)
def update_station_tariff(
    station_id: int,
    payload: StationTariffUpdate,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> StationTariffResponse:
    return TariffService.update_tariff(db, current_user, station_id, payload)
