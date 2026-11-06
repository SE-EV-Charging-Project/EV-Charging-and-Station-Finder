from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict, model_validator


class MaintenanceWindowCreateRequest(BaseModel):
    """
    Payload for defining a maintenance window for a station or charger (REQ-F2-06).
    """
    charger_id: int | None = Field(
        default=None,
        description="Optional charger ID. If omitted, maintenance window applies to the entire station."
    )
    title: str = Field(..., min_length=3, max_length=100, description="Title/reason for maintenance window")
    description: str | None = Field(default=None, max_length=500, description="Optional detailed description")
    start_time: datetime = Field(..., description="Maintenance start timestamp")
    end_time: datetime = Field(..., description="Maintenance end timestamp")

    @model_validator(mode="after")
    def validate_time_range(self) -> "MaintenanceWindowCreateRequest":
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be strictly after start_time")
        return self


class MaintenanceWindowUpdateRequest(BaseModel):
    """
    Payload for updating an existing maintenance window (REQ-F2-06).
    """
    charger_id: int | None = None
    title: str | None = Field(default=None, min_length=3, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    start_time: datetime | None = None
    end_time: datetime | None = None

    @model_validator(mode="after")
    def validate_time_range(self) -> "MaintenanceWindowUpdateRequest":
        if self.start_time is not None and self.end_time is not None:
            if self.end_time <= self.start_time:
                raise ValueError("end_time must be strictly after start_time")
        return self


class MaintenanceWindowResponse(BaseModel):
    """
    Response schema representing a maintenance window.
    """
    id: int
    station_id: int
    charger_id: int | None
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime
    created_by_user_id: int | None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class MaintenanceWindowListResponse(BaseModel):
    """
    Paginated/listed maintenance windows response.
    """
    total: int
    items: list[MaintenanceWindowResponse]


class SlotItem(BaseModel):
    """
    Represents an individual time slot for availability checking (REQ-F2-06 / §5.2.4).
    """
    charger_id: int | None = None
    start_time: datetime
    end_time: datetime
    is_available: bool = True
    blocked_reason: str | None = None

    @model_validator(mode="after")
    def validate_slot_times(self) -> "SlotItem":
        if self.end_time <= self.start_time:
            raise ValueError("Slot end_time must be after start_time")
        return self


class SlotAvailabilityCheckRequest(BaseModel):
    """
    Payload to verify a list of candidate slots against active maintenance windows.
    """
    slots: list[SlotItem] = Field(..., description="Candidate slots to filter")


class SlotAvailabilityCheckResponse(BaseModel):
    """
    Response containing filtered available slots and removed slots (REQ-F2-06).
    """
    total_slots: int
    available_count: int
    removed_count: int
    available_slots: list[SlotItem]
    removed_slots: list[SlotItem]

