"""
Booking Service (Feature 3: Battery-Aware Booking and Auto-Booking / CS19-055 / REQ-F3-01).
Orchestrates booking workflows, starting with battery level input and estimation.
"""

from datetime import date, datetime
from typing import Any
from sqlalchemy.orm import Session

from app.booking.battery import (
    enter_battery_level as domain_enter_battery_level,
    get_vehicle_battery as domain_get_vehicle_battery,
    compute_usable_range as domain_compute_usable_range,
    compute_estimated_range as domain_compute_estimated_range,
    compute_energy_required as domain_compute_energy_required,
    estimate_charging_time as domain_estimate_charging_time,
    estimate_charging_cost as domain_estimate_charging_cost,
)
from app.booking.validators import get_battery_rules as domain_get_battery_rules
from app.booking.slots import (
    create_manual_slot_booking as domain_create_manual_slot_booking,
    create_slot_hold as domain_create_slot_hold,
    modify_confirmed_booking as domain_modify_confirmed_booking,
    cancel_booking as domain_cancel_booking,
    recommend_slots as domain_recommend_slots,
)
from app.models.user import User
from app.schemas.booking import (
    BatteryLevelResponse,
    BookingCancellationResponse,
    BookingModificationResponse,
    ChargingCostEstimateResponse,
    ChargingTimeEstimateResponse,
    ManualSlotBookingResponse,
    RecommendedSlotsResponse,
    SlotHoldResponse,
)


class BookingService:
    """
    Domain service for Booking and Battery Estimation operations (REQ-F3-01 / CS19-055).
    """

    @staticmethod
    def set_battery_level(
        db: Session,
        user: User,
        battery_level: int,
        vehicle_id: int | None = None,
        target_soc: int | None = None,
        ip_address: str | None = None,
    ) -> BatteryLevelResponse:
        """
        Record and update driver's vehicle battery level (REQ-F3-01 / CS19-055).
        """
        return domain_enter_battery_level(
            db=db,
            user=user,
            vehicle_id=vehicle_id,
            battery_level=battery_level,
            target_soc=target_soc,
            ip_address=ip_address,
        )

    @staticmethod
    def get_battery_level(
        db: Session,
        user: User,
        vehicle_id: int | None = None,
    ) -> BatteryLevelResponse:
        """
        Retrieve driver's current vehicle battery level and driving range estimates (REQ-F3-01 / CS19-055).
        """
        return domain_get_vehicle_battery(
            db=db,
            user=user,
            vehicle_id=vehicle_id,
        )

    @staticmethod
    def get_battery_rules() -> dict[str, Any]:
        """
        Retrieve Appendix B battery and range calculation rules.
        """
        return domain_get_battery_rules()

    @staticmethod
    def calculate_usable_range(
        battery_kwh: float,
        consumption_kwh_100km: float,
        current_soc: int,
        reserve: int = 10,
    ) -> float:
        """
        Calculate usable range in km from battery specs and current SoC.
        """
        return domain_compute_usable_range(
            battery_kwh=battery_kwh,
            consumption_kwh_100km=consumption_kwh_100km,
            current_soc=current_soc,
            reserve=reserve,
        )

    @staticmethod
    def calculate_energy_required(
        battery_kwh: float,
        current_soc: int,
        target_soc: int = 80,
    ) -> float:
        """
        Calculate energy required in kWh to charge from current to target SoC.
        """
        return domain_compute_energy_required(
            battery_kwh=battery_kwh,
            current_soc=current_soc,
            target_soc=target_soc,
        )

    @staticmethod
    def estimate_charging_time(
        db: Session,
        user: User,
        vehicle_id: int,
        charger_id: int,
        target_soc: int = 80,
    ) -> ChargingTimeEstimateResponse:
        """Estimate charging time for one of the driver's vehicles."""
        return domain_estimate_charging_time(
            db=db,
            user=user,
            vehicle_id=vehicle_id,
            charger_id=charger_id,
            target_soc=target_soc,
        )

    @staticmethod
    def estimate_charging_cost(
        db: Session,
        user: User,
        vehicle_id: int,
        station_id: int,
        target_soc: int = 80,
    ) -> ChargingCostEstimateResponse:
        """Estimate charging cost using the selected station's tariff."""
        return domain_estimate_charging_cost(
            db=db,
            user=user,
            vehicle_id=vehicle_id,
            station_id=station_id,
            target_soc=target_soc,
        )

    @staticmethod
    def recommend_slots(
        db: Session,
        user: User,
        vehicle_id: int,
        slot_date: date,
        target_soc: int = 80,
        station_id: int | None = None,
        limit: int = 50,
    ) -> RecommendedSlotsResponse:
        """Return free compatible slots ranked by time, tariff, then duration."""
        return domain_recommend_slots(
            db=db,
            user=user,
            vehicle_id=vehicle_id,
            slot_date=slot_date,
            target_soc=target_soc,
            station_id=station_id,
            limit=limit,
        )

    @staticmethod
    def create_manual_slot_booking(
        db: Session,
        user: User,
        station_id: int,
        vehicle_id: int,
        charger_id: int,
        start_time: datetime,
        target_soc: int = 80,
        ip_address: str | None = None,
    ) -> ManualSlotBookingResponse:
        """Create a booking after revalidating the selected slot's availability."""
        return domain_create_manual_slot_booking(
            db=db,
            user=user,
            station_id=station_id,
            vehicle_id=vehicle_id,
            charger_id=charger_id,
            start_time=start_time,
            target_soc=target_soc,
            ip_address=ip_address,
        )

    @staticmethod
    def create_slot_hold(
        db: Session,
        user: User,
        station_id: int,
        vehicle_id: int,
        charger_id: int,
        start_time: datetime,
        target_soc: int = 80,
        ip_address: str | None = None,
    ) -> SlotHoldResponse:
        """Temporarily reserve a selected slot for five minutes."""
        return domain_create_slot_hold(
            db=db,
            user=user,
            station_id=station_id,
            vehicle_id=vehicle_id,
            charger_id=charger_id,
            start_time=start_time,
            target_soc=target_soc,
            ip_address=ip_address,
        )

    @staticmethod
    def modify_confirmed_booking(
        db: Session,
        user: User,
        booking_id: int,
        charger_id: int,
        start_time: datetime,
        ip_address: str | None = None,
    ) -> BookingModificationResponse:
        """Move an owned confirmed booking to a compatible available slot."""
        return domain_modify_confirmed_booking(
            db=db,
            user=user,
            booking_id=booking_id,
            charger_id=charger_id,
            start_time=start_time,
            ip_address=ip_address,
        )

    @staticmethod
    def cancel_booking(
        db: Session,
        user: User,
        booking_id: int,
        ip_address: str | None = None,
    ) -> BookingCancellationResponse:
        """Cancel an owned booking and record any applicable late fee."""
        return domain_cancel_booking(
            db=db,
            user=user,
            booking_id=booking_id,
            ip_address=ip_address,
        )
