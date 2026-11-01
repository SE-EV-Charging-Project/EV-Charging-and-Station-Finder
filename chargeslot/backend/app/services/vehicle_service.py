from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.schemas.vehicle import (
    VehicleCreateRequest,
    VehicleUpdateRequest,
    VehicleResponse,
    VehicleListResponse,
    VehicleDeleteResponse,
    VehicleValidationRulesResponse,
    VehicleValidationCheckRequest,
    VehicleValidationCheckResponse,
    VehicleSummaryCardResponse,
    VehicleSummaryCardListResponse,
)
from app.services.audit_service import AuditService


class VehicleService:
    """
    Service handling EV Vehicle Management, Validation, and Summary Cards
    (CS19-018 / CS19-019 / CS19-020 / REQ-F1-18 / REQ-F1-19 / REQ-F1-20 / Appendix B.1, B.3).
    """

    MAX_VEHICLES_PER_DRIVER = 5

    CONNECTOR_ICON_MAP = {
        ConnectorType.CCS2: "icon-ccs2",
        ConnectorType.CHADEMO: "icon-chademo",
        ConnectorType.TYPE_2: "icon-type2",
        ConnectorType.GBT: "icon-gbt",
    }

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
        if user.role not in [UserRole.DRIVER, UserRole.ADMIN]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only drivers and administrators can register vehicles.",
            )

        current_count = db.query(Vehicle).filter(Vehicle.user_id == user.id).count()
        if current_count >= VehicleService.MAX_VEHICLES_PER_DRIVER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Driver has reached maximum limit of {VehicleService.MAX_VEHICLES_PER_DRIVER} vehicles (REQ-F1-22).",
            )

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
    def get_vehicle_by_id(db: Session, vehicle_id: int, user: User) -> Vehicle:
        """
        Retrieve raw vehicle model by ID, ensuring ownership scoping (REQ-F1-26).
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
        return vehicle

    @staticmethod
    def update_vehicle(
        db: Session,
        vehicle_id: int,
        user: User,
        data: VehicleUpdateRequest,
        ip_address: str | None = None,
    ) -> VehicleResponse:
        """
        Update specifications or details of an existing vehicle (CS19-021 / REQ-F1-21).
        Enforces driver ownership, validates bounds, handles default reassignment, and logs audit events.
        """
        vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)
        changes: list[str] = []

        if data.make is not None:
            trimmed_make = data.make.strip()
            if not trimmed_make:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Vehicle make cannot be empty or whitespace.",
                )
            if vehicle.make != trimmed_make:
                changes.append(f"make: '{vehicle.make}' -> '{trimmed_make}'")
                vehicle.make = trimmed_make

        if data.model is not None:
            trimmed_model = data.model.strip()
            if not trimmed_model:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Vehicle model cannot be empty or whitespace.",
                )
            if vehicle.model != trimmed_model:
                changes.append(f"model: '{vehicle.model}' -> '{trimmed_model}'")
                vehicle.model = trimmed_model

        if data.battery_kwh is not None:
            if data.battery_kwh < 5.0 or data.battery_kwh > 250.0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Battery capacity must be between 5.0 and 250.0 kWh (Appendix B.3).",
                )
            if vehicle.battery_kwh != data.battery_kwh:
                changes.append(f"battery_kwh: {vehicle.battery_kwh} -> {data.battery_kwh}")
                vehicle.battery_kwh = data.battery_kwh

        if data.connector_type is not None:
            if vehicle.connector_type != data.connector_type:
                changes.append(f"connector_type: '{vehicle.connector_type.value}' -> '{data.connector_type.value}'")
                vehicle.connector_type = data.connector_type

        if data.max_ac_kw is not None:
            if data.max_ac_kw < 1.0 or data.max_ac_kw > 50.0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Maximum AC charging rate must be between 1.0 and 50.0 kW (Appendix B.3).",
                )
            if vehicle.max_ac_kw != data.max_ac_kw:
                changes.append(f"max_ac_kw: {vehicle.max_ac_kw} -> {data.max_ac_kw}")
                vehicle.max_ac_kw = data.max_ac_kw

        if data.max_dc_kw is not None:
            if data.max_dc_kw < 0.0 or (0.0 < data.max_dc_kw < 10.0) or data.max_dc_kw > 400.0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Maximum DC charging rate must be 0 kW (unsupported) or between 10.0 and 400.0 kW (Appendix B.3).",
                )
            if vehicle.max_dc_kw != data.max_dc_kw:
                changes.append(f"max_dc_kw: {vehicle.max_dc_kw} -> {data.max_dc_kw}")
                vehicle.max_dc_kw = data.max_dc_kw

        if data.consumption_kwh_100km is not None:
            if data.consumption_kwh_100km < 5.0 or data.consumption_kwh_100km > 50.0:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Energy consumption must be between 5.0 and 50.0 kWh per 100 km (Appendix B.3).",
                )
            if vehicle.consumption_kwh_100km != data.consumption_kwh_100km:
                changes.append(f"consumption: {vehicle.consumption_kwh_100km} -> {data.consumption_kwh_100km}")
                vehicle.consumption_kwh_100km = data.consumption_kwh_100km

        if data.registration_no is not None:
            trimmed_reg = data.registration_no.strip().upper() if data.registration_no else None
            if vehicle.registration_no != trimmed_reg:
                changes.append(f"registration_no: '{vehicle.registration_no}' -> '{trimmed_reg}'")
                vehicle.registration_no = trimmed_reg

        if data.is_default is not None:
            if data.is_default is True and not vehicle.is_default:
                # Unset existing default vehicle for this user
                db.query(Vehicle).filter(Vehicle.user_id == user.id, Vehicle.id != vehicle.id).update({"is_default": False})
                vehicle.is_default = True
                changes.append("is_default: False -> True")
            elif data.is_default is False and vehicle.is_default:
                vehicle.is_default = False
                changes.append("is_default: True -> False")

        if changes:
            AuditService.log_action(
                db=db,
                user_id=user.id,
                action="VEHICLE_UPDATED",
                resource=f"vehicle:{vehicle.id}",
                details=f"Updated vehicle {vehicle.make} {vehicle.model}: {'; '.join(changes)}",
                ip_address=ip_address,
                commit=False,
            )

        db.commit()
        db.refresh(vehicle)
        return VehicleResponse.model_validate(vehicle)

    @staticmethod
    def remove_vehicle(
        db: Session,
        vehicle_id: int,
        user: User,
        ip_address: str | None = None,
    ) -> VehicleDeleteResponse:
        """
        Remove/delete a vehicle owned by the authenticated driver (CS19-021 / REQ-F1-21).
        Enforces driver ownership, handles fallback default assignment, and logs audit events.
        """
        vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)
        was_default = vehicle.is_default
        veh_info = f"{vehicle.make} {vehicle.model} (ID: {vehicle.id})"

        db.delete(vehicle)
        db.flush()

        # If deleted vehicle was default, set the most recent remaining vehicle as default
        if was_default:
            remaining = (
                db.query(Vehicle)
                .filter(Vehicle.user_id == user.id)
                .order_by(Vehicle.created_at.desc())
                .first()
            )
            if remaining:
                remaining.is_default = True

        AuditService.log_action(
            db=db,
            user_id=user.id,
            action="VEHICLE_DELETED",
            resource=f"vehicle:{vehicle_id}",
            details=f"Deleted vehicle {veh_info}",
            ip_address=ip_address,
            commit=False,
        )

        db.commit()
        return VehicleDeleteResponse(
            message=f"Vehicle '{veh_info}' has been successfully removed.",
            vehicle_id=vehicle_id,
            status="success",
        )

    @staticmethod
    def get_validation_rules() -> VehicleValidationRulesResponse:
        """
        Returns metadata validation rules for EV vehicles (REQ-F1-19 / REQ-F1-24 / Appendix B.3).
        """
        rules = {
            "make": {
                "required": True,
                "min_length": 1,
                "max_length": 40,
                "description": "Vehicle make/manufacturer; cannot be empty.",
            },
            "model": {
                "required": True,
                "min_length": 1,
                "max_length": 40,
                "description": "Vehicle model name; cannot be empty.",
            },
            "battery_kwh": {
                "required": True,
                "min": 5.0,
                "max": 250.0,
                "unit": "kWh",
                "description": "Usable battery capacity in kWh (5 to 250 kWh).",
            },
            "connector_type": {
                "required": True,
                "allowed_values": [ct.value for ct in ConnectorType],
                "description": "Standardized charging connector type.",
            },
            "max_ac_kw": {
                "required": True,
                "min": 1.0,
                "max": 50.0,
                "unit": "kW",
                "description": "Maximum onboard AC charging rate in kW (1 to 50 kW).",
            },
            "max_dc_kw": {
                "required": False,
                "default": 0.0,
                "min_if_supported": 10.0,
                "max": 400.0,
                "unit": "kW",
                "description": "Maximum DC fast charging rate in kW (0 if none, or 10 to 400 kW).",
            },
            "consumption_kwh_100km": {
                "required": True,
                "min": 5.0,
                "max": 50.0,
                "unit": "kWh/100km",
                "description": "Vehicle energy consumption in kWh per 100 km (5 to 50 kWh/100km).",
            },
            "registration_no": {
                "required": False,
                "max_length": 15,
                "description": "Vehicle registration or license plate number.",
            },
            "max_vehicles_per_driver": {
                "max": VehicleService.MAX_VEHICLES_PER_DRIVER,
                "description": "Maximum vehicles allowed per driver (REQ-F1-22).",
            },
        }
        return VehicleValidationRulesResponse(rules=rules, status="success")

    @staticmethod
    def validate_vehicle_inputs(payload: VehicleValidationCheckRequest) -> VehicleValidationCheckResponse:
        """
        Validate vehicle field values dynamically returning inline feedback (CS19-019 / REQ-F1-19).
        """
        errors: dict[str, str] = {}

        if payload.make is not None:
            trimmed_make = payload.make.strip()
            if not trimmed_make:
                errors["make"] = "Vehicle make cannot be empty or blank."
            elif len(trimmed_make) > 40:
                errors["make"] = "Vehicle make cannot exceed 40 characters."

        if payload.model is not None:
            trimmed_model = payload.model.strip()
            if not trimmed_model:
                errors["model"] = "Vehicle model cannot be empty or blank."
            elif len(trimmed_model) > 40:
                errors["model"] = "Vehicle model cannot exceed 40 characters."

        if payload.battery_kwh is not None:
            if payload.battery_kwh < 5.0 or payload.battery_kwh > 250.0:
                errors["battery_kwh"] = "Battery capacity must be between 5.0 and 250.0 kWh (Appendix B.3)."

        if payload.connector_type is not None:
            allowed = [ct.value for ct in ConnectorType]
            if payload.connector_type not in allowed:
                errors["connector_type"] = f"Invalid connector type. Allowed types: {', '.join(allowed)}."

        if payload.max_ac_kw is not None:
            if payload.max_ac_kw < 1.0 or payload.max_ac_kw > 50.0:
                errors["max_ac_kw"] = "Maximum AC charging rate must be between 1.0 and 50.0 kW (Appendix B.3)."

        if payload.max_dc_kw is not None:
            if payload.max_dc_kw < 0.0 or (0.0 < payload.max_dc_kw < 10.0) or payload.max_dc_kw > 400.0:
                errors["max_dc_kw"] = "Maximum DC charging rate must be 0 kW (unsupported) or between 10.0 and 400.0 kW (Appendix B.3)."

        if payload.consumption_kwh_100km is not None:
            if payload.consumption_kwh_100km < 5.0 or payload.consumption_kwh_100km > 50.0:
                errors["consumption_kwh_100km"] = "Energy consumption must be between 5.0 and 50.0 kWh per 100 km (Appendix B.3)."

        if payload.registration_no is not None:
            trimmed_reg = payload.registration_no.strip()
            if len(trimmed_reg) > 15:
                errors["registration_no"] = "Registration number cannot exceed 15 characters."

        is_valid = len(errors) == 0
        message = "Vehicle validation successful. All fields are within valid ranges." if is_valid else "Vehicle validation failed with field errors."

        return VehicleValidationCheckResponse(
            is_valid=is_valid,
            errors=errors,
            message=message,
        )

    @staticmethod
    def build_summary_card(vehicle: Vehicle) -> VehicleSummaryCardResponse:
        """
        Build a vehicle summary card representation with compatibility badges and icons (CS19-020 / REQ-F1-20).
        """
        connector_icon = VehicleService.CONNECTOR_ICON_MAP.get(vehicle.connector_type, "icon-ev")
        has_dc = vehicle.max_dc_kw > 0.0
        current_type = "AC/DC" if has_dc else "AC Only"
        fast_charging = vehicle.max_dc_kw >= 50.0

        # Calculations from Appendix B.1
        # Usable range = (100 - reserve) / 100 * battery_kwh / (consumption / 100), where reserve = 10%
        factor_100 = vehicle.consumption_kwh_100km / 100.0
        estimated_range = round(vehicle.battery_kwh / factor_100, 1)
        usable_range = round(((100.0 - 10.0) / 100.0 * vehicle.battery_kwh) / factor_100, 1)

        # Compatibility badges
        badges = [
            f"{vehicle.connector_type.value} Connector",
            f"AC {vehicle.max_ac_kw:.1f} kW",
        ]
        if has_dc:
            badges.append(f"DC Fast Charging ({vehicle.max_dc_kw:.0f} kW)")
        else:
            badges.append("AC Charging Only")

        if vehicle.battery_kwh >= 60.0:
            badges.append("Long Range")

        if vehicle.is_default:
            badges.append("Default Vehicle")

        return VehicleSummaryCardResponse(
            vehicle_id=vehicle.id,
            user_id=vehicle.user_id,
            make=vehicle.make,
            model=vehicle.model,
            display_title=f"{vehicle.make} {vehicle.model}",
            registration_no=vehicle.registration_no,
            is_default=vehicle.is_default,
            battery_kwh=vehicle.battery_kwh,
            connector_type=vehicle.connector_type,
            connector_icon=connector_icon,
            current_type=current_type,
            max_ac_kw=vehicle.max_ac_kw,
            max_dc_kw=vehicle.max_dc_kw,
            fast_charging_support=has_dc,
            consumption_kwh_100km=vehicle.consumption_kwh_100km,
            estimated_range_km=estimated_range,
            usable_range_km=usable_range,
            compatibility_badges=badges,
        )

    @staticmethod
    def get_vehicle_summary(db: Session, vehicle_id: int, user: User) -> VehicleSummaryCardResponse:
        """
        Get vehicle summary card by vehicle ID (REQ-F1-20).
        """
        vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)
        return VehicleService.build_summary_card(vehicle)

    @staticmethod
    def list_vehicle_summaries(db: Session, user: User) -> VehicleSummaryCardListResponse:
        """
        List summary cards for all vehicles of the authenticated driver (REQ-F1-20).
        """
        vehicles = db.query(Vehicle).filter(Vehicle.user_id == user.id).order_by(Vehicle.is_default.desc(), Vehicle.created_at.desc()).all()
        cards = [VehicleService.build_summary_card(v) for v in vehicles]
        return VehicleSummaryCardListResponse(
            total=len(cards),
            items=cards,
        )
