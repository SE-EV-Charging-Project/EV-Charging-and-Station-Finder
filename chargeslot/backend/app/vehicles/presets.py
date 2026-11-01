"""
Preset EV Models Catalog (REQ-F1-23 / CS19-023 / vehicles/presets.py).
Provides a pre-defined catalog of common EV models in India and worldwide
that pre-fills vehicle specification fields for drivers.
All specifications strictly adhere to SRS Appendix B.3 field ranges.
"""

from typing import Any
from pydantic import BaseModel, ConfigDict
from app.models.vehicle import ConnectorType


class EVModelPreset(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    make: str
    model: str
    battery_kwh: float
    connector_type: ConnectorType
    max_ac_kw: float
    max_dc_kw: float
    consumption_kwh_100km: float
    description: str


EV_PRESET_MODELS: list[EVModelPreset] = [
    EVModelPreset(
        id="tata-nexon-ev-lr",
        make="Tata",
        model="Nexon EV Long Range",
        battery_kwh=40.5,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.0,
        description="India's best-selling compact electric SUV with 40.5 kWh battery and CCS2 fast charging.",
    ),
    EVModelPreset(
        id="tata-punch-ev-lr",
        make="Tata",
        model="Punch EV Long Range",
        battery_kwh=35.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=14.0,
        description="Compact urban EV with acti.ev architecture, 35 kWh battery and CCS2 support.",
    ),
    EVModelPreset(
        id="tata-tiago-ev",
        make="Tata",
        model="Tiago EV Long Range",
        battery_kwh=24.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=3.3,
        max_dc_kw=25.0,
        consumption_kwh_100km=12.0,
        description="Affordable urban hatchback featuring 24 kWh battery and CCS2 DC charging.",
    ),
    EVModelPreset(
        id="mg-zs-ev",
        make="MG",
        model="ZS EV Excite",
        battery_kwh=50.3,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.4,
        max_dc_kw=50.0,
        consumption_kwh_100km=16.5,
        description="Mid-size electric SUV with 50.3 kWh prismatic cell pack and CCS2 interface.",
    ),
    EVModelPreset(
        id="hyundai-ioniq-5",
        make="Hyundai",
        model="Ioniq 5 RWD",
        battery_kwh=72.6,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=11.0,
        max_dc_kw=350.0,
        consumption_kwh_100km=17.0,
        description="800V ultra-fast charging electric crossover with 72.6 kWh battery.",
    ),
    EVModelPreset(
        id="mahindra-xuv400",
        make="Mahindra",
        model="XUV400 EL Pro",
        battery_kwh=39.4,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.2,
        max_dc_kw=50.0,
        consumption_kwh_100km=15.5,
        description="All-electric SUV with 39.4 kWh battery capacity and 50 kW fast DC charging.",
    ),
    EVModelPreset(
        id="byd-atto-3",
        make="BYD",
        model="Atto 3 Superior",
        battery_kwh=60.48,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=7.0,
        max_dc_kw=80.0,
        consumption_kwh_100km=16.0,
        description="Blade battery powered crossover with 60.48 kWh capacity and 80 kW DC charging.",
    ),
    EVModelPreset(
        id="tesla-model-3",
        make="Tesla",
        model="Model 3 RWD",
        battery_kwh=60.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=11.0,
        max_dc_kw=170.0,
        consumption_kwh_100km=14.5,
        description="Efficient global sedan with 60 kWh LFP battery and high-speed CCS2 DC charging.",
    ),
    EVModelPreset(
        id="nissan-leaf",
        make="Nissan",
        model="Leaf e+",
        battery_kwh=40.0,
        connector_type=ConnectorType.CHADEMO,
        max_ac_kw=6.6,
        max_dc_kw=50.0,
        consumption_kwh_100km=17.0,
        description="Global pioneer hatchback equipped with 40 kWh battery and CHAdeMO fast connector.",
    ),
    EVModelPreset(
        id="kia-ev6",
        make="Kia",
        model="EV6 GT-Line AWD",
        battery_kwh=77.4,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=11.0,
        max_dc_kw=350.0,
        consumption_kwh_100km=16.5,
        description="Performance crossover with 77.4 kWh battery and 350 kW DC charging architecture.",
    ),
    EVModelPreset(
        id="bmw-i4",
        make="BMW",
        model="i4 eDrive40",
        battery_kwh=83.9,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=11.0,
        max_dc_kw=205.0,
        consumption_kwh_100km=18.0,
        description="Gran Coupe electric sedan with 83.9 kWh slim battery pack and 205 kW DC rate.",
    ),
    EVModelPreset(
        id="volvo-ex40",
        make="Volvo",
        model="EX40 Recharge Plus",
        battery_kwh=69.0,
        connector_type=ConnectorType.CCS2,
        max_ac_kw=11.0,
        max_dc_kw=130.0,
        consumption_kwh_100km=17.5,
        description="Compact luxury SUV with 69 kWh battery and 130 kW DC fast charging capabilities.",
    ),
]


def get_preset_models(
    make: str | None = None,
    connector_type: str | None = None,
) -> list[EVModelPreset]:
    """
    Returns a filtered or complete list of preset EV models (REQ-F1-23).
    """
    results = EV_PRESET_MODELS
    if make:
        m_lower = make.strip().lower()
        results = [p for p in results if p.make.lower() == m_lower]
    if connector_type:
        c_upper = connector_type.strip().upper()
        results = [p for p in results if p.connector_type.value.upper() == c_upper]
    return results


def get_preset_by_id(preset_id: str) -> EVModelPreset | None:
    """
    Look up an EV model preset by its slug/identifier.
    """
    target = preset_id.strip().lower()
    for preset in EV_PRESET_MODELS:
        if preset.id.lower() == target:
            return preset
    return None


def prefill_vehicle_specs(
    preset_id: str,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Pre-fills vehicle specification fields from a selected preset EV model,
    allowing driver overrides for customizable parameters (REQ-F1-23).
    """
    preset = get_preset_by_id(preset_id)
    if not preset:
        raise ValueError(f"Preset EV model '{preset_id}' not found.")

    specs: dict[str, Any] = {
        "make": preset.make,
        "model": preset.model,
        "battery_kwh": preset.battery_kwh,
        "connector_type": preset.connector_type.value,
        "max_ac_kw": preset.max_ac_kw,
        "max_dc_kw": preset.max_dc_kw,
        "consumption_kwh_100km": preset.consumption_kwh_100km,
        "registration_no": None,
        "is_default": False,
    }

    if overrides:
        for k, v in overrides.items():
            if v is not None and k in specs:
                specs[k] = v

    return specs
