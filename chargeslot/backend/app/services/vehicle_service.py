from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.vehicle import Vehicle
from app.schemas.vehicle import VehicleCreateRequest, VehicleResponse, VehicleListResponse
from app.services.audit_service import AuditService


class VehicleService:
    """
    Service handling EV Vehicle Management (CS19-018 / REQ-F1-18 / Appendix B.3).
    Allows drivers to add and manage electric vehicles with full charging & battery specifications.
    """

    MAX_VEHICLES_PER_DRIVER = 5

    @staticmethod
    def add_vehicle(
        db: Session,
        user: User,
        data: VehicleCreateRequest,
        ip_address: str | None = None,
    ) -> VehicleResponse:
        """
        Add a new electric vehicle for the authenticated driver (REQ-F1-18).
        Validates vehicle specs, enforces limits, sets defaults, and records audit logs.
        """
        # Ensure role authorization
        if user.role not in [UserRole.DRIVER, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only drivers and administrators can register vehicles.",
            )

        # Check vehicle count limit (REQ-F1-22 / CS19-022)
        current_count = db.query(Vehicle).filter(Vehicle.user_id == user.id).count()
        if current_count >= VehicleService.MAX_VEHICLES_PER_DRIVER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Driver has reached maximum limit of {VehicleService.MAX_VEHICLES_PER_DRIVER} vehicles (REQ-F1-22).",
            )

        # Handle default vehicle assignment
        is_default = data.is_default
        if current_count == 0:
            is_default = True
        elif is_default:
            db.query(Vehicle).filter(Vehicle.user_id == user.id).update({"is_default": False})

        vehicle = Vehicle(
            user_id=user.id,
            make=data.make,
            model=data.model,
            battery_kwh=data.battery_kwh,
            connector_type=data.connector_type,
            max_ac_kw=data.max_ac_kw,
            max_dc_kw=data.max_dc_kw,
            consumption_kwh_100km=data.consumption_kwh_100km,
            registration_no=data.registration_no,
            is_default=is_default,
        )
        db.add(vehicle)
        db.flush()

        # Audit log creation
        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="VEHICLE_ADDED",
            resource=f"vehicle:{vehicle.id}",
            details=f"Added vehicle {vehicle.make} {vehicle.model} ({vehicle.battery_kwh} kWh, {vehicle.connector_type.value})",
            ip_address=ip_address,
            commit=False,
        )

        db.commit()
        db.refresh(vehicle)
        return VehicleResponse.model_validate(vehicle)

    @staticmethod
    def list_vehicles(db: Session, user: User) -> VehicleListResponse:
        """
        List all vehicles owned by the authenticated driver (REQ-F1-26).
        """
        query = db.query(Vehicle).filter(Vehicle.user_id == user.id).order_by(Vehicle.is_default.desc(), Vehicle.created_at.desc())
        vehicles = query.all()
        return VehicleListResponse(
            total=len(vehicles),
            items=[VehicleResponse.model_validate(v) for v in vehicles],
        )

    @staticmethod
    def get_vehicle_by_id(db: Session, vehicle_id: int, user: User) -> VehicleResponse:
        """
        Retrieve a specific vehicle by ID, ensuring ownership scoping (REQ-F1-26).
        """
        vehicle = db.query(Vehicle).filter(Vehicle.id == vehicle_id).first()
        if not vehicle:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Vehicle with ID {vehicle_id} not found.",
            )
        if vehicle.user_id != user.id and user.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You do not have permission to access this vehicle (REQ-F1-26).",
            )
        return VehicleResponse.model_validate(vehicle)
