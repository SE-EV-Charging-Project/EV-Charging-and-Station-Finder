"""
Vehicles Module Package (HLD / SDD §Vehicles).
Contains presets and validators conforming to SRS REQ-F1-23, REQ-F1-24 and Appendix B.
"""

from app.vehicles.presets import (
    EV_PRESET_MODELS,
    EVModelPreset,
    get_preset_models,
    get_preset_by_id,
    prefill_vehicle_specs,
)
from app.vehicles.validators import (
    APPENDIX_B_VEHICLE_RULES,
    validate_vehicle_values,
    enforce_vehicle_values,
    get_appendix_b_rules,
)

__all__ = [
    "EV_PRESET_MODELS",
    "EVModelPreset",
    "get_preset_models",
    "get_preset_by_id",
    "prefill_vehicle_specs",
    "APPENDIX_B_VEHICLE_RULES",
    "validate_vehicle_values",
    "enforce_vehicle_values",
    "get_appendix_b_rules",
]
