from datetime import datetime, time

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PeakPeriod(BaseModel):
    start: time
    end: time
    multiplier: float = Field(default=1.0, gt=0, le=10, strict=True)

    @model_validator(mode="after")
    def reject_empty_period(self) -> "PeakPeriod":
        if self.start == self.end:
            raise ValueError("A peak period must have a non-zero duration.")
        return self


class StationTariffUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    price_per_kwh: float = Field(ge=0, le=100_000, strict=True)
    idle_fee_per_minute: float = Field(default=0, ge=0, le=100_000, strict=True)
    tax_rate_percent: float = Field(default=0, ge=0, le=100, strict=True)
    peak_periods: list[PeakPeriod] = Field(default_factory=list, max_length=24)


class StationTariffResponse(BaseModel):
    id: int | None
    station_id: int
    price_per_kwh: float
    idle_fee_per_minute: float
    tax_rate_percent: float
    peak_periods: list[PeakPeriod]
    effective_from: datetime | None

    model_config = ConfigDict(from_attributes=True)


class ReconciliationResponse(BaseModel):
    reconciled_on: str
    gateway_payment_count: int
    internal_payment_count: int
    discrepancies: list[dict]
    created_at: datetime
