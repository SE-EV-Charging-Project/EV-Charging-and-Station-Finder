"""
Booking Service (Feature 3: Battery-Aware Booking and Auto-Booking / CS19-055 / REQ-F3-01).
Orchestrates booking workflows, starting with battery level input and estimation.
"""

from typing import Any
from sqlalchemy.orm import Session

from app.booking.battery import (
    enter_battery_level as domain_enter_battery_level,
    get_vehicle_battery as domain_get_vehicle_battery,
    compute_usable_range as domain_compute_usable_range,
    compute_estimated_range as domain_compute_estimated_range,
    compute_energy_required as domain_compute_energy_required,
)
from app.booking.validators import get_battery_rules as domain_get_battery_rules
from app.models.user import User
from app.schemas.booking import BatteryLevelResponse


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
