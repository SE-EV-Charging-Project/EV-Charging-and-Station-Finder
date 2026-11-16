from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class AnalyticsSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["driver", "operator", "platform"]
    start_date: date
    end_date: date
    refreshed_at: datetime
    totals: dict[str, int | float]
    trends: list[dict[str, Any]]
    top_stations: list[dict[str, Any]]
    stations: list[dict[str, Any]]
