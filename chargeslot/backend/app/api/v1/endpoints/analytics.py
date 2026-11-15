from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.analytics import AnalyticsSummaryResponse
from app.services.analytics_service import (
    export_analytics_csv,
    get_analytics_summary,
)

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/summary", response_model=AnalyticsSummaryResponse)
def analytics_summary(
    start_date: date | None = None,
    end_date: date | None = None,
    granularity: Literal["week", "month"] = Query(default="week"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AnalyticsSummaryResponse:
    return get_analytics_summary(
        db,
        current_user,
        start_date=start_date,
        end_date=end_date,
        granularity=granularity,
    )


@router.get(
    "/export.csv",
    response_class=Response,
    responses={200: {"content": {"text/csv": {}}}},
)
def export_analytics(
    start_date: date | None = None,
    end_date: date | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    contents = export_analytics_csv(
        db,
        current_user,
        start_date=start_date,
        end_date=end_date,
    )
    return Response(
        content=contents,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="chargeslot-analytics.csv"'},
    )
