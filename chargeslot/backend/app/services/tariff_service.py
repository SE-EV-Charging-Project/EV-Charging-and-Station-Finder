from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import enforce_operator_scope
from app.models.station import Station
from app.models.station_tariff import StationTariff
from app.models.user import User
from app.schemas.billing import StationTariffResponse, StationTariffUpdate


class TariffService:
    @staticmethod
    def get_current(db: Session, station_id: int) -> StationTariff | None:
        now = datetime.now(timezone.utc)
        return (
            db.query(StationTariff)
            .filter(
                StationTariff.station_id == station_id,
                StationTariff.effective_from <= now,
            )
            .order_by(StationTariff.effective_from.desc(), StationTariff.id.desc())
            .first()
        )

    @staticmethod
    def _station_for_operator(db: Session, user: User, station_id: int) -> Station:
        station = db.query(Station).filter(Station.id == station_id).first()
        if station is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Station not found.",
            )
        enforce_operator_scope(user, station.operator_id)
        return station

    @classmethod
    def get_tariff(
        cls, db: Session, user: User, station_id: int
    ) -> StationTariffResponse:
        station = cls._station_for_operator(db, user, station_id)
        tariff = cls.get_current(db, station.id)
        if tariff is None:
            return StationTariffResponse(
                id=None,
                station_id=station.id,
                price_per_kwh=station.price_per_kwh or 0.0,
                idle_fee_per_minute=0.0,
                tax_rate_percent=0.0,
                peak_periods=[],
                effective_from=None,
            )
        return StationTariffResponse.model_validate(
            {
                "id": tariff.id,
                "station_id": tariff.station_id,
                "price_per_kwh": tariff.price_per_kwh,
                "idle_fee_per_minute": tariff.idle_fee_per_minute,
                "tax_rate_percent": tariff.tax_rate_percent,
                "peak_periods": tariff.peak_periods,
                "effective_from": tariff.effective_from,
            }
        )

    @classmethod
    def update_tariff(
        cls,
        db: Session,
        user: User,
        station_id: int,
        data: StationTariffUpdate,
    ) -> StationTariffResponse:
        station = cls._station_for_operator(db, user, station_id)
        now = datetime.now(timezone.utc)

        tariff = StationTariff(
            station_id=station.id,
            created_by_user_id=user.id,
            price_per_kwh=data.price_per_kwh,
            idle_fee_per_minute=data.idle_fee_per_minute,
            tax_rate_percent=data.tax_rate_percent,
            peak_periods=[
                period.model_dump(mode="json") for period in data.peak_periods
            ],
            effective_from=now,
        )
        db.add(tariff)
        station.price_per_kwh = data.price_per_kwh
        db.commit()
        db.refresh(tariff)
        return StationTariffResponse.model_validate(
            {
                "id": tariff.id,
                "station_id": tariff.station_id,
                "price_per_kwh": tariff.price_per_kwh,
                "idle_fee_per_minute": tariff.idle_fee_per_minute,
                "tax_rate_percent": tariff.tax_rate_percent,
                "peak_periods": tariff.peak_periods,
                "effective_from": tariff.effective_from,
            }
        )
