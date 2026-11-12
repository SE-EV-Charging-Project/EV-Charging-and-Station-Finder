from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.permissions import enforce_operator_scope
from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.models.charger import Charger
from app.models.maintenance import MaintenanceWindow
from app.models.booking import Booking, BookingStatus
from app.schemas.maintenance import (
    MaintenanceWindowCreateRequest,
    MaintenanceWindowUpdateRequest,
    SlotItem,
)
from app.services.audit_service import AuditService
from app.stations.slots import filter_slots_by_maintenance, ensure_utc


class MaintenanceService:
    """
    Service handling Maintenance Window lifecycle, Operator tenancy enforcement,
    booking conflict mitigation, and slot availability filtering (REQ-F2-06 / CS19-032).
    """

    @staticmethod
    def create_maintenance_window(
        db: Session,
        station_id: int,
        user: User,
        data: MaintenanceWindowCreateRequest,
        ip_address: str | None = None,
    ) -> MaintenanceWindow:
        """
        Creates a new maintenance window for a station or specific charger (REQ-F2-06).
        Ensures operator owns the station and removes conflicting slots/bookings.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        enforce_operator_scope(user, station.operator_id)

        start_time_utc = ensure_utc(data.start_time)
        end_time_utc = ensure_utc(data.end_time)

        if end_time_utc <= start_time_utc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Maintenance window end_time must be strictly after start_time.",
            )

        if data.charger_id is not None:
            charger = db.query(Charger).filter(
                Charger.id == data.charger_id,
                Charger.station_id == station_id,
            ).first()
            if not charger:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Charger with ID {data.charger_id} does not belong to station {station_id}.",
                )

        window = MaintenanceWindow(
            station_id=station_id,
            charger_id=data.charger_id,
            title=data.title.strip(),
            description=data.description.strip() if data.description else None,
            start_time=start_time_utc,
            end_time=end_time_utc,
            created_by_user_id=user.id,
        )
        db.add(window)
        db.flush()

        # Invalidate/cancel any active or confirmed bookings overlapping this window (REQ-F2-06)
        booking_query = db.query(Booking).filter(
            Booking.station_id == station_id,
            Booking.status.in_([BookingStatus.CONFIRMED, BookingStatus.HELD]),
            Booking.start_time < end_time_utc,
            Booking.end_time > start_time_utc,
        )
        if data.charger_id is not None:
            booking_query = booking_query.filter(Booking.charger_id == data.charger_id)

        conflicting_bookings = booking_query.all()
        for b in conflicting_bookings:
            b.status = BookingStatus.CANCELLED
            AuditService.log_action(
                db=db,
                user_id=user.id,
                action="BOOKING_CANCELLED_MAINTENANCE",
                resource=f"Booking:{b.id}",
                details=f"Booking {b.id} cancelled due to maintenance window '{window.title}' (ID {window.id})",
                ip_address=ip_address,
            )

        db.commit()
        db.refresh(window)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="MAINTENANCE_WINDOW_CREATED",
            resource=f"MaintenanceWindow:{window.id}",
            details=f"Maintenance window '{window.title}' created for station {station_id} (charger: {window.charger_id or 'ALL'})",
            ip_address=ip_address,
        )

        return window

    @staticmethod
    def get_maintenance_window(
        db: Session,
        window_id: int,
        user: User,
    ) -> MaintenanceWindow:
        """
        Retrieves a maintenance window with RBAC check.
        """
        window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
        if not window:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Maintenance window with ID {window_id} not found.",
            )

        if user.role == UserRole.OPERATOR:
            station = db.query(Station).filter(Station.id == window.station_id).first()
            if station:
                enforce_operator_scope(user, station.operator_id)

        return window

    @staticmethod
    def list_maintenance_windows(
        db: Session,
        user: User,
        station_id: int | None = None,
        charger_id: int | None = None,
        active_only: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> tuple[int, list[MaintenanceWindow]]:
        """
        List maintenance windows filtered by station, charger, and operator tenancy.
        Supports global GET /api/v1/stations/maintenance-windows (Architecture Doc Page 6).
        """
        query = db.query(MaintenanceWindow)

        if station_id is not None:
            station = db.query(Station).filter(Station.id == station_id).first()
            if not station:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Station with ID {station_id} not found.",
                )
            if user.role == UserRole.OPERATOR:
                enforce_operator_scope(user, station.operator_id)
            query = query.filter(MaintenanceWindow.station_id == station_id)
        else:
            if user.role == UserRole.OPERATOR:
                query = query.join(Station).filter(Station.operator_id == user.id)
            elif user.role == UserRole.DRIVER:
                query = query.join(Station).filter(
                    Station.status == StationStatus.APPROVED,
                    Station.is_active.is_(True),
                )

        if charger_id is not None:
            query = query.filter(
                or_(
                    MaintenanceWindow.charger_id == charger_id,
                    MaintenanceWindow.charger_id.is_(None),
                )
            )

        if active_only:
            now_utc = datetime.now(timezone.utc)
            query = query.filter(MaintenanceWindow.end_time >= now_utc)

        total = query.count()
        items = query.order_by(MaintenanceWindow.start_time.asc()).offset(skip).limit(limit).all()
        return total, items

    @staticmethod
    def update_maintenance_window(
        db: Session,
        window_id: int,
        user: User,
        data: MaintenanceWindowUpdateRequest,
        ip_address: str | None = None,
    ) -> MaintenanceWindow:
        """
        Updates an existing maintenance window.
        """
        window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
        if not window:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Maintenance window with ID {window_id} not found.",
            )

        station = db.query(Station).filter(Station.id == window.station_id).first()
        if station:
            enforce_operator_scope(user, station.operator_id)

        if data.charger_id is not None:
            charger = db.query(Charger).filter(
                Charger.id == data.charger_id,
                Charger.station_id == window.station_id,
            ).first()
            if not charger:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Charger with ID {data.charger_id} does not belong to station {window.station_id}.",
                )
            window.charger_id = data.charger_id

        if data.title is not None:
            window.title = data.title.strip()

        if data.description is not None:
            window.description = data.description.strip()

        new_start = ensure_utc(data.start_time) if data.start_time is not None else ensure_utc(window.start_time)
        new_end = ensure_utc(data.end_time) if data.end_time is not None else ensure_utc(window.end_time)

        if new_end <= new_start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Maintenance window end_time must be strictly after start_time.",
            )

        window.start_time = new_start
        window.end_time = new_end
        window.updated_at = datetime.now(timezone.utc)

        db.commit()
        db.refresh(window)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="MAINTENANCE_WINDOW_UPDATED",
            resource=f"MaintenanceWindow:{window.id}",
            details=f"Maintenance window {window.id} updated",
            ip_address=ip_address,
        )

        return window

    @staticmethod
    def delete_maintenance_window(
        db: Session,
        window_id: int,
        user: User,
        ip_address: str | None = None,
    ) -> bool:
        """
        Deletes a maintenance window, restoring slot availability.
        """
        window = db.query(MaintenanceWindow).filter(MaintenanceWindow.id == window_id).first()
        if not window:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Maintenance window with ID {window_id} not found.",
            )

        station = db.query(Station).filter(Station.id == window.station_id).first()
        if station:
            enforce_operator_scope(user, station.operator_id)

        db.delete(window)
        db.commit()

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="MAINTENANCE_WINDOW_DELETED",
            resource=f"MaintenanceWindow:{window_id}",
            details=f"Maintenance window {window_id} deleted",
            ip_address=ip_address,
        )

        return True

    @staticmethod
    def check_slot_availability(
        db: Session,
        station_id: int,
        slots: list[SlotItem],
    ) -> tuple[list[SlotItem], list[SlotItem]]:
        """
        Verifies a list of candidate slots for a station and removes those overlapping
        active maintenance windows (REQ-F2-06).
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        windows = db.query(MaintenanceWindow).filter(MaintenanceWindow.station_id == station_id).all()
        return filter_slots_by_maintenance(slots, windows)
