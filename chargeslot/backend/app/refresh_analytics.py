from app.db.session import SessionLocal
from app.services.analytics_service import refresh_analytics_snapshot


def run_analytics_refresh() -> None:
    db = SessionLocal()
    try:
        snapshot = refresh_analytics_snapshot(db)
        print(f"Analytics snapshot refreshed at {snapshot.refreshed_at.isoformat()}")
    finally:
        db.close()


if __name__ == "__main__":
    run_analytics_refresh()
