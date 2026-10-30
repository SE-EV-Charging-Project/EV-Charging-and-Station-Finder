from datetime import datetime
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.audit import AuditLog
from app.models.user import User


class AuditService:
    """
    Service handling system audit logging and compliance (CS19-014 / REQ-F1-14).
    Logs all role changes, administrative actions, and operator onboarding decisions
    with acting user, timestamp, resource, and change details.
    """

    @staticmethod
    def log_action(
        db: Session,
        user_id: int | None,
        action: str,
        resource: str | None = None,
        details: str | None = None,
        ip_address: str | None = None,
        commit: bool = True,
    ) -> AuditLog:
        """
        Record an immutable audit log entry.
        """
        audit = AuditLog(
            user_id=user_id,
            action=action.strip(),
            resource=resource.strip() if resource else None,
            details=details.strip() if details else None,
            ip_address=ip_address.strip() if ip_address else None,
        )
        db.add(audit)
        if commit:
            db.commit()
            db.refresh(audit)
        else:
            db.flush()
        return audit

    @staticmethod
    def list_logs(
        db: Session,
        user_id: int | None = None,
        action: str | None = None,
        resource: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[dict], int]:
        """
        Query audit log entries with optional filters and pagination.
        """
        q = db.query(AuditLog)

        if user_id is not None:
            q = q.filter(AuditLog.user_id == user_id)

        if action:
            q = q.filter(AuditLog.action.ilike(f"%{action.strip()}%"))

        if resource:
            q = q.filter(AuditLog.resource == resource.strip())

        if start_date is not None:
            q = q.filter(AuditLog.timestamp >= start_date)

        if end_date is not None:
            q = q.filter(AuditLog.timestamp <= end_date)

        total = q.count()
        logs = q.order_by(desc(AuditLog.timestamp)).offset(skip).limit(limit).all()

        results: list[dict] = []
        for l in logs:
            results.append({
                "id": l.id,
                "user_id": l.user_id,
                "user_email": l.user.email if l.user else None,
                "action": l.action,
                "resource": l.resource,
                "details": l.details,
                "ip_address": l.ip_address,
                "timestamp": l.timestamp,
            })

        return results, total
