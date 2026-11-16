from datetime import date, datetime, timedelta, timezone
import json

from app.db.session import SessionLocal
from app.models.user import User, UserRole
from app.services.reconciliation_service import reconcile_daily


def run_daily_reconciliation(day: date | None = None) -> None:
    db = SessionLocal()
    try:
        system_admin = db.query(User).filter(User.role == UserRole.ADMIN).first()
        if system_admin is None:
            raise RuntimeError("Daily reconciliation requires an administrator account.")
        result = reconcile_daily(
            db,
            system_admin,
            day or datetime.now(timezone.utc).date() - timedelta(days=1),
        )
        print(json.dumps(result.model_dump(mode="json"), sort_keys=True))
    finally:
        db.close()


if __name__ == "__main__":
    run_daily_reconciliation()
