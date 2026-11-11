from fastapi import HTTPException, status
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.core.permissions import enforce_operator_scope, scope_operator_query
from app.models.user import User, UserRole
from app.models.station import Station, StationStatus
from app.schemas.station import (
    StationCreateRequest,
    StationUpdateRequest,
    StationResponse,
)
from app.services.audit_service import AuditService
from app.stations.validators import (
    enforce_station_values,
    validate_station_values,
    validate_charger_values,
    get_station_validation_rules,
)
from app.stations.moderation import StationModerationService


class StationService:
    """
    Service handling Station CRUD, validation, and deactivation
    (CS19-027 / CS19-030 / REQ-F2-01 / REQ-F2-04 / Appendix B.4).
    """

    @staticmethod
    def create_station(
        db: Session,
        user: User,
        data: StationCreateRequest,
        ip_address: str | None = None,
    ) -> Station:
        """
        Creates a new charging station managed by the authenticated Station Operator.
        Initial status is 'pending' awaiting Admin approval (REQ-F2-01, REQ-F2-03).
        Validates coordinates and fields per REQ-F2-04 / Appendix B.4.
        """
        if user.role not in [UserRole.OPERATOR, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions: Station Operator or Administrator role required (REQ-F1-11).",
            )

        # Enforce validation rules per REQ-F2-04
        enforce_station_values(data.model_dump())

        station = Station(
            operator_id=user.id,
            name=data.name,
            address=data.address,
            latitude=data.latitude,
            longitude=data.longitude,
            amenities=data.amenities,
            operating_hours=data.operating_hours,
            contact_phone=data.contact_phone,
            contact_email=data.contact_email,
            price_per_kwh=data.price_per_kwh,
            status=StationStatus.PENDING,
            is_active=True,
        )
        db.add(station)
        db.commit()
        db.refresh(station)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="STATION_CREATED",
            resource=f"Station:{station.id}",
            details=f"Station '{station.name}' created by operator {user.id}",
            ip_address=ip_address,
        )

        return station

    @staticmethod
    def list_stations(
        db: Session,
        user: User,
        is_active: bool | None = None,
        status_filter: StationStatus | None = None,
        search_query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Station], int]:
        """
        Lists stations with role-based scoping:
        - Station Operators view only their own stations (REQ-F1-12).
        - Administrators view all stations across operators.
        - Drivers view only approved active stations (REQ-F2-03).
        """
        query = db.query(Station)
        if user.role == UserRole.DRIVER:
            # REQ-F2-03: Hidden from drivers until approved and active
            query = query.filter(
                Station.status == StationStatus.APPROVED,
                Station.is_active.is_(True),
            )
        else:
            query = scope_operator_query(query, Station, user, operator_id_attr="operator_id")

        if is_active is not None and user.role != UserRole.DRIVER:
            query = query.filter(Station.is_active == is_active)

        if status_filter is not None and user.role != UserRole.DRIVER:
            query = query.filter(Station.status == status_filter)

        if search_query:
            term = f"%{search_query.strip()}%"
            query = query.filter(
                or_(
                    Station.name.ilike(term),
                    Station.address.ilike(term),
                )
            )

        total = query.count()
        items = (
            query.order_by(Station.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )
        return items, total

    @staticmethod
    def get_station(
        db: Session,
        user: User,
        station_id: int,
    ) -> Station:
        """
        Retrieves a station by ID with role-based scoping:
        - Operators can access only their own stations (REQ-F1-12).
        - Drivers can view only approved active stations; unapproved/inactive are hidden (REQ-F2-03).
        - Administrators have global access across stations.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        if user.role == UserRole.ADMIN:
            return station
        elif user.role == UserRole.OPERATOR:
            enforce_operator_scope(user, station.operator_id)
            return station
        elif user.role == UserRole.DRIVER:
            if not StationModerationService.is_station_visible_to_drivers(station):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Station not found or pending administrative approval (REQ-F2-03).",
                )
            return station
        else:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied.",
            )

    @staticmethod
    def update_station(
        db: Session,
        user: User,
        station_id: int,
        data: StationUpdateRequest,
        ip_address: str | None = None,
    ) -> Station:
        """
        Updates station details with operator scoping (REQ-F1-12, REQ-F2-01).
        Editing details resets status to 'pending' per REQ-F2-03.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        enforce_operator_scope(user, station.operator_id)

        update_dict = data.model_dump(exclude_unset=True)
        if not update_dict:
            return station

        # Enforce validation rules per REQ-F2-04 on modified fields
        enforce_station_values(update_dict, partial=True)

        content_changed = False
        for field, value in update_dict.items():
            if field == "is_active":
                station.is_active = value
                if not value:
                    station.status = StationStatus.INACTIVE
            else:
                setattr(station, field, value)
                content_changed = True

        # Per REQ-F2-03: keep edited station hidden from drivers until an Administrator approves it
        if content_changed and station.is_active:
            station.status = StationStatus.PENDING

        db.commit()
        db.refresh(station)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="STATION_UPDATED",
            resource=f"Station:{station.id}",
            details=f"Station '{station.name}' updated by user {user.id}",
            ip_address=ip_address,
        )

        return station

    @staticmethod
    def deactivate_station(
        db: Session,
        user: User,
        station_id: int,
        ip_address: str | None = None,
    ) -> Station:
        """
        Deactivates a station (REQ-F2-01 / CS19-027).
        Marks is_active=False and status=INACTIVE.
        """
        station = db.query(Station).filter(Station.id == station_id).first()
        if not station:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Station with ID {station_id} not found.",
            )

        enforce_operator_scope(user, station.operator_id)

        station.is_active = False
        station.status = StationStatus.INACTIVE
        db.commit()
        db.refresh(station)

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="STATION_DEACTIVATED",
            resource=f"Station:{station.id}",
            details=f"Station '{station.name}' deactivated by user {user.id}",
            ip_address=ip_address,
        )

        return station

    @staticmethod
    def get_validation_rules() -> dict:
        """
        Returns Appendix B.4 validation constraints for stations and chargers.
        """
        return get_station_validation_rules()

    @staticmethod
    def validate_station_payload(data: dict, partial: bool = False) -> tuple[bool, dict[str, str]]:
        """
        Validates station fields without database modification (dry-run check).
        """
        return validate_station_values(data, partial=partial)

    @staticmethod
    def validate_charger_payload(data: dict, partial: bool = False) -> tuple[bool, dict[str, str]]:
        """
        Validates charger and connector fields without database modification (dry-run check).
        """
        return validate_charger_values(data, partial=partial)

    @staticmethod
    def approve_station(
        db: Session,
        admin: User,
        station_id: int,
        ip_address: str | None = None,
    ) -> Station:
        """
        Approves a station by Administrator (REQ-F2-03 / CS19-029).
        """
        return StationModerationService.approve_station(
            db=db, admin=admin, station_id=station_id, ip_address=ip_address
        )

    @staticmethod
    def reject_station(
        db: Session,
        admin: User,
        station_id: int,
        reason: str,
        ip_address: str | None = None,
    ) -> Station:
        """
        Rejects a station by Administrator with reason (REQ-F2-03 / CS19-029).
        """
        return StationModerationService.reject_station(
            db=db, admin=admin, station_id=station_id, reason=reason, ip_address=ip_address
        )

    @staticmethod
    def list_pending_stations(
        db: Session,
        admin: User,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Station], int]:
        """
        Lists pending stations for moderation review (REQ-F2-03 / CS19-029).
        """
        return StationModerationService.list_pending_stations(
            db=db, admin=admin, page=page, page_size=page_size
        )

    @staticmethod
    def get_approval_gate_status(
        db: Session,
        user: User,
        station_id: int,
    ) -> dict:
        """
        Gets approval gate status (REQ-F2-03 / CS19-029).
        """
        return StationModerationService.get_approval_gate_status(
            db=db, user=user, station_id=station_id
        )

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
        Processes an approval gate action (approve or reject) (REQ-F2-03 / CS19-029).
        """
        return StationModerationService.process_gate_action(
            db=db, admin=admin, station_id=station_id, action=action, reason=reason, ip_address=ip_address
        )

