from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.permissions import enforce_driver_scope, scope_driver_query
from app.models.user import User, UserRole
from app.models.vehicle import Vehicle, ConnectorType
from app.models.booking import Booking, BookingStatus
from app.schemas.user import DriverDataScopeResponse
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
    SetDefaultVehicleRequest,
    VehicleLimitAndDefaultResponse,
    SetDefaultVehicleResponse,
    EVPresetModelResponse,
    EVPresetListResponse,
    ApplyPresetRequest,
    ApplyPresetResponse,
    ActiveBookingInfo,
    ProtectBookedVehicleRequest,
    ProtectBookedVehicleResponse,
)
from app.services.audit_service import AuditService
from app.vehicles.presets import (
    get_preset_models,
    get_preset_by_id,
    prefill_vehicle_specs,
)
from app.vehicles.validators import (
    validate_vehicle_values,
    enforce_vehicle_values,
    get_appendix_b_rules,
)


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

        # Enforce Appendix B.3 validation ranges (REQ-F1-24 / CS19-024)
        enforce_vehicle_values(data.model_dump())

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
        query = db.query(Vehicle)
        query = scope_driver_query(query=query, model=Vehicle, current_user=user)
        vehicles = query.order_by(Vehicle.is_default.desc(), Vehicle.created_at.desc()).all()
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
        enforce_driver_scope(current_user=user, resource_user_id=vehicle.user_id)
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
                total_vehicles = db.query(Vehicle).filter(Vehicle.user_id == user.id).count()
                if total_vehicles <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="A driver must have exactly one default vehicle (REQ-F1-22). Cannot unset default on your only vehicle.",
                    )
                # Reassign default to another vehicle
                other_veh = db.query(Vehicle).filter(Vehicle.user_id == user.id, Vehicle.id != vehicle.id).first()
                if other_veh:
                    other_veh.is_default = True
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
    def check_vehicle_booking_protection(
        db: Session,
        vehicle_id: int,
    ) -> tuple[bool, list[Booking]]:
        """
        Checks whether a vehicle is linked to any upcoming or active bookings (REQ-F1-25 / CS19-025).
        Active/upcoming bookings have status in {HELD, CONFIRMED, ACTIVE}.
        """
        active_statuses = [
            BookingStatus.HELD,
            BookingStatus.CONFIRMED,
            BookingStatus.ACTIVE,
        ]
        bookings = (
            db.query(Booking)
            .filter(
                Booking.vehicle_id == vehicle_id,
                Booking.status.in_(active_statuses),
            )
            .order_by(Booking.start_time.asc())
            .all()
        )
        is_protected = len(bookings) > 0
        return is_protected, bookings

    @staticmethod
    def get_booking_protection_status(
        db: Session,
        vehicle_id: int,
        user: User,
    ) -> ProtectBookedVehicleResponse:
        """
        Inspect whether a vehicle is protected from deletion due to active or upcoming bookings (REQ-F1-25 / CS19-025).
        """
        vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)
        is_protected, active_bookings = VehicleService.check_vehicle_booking_protection(db=db, vehicle_id=vehicle.id)
        booking_infos = [
            ActiveBookingInfo(
                id=b.id,
                status=b.status.value if hasattr(b.status, "value") else str(b.status),
                start_time=b.start_time,
                end_time=b.end_time,
            )
            for b in active_bookings
        ]
        message = (
            f"Vehicle '{vehicle.make} {vehicle.model}' is protected from deletion: {len(active_bookings)} active/upcoming booking(s) exist (REQ-F1-25)."
            if is_protected
            else f"Vehicle '{vehicle.make} {vehicle.model}' has no active bookings and can be safely removed."
        )
        return ProtectBookedVehicleResponse(
            vehicle_id=vehicle.id,
            is_protected=is_protected,
            can_delete=not is_protected,
            active_booking_count=len(active_bookings),
            active_bookings=booking_infos,
            message=message,
        )

    @staticmethod
    def remove_vehicle(
        db: Session,
        vehicle_id: int,
        user: User,
        ip_address: str | None = None,
    ) -> VehicleDeleteResponse:
        """
        Remove/delete a vehicle owned by the authenticated driver (CS19-021 / REQ-F1-21).
        Enforces driver ownership (REQ-F1-26), prevents deleting booked vehicles (REQ-F1-25),
        handles fallback default assignment (REQ-F1-22), and logs audit events.
        """
        vehicle = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)

        # Protect booked vehicle (REQ-F1-25 / CS19-025)
        is_protected, active_bookings = VehicleService.check_vehicle_booking_protection(db=db, vehicle_id=vehicle.id)
        if is_protected:
            booking = active_bookings[0]
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot delete vehicle: It is linked to an active or upcoming booking (Booking #{booking.id}, status: '{booking.status.value}') (REQ-F1-25).",
            )

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
    def get_limit_and_default(db: Session, user: User) -> VehicleLimitAndDefaultResponse:
        """
        Get vehicle quota limits and current default vehicle status for the driver (CS19-022 / REQ-F1-22).
        Guarantees that if vehicles exist, exactly one is marked as default.
        """
        count = db.query(Vehicle).filter(Vehicle.user_id == user.id).count()
        default_veh = db.query(Vehicle).filter(Vehicle.user_id == user.id, Vehicle.is_default == True).first()

        # Enforce exactly one default vehicle if vehicles exist but none is default
        if count > 0 and not default_veh:
            default_veh = (
                db.query(Vehicle)
                .filter(Vehicle.user_id == user.id)
                .order_by(Vehicle.created_at.desc())
                .first()
            )
            if default_veh:
                default_veh.is_default = True
                db.commit()
                db.refresh(default_veh)

        can_add = count < VehicleService.MAX_VEHICLES_PER_DRIVER
        message = (
            f"You have {count} of {VehicleService.MAX_VEHICLES_PER_DRIVER} maximum vehicles."
            if can_add
            else f"Vehicle limit reached ({VehicleService.MAX_VEHICLES_PER_DRIVER}/{VehicleService.MAX_VEHICLES_PER_DRIVER})."
        )

        return VehicleLimitAndDefaultResponse(
            max_vehicles_allowed=VehicleService.MAX_VEHICLES_PER_DRIVER,
            current_vehicle_count=count,
            can_add_more=can_add,
            default_vehicle_id=default_veh.id if default_veh else None,
            default_vehicle=VehicleResponse.model_validate(default_veh) if default_veh else None,
            message=message,
        )

    @staticmethod
    def set_default_vehicle(
        db: Session,
        vehicle_id: int,
        user: User,
        ip_address: str | None = None,
    ) -> SetDefaultVehicleResponse:
        """
        Set a specific vehicle as the driver's primary default vehicle (CS19-022 / REQ-F1-22).
        Unsets all other defaults ensuring exactly one default vehicle exists.
        """
        target_veh = VehicleService.get_vehicle_by_id(db=db, vehicle_id=vehicle_id, user=user)

        if not target_veh.is_default:
            # Unset all other defaults for this driver
            db.query(Vehicle).filter(Vehicle.user_id == user.id, Vehicle.id != target_veh.id).update({"is_default": False})
            target_veh.is_default = True

            AuditService.log_action(
                db=db,
                user_id=user.id,
                action="VEHICLE_DEFAULT_SET",
                resource=f"vehicle:{target_veh.id}",
                details=f"Set {target_veh.make} {target_veh.model} as default vehicle (REQ-F1-22)",
                ip_address=ip_address,
                commit=False,
            )
            db.commit()
            db.refresh(target_veh)

        return SetDefaultVehicleResponse(
            success=True,
            message=f"Vehicle '{target_veh.make} {target_veh.model}' is now your default vehicle.",
            default_vehicle=VehicleResponse.model_validate(target_veh),
        )

    @staticmethod
    def get_validation_rules() -> VehicleValidationRulesResponse:
        """
        Returns metadata validation rules for EV vehicles (REQ-F1-19 / REQ-F1-24 / Appendix B.3).
        """
        rules = get_appendix_b_rules()
        return VehicleValidationRulesResponse(rules=rules, status="success")

    @staticmethod
    def validate_vehicle_inputs(payload: VehicleValidationCheckRequest) -> VehicleValidationCheckResponse:
        """
        Validate vehicle field values dynamically returning inline feedback (CS19-019 / REQ-F1-19 / REQ-F1-24).
        """
        data = payload.model_dump(exclude_unset=True)
        is_valid, errors = validate_vehicle_values(data)
        message = (
            "Vehicle validation successful. All fields are within valid ranges."
            if is_valid
            else "Vehicle validation failed with field errors."
        )
        return VehicleValidationCheckResponse(
            is_valid=is_valid,
            errors=errors,
            message=message,
        )

    # ==========================================================================
    # Preset EV Models Catalog (CS19-023 / REQ-F1-23 / vehicles/presets.py)
    # ==========================================================================

    @staticmethod
    def list_presets(
        make: str | None = None,
        connector_type: str | None = None,
    ) -> EVPresetListResponse:
        """
        Returns the catalog of common preset EV models with pre-filled specs (REQ-F1-23).
        """
        presets = get_preset_models(make=make, connector_type=connector_type)
        items = [EVPresetModelResponse.model_validate(p) for p in presets]
        return EVPresetListResponse(
            total=len(items),
            items=items,
        )

    @staticmethod
    def get_preset(preset_id: str) -> EVPresetModelResponse:
        """
        Fetch a single preset EV model by ID / slug (REQ-F1-23).
        """
        preset = get_preset_by_id(preset_id)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset EV model '{preset_id}' not found.",
            )
        return EVPresetModelResponse.model_validate(preset)

    @staticmethod
    def apply_preset(
        db: Session,
        user: User,
        data: ApplyPresetRequest,
        ip_address: str | None = None,
    ) -> ApplyPresetResponse:
        """
        Applies a preset EV model to pre-fill specification fields (REQ-F1-23).
        If data.create_vehicle is True, additionally persists the new vehicle to the driver's garage.
        """
        preset = get_preset_by_id(data.preset_id)
        if not preset:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Preset EV model '{data.preset_id}' not found.",
            )

        battery = data.custom_battery_kwh if data.custom_battery_kwh is not None else preset.battery_kwh
        ac_kw = data.custom_max_ac_kw if data.custom_max_ac_kw is not None else preset.max_ac_kw
        dc_kw = data.custom_max_dc_kw if data.custom_max_dc_kw is not None else preset.max_dc_kw
        consumption = data.custom_consumption_kwh_100km if data.custom_consumption_kwh_100km is not None else preset.consumption_kwh_100km

        spec = VehicleCreateRequest(
            make=preset.make,
            model=preset.model,
            battery_kwh=battery,
            connector_type=preset.connector_type,
            max_ac_kw=ac_kw,
            max_dc_kw=dc_kw,
            consumption_kwh_100km=consumption,
            registration_no=data.registration_no,
            is_default=data.is_default,
        )

        created_vehicle: VehicleResponse | None = None
        if data.create_vehicle:
            created_vehicle = VehicleService.add_vehicle(
                db=db,
                user=user,
                data=spec,
                ip_address=ip_address,
            )
            message = f"Vehicle '{preset.make} {preset.model}' successfully added to your garage from preset."
        else:
            message = f"Specifications pre-filled successfully for '{preset.make} {preset.model}'."

        return ApplyPresetResponse(
            preset_id=preset.id,
            prefilled_spec=spec,
            created_vehicle=created_vehicle,
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
        List summary cards for all vehicles of the authenticated driver (REQ-F1-20 / REQ-F1-26).
        """
        query = db.query(Vehicle)
        query = scope_driver_query(query=query, model=Vehicle, current_user=user)
        vehicles = query.order_by(Vehicle.is_default.desc(), Vehicle.created_at.desc()).all()
        cards = [VehicleService.build_summary_card(v) for v in vehicles]
        return VehicleSummaryCardListResponse(
            total=len(cards),
            items=cards,
        )

    # ==========================================================================
    # Driver Tenancy Isolation Scope (CS19-026 / REQ-F1-26)
    # ==========================================================================

    @staticmethod
    def get_driver_data_scope(
        db: Session,
        user: User,
        target_user_id: int | None = None,
    ) -> DriverDataScopeResponse:
        """
        Verify that a driver can view only their own profile and vehicles (REQ-F1-26 / CS19-026).
        Denies access with HTTP 403 Forbidden if a driver attempts to inspect another user's scope.
        """
        if target_user_id is not None and target_user_id != user.id:
            enforce_driver_scope(current_user=user, resource_user_id=target_user_id)

        vehicles = db.query(Vehicle).filter(Vehicle.user_id == user.id).all()
        vehicle_ids = [v.id for v in vehicles]

        return DriverDataScopeResponse(
            user_id=user.id,
            role=user.role.value if hasattr(user.role, "value") else str(user.role),
            email=user.email,
            accessible_vehicle_ids=vehicle_ids,
            total_vehicles=len(vehicle_ids),
            tenancy_status="isolated",
            message="Driver data isolation verified: only own profile and vehicles accessible (REQ-F1-26).",
        )
