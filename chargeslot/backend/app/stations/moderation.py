"""
Station Moderation & Approval Gate Service
Requirement: REQ-F2-03 (Station approval gate)
SRS Architecture Reference: HLD §Stations, SDD §Stations
Code File Reference: stations/moderation.py (SRS Page 35)
Story ID: CS19-029
Test Case ID: TC-F2-03, STC-F2-03
"""

from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.models.station import Station, StationStatus
from app.models.user import User, UserRole
from app.services.audit_service import AuditService


class StationModerationService:
    """
    Service enforcing the Station Approval Gate (REQ-F2-03 / CS19-029).
    Keeps new or edited stations hidden from drivers until approved by an Administrator.
    Provides admin approval, rejection with reasons, pending queue listing,
    and driver visibility filtering.
    """

    @staticmethod
    def is_station_visible_to_drivers(station: Station) -> bool:
        """
        Determines if a station is discoverable/visible to drivers (REQ-F2-03).
        A station is ONLY visible to drivers when:
        1. status is APPROVED
        2. is_active is True
        """
        return station.status == StationStatus.APPROVED and station.is_active is True

    @staticmethod
    def approve_station(
        db: Session,
        admin: User,
        station_id: int,
        ip_address: str | None = None,
    ) -> Station:
        """
        Approves a station by Administrator (REQ-F2-03).
        Sets status to APPROVED, records admin metadata, clears rejection reasons,
        and logs audit event.
        """
        if admin.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative privileges required to approve stations (REQ-F2-03).",
            )

        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        station.status = StationStatus.APPROVED
        station.reviewed_by_admin_id = admin.id
        station.reviewed_at = datetime.now(timezone.utc)
        station.rejection_reason = None

        db.commit()
        db.refresh(station)

        AuditService.log_action(
            db=db,
            user_id=admin.id,
            action="STATION_APPROVED",
            resource=f"Station:{station.id}",
            details=f"Station '{station.name}' (id={station.id}) approved by Admin {admin.id}",
            ip_address=ip_address,
        )

        return station

    @staticmethod
    def reject_station(
        db: Session,
        admin: User,
        station_id: int,
        reason: str,
        ip_address: str | None = None,
    ) -> Station:
        """
        Rejects a station by Administrator with a mandatory reason (REQ-F2-03).
        Sets status to REJECTED, records rejection details and reviewer metadata,
        and logs audit event.
        """
        if admin.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative privileges required to reject stations (REQ-F2-03).",
            )

        if not reason or not reason.strip():
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Rejection reason is required and cannot be empty (REQ-F2-03).",
            )

        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        station.status = StationStatus.REJECTED
        station.rejection_reason = reason.strip()
        station.reviewed_by_admin_id = admin.id
        station.reviewed_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(station)

        AuditService.log_action(
            db=db,
            user_id=admin.id,
            action="STATION_REJECTED",
            resource=f"Station:{station.id}",
            details=f"Station '{station.name}' (id={station.id}) rejected by Admin {admin.id}: {reason.strip()}",
            ip_address=ip_address,
        )

        return station

    @staticmethod
    def list_pending_stations(
        db: Session,
        admin: User,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Station], int]:
        """
        Lists all stations currently pending administrative approval (REQ-F2-03).
        Restricted to Administrators.
        """
        if admin.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Administrative privileges required to view pending stations queue.",
            )

        query = db.query(Station).filter(Station.status == StationStatus.PENDING)
        total = query.count()
        items = (
            query.order_by(desc(Station.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def get_approval_gate_status(
        db: Session,
        user: User,
        station_id: int,
    ) -> dict:
        """
        Inspects station approval gate and driver visibility status (REQ-F2-03).
        Enforces tenant/role access boundaries.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        visible = StationModerationService.is_station_visible_to_drivers(station)

        # Drivers can only query status if station is approved & visible, otherwise hidden
        if user.role == UserRole.DRIVER and not visible:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Station is pending administrative approval and hidden from drivers (REQ-F2-03).",
            )

        # Operators can only inspect their own station's approval gate
        if user.role == UserRole.OPERATOR and station.operator_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to foreign station approval gate (REQ-F1-12).",
            )

        return {
            "station_id": station.id,
            "station_name": station.name,
            "status": station.status,
            "is_active": station.is_active,
            "visible_to_drivers": visible,
            "can_approve": user.role == UserRole.ADMIN,
            "rejection_reason": station.rejection_reason,
            "reviewed_by_admin_id": station.reviewed_by_admin_id,
            "reviewed_at": station.reviewed_at,
        }

    @staticmethod
    def process_gate_action(
        db: Session,
        admin: User,
        station_id: int,
        action: str,
        reason: str | None = None,
        ip_address: str | None = None,
    ) -> Station:
        """
        Processes an approval gate moderation action ('approve' or 'reject') (REQ-F2-03).
        """
        act = action.strip().lower()
        if act == "approve":
            return StationModerationService.approve_station(
                db=db, admin=admin, station_id=station_id, ip_address=ip_address
            )
        elif act == "reject":
            if not reason or not reason.strip():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Rejection reason is required when rejecting a station.",
                )
            return StationModerationService.reject_station(
                db=db, admin=admin, station_id=station_id, reason=reason, ip_address=ip_address
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid approval gate action '{action}'. Must be 'approve' or 'reject'.",
            )
