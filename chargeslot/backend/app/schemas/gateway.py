from datetime import datetime
from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class GatewayStatusIngestRequest(BaseModel):
    """
    Unified status ingestion request accepting ChargeSlot telemetry or OCPP 1.6J StatusNotification
    fields (REQ-F2-17 / CS19-043).
    """

    connector_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("connector_id", "connectorId"),
        description="ChargeSlot database connector ID (or 1-based port index when connector_index omitted and gateway_id supplied)",
    )
    gateway_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("gateway_id", "chargePointId", "charge_point_id"),
        max_length=100,
        description="OCPP / Charge Point gateway hardware identifier matching Charger.gateway_id",
    )
    connector_index: int | None = Field(
        default=None,
        validation_alias=AliasChoices("connector_index", "connectorIndex"),
        description="Optional 1-based physical port index on the charge point gateway",
    )
    status: str = Field(
        ...,
        validation_alias=AliasChoices("status", "state"),
        min_length=1,
        max_length=50,
        description="ChargeSlot status (Available, Occupied, Reserved, Faulted, Offline) or OCPP 1.6J status",
    )
    observed_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("observed_at", "timestamp"),
        description="UTC timestamp when the gateway observed the status change",
    )
    error_code: str | None = Field(
        default=None,
        validation_alias=AliasChoices("error_code", "errorCode"),
        max_length=50,
        description="Optional OCPP 1.6J errorCode (e.g. NoError, ConnectorLockFailure)",
    )
    idempotency_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("idempotency_key", "messageId", "message_id"),
        max_length=120,
        description="Optional idempotency / OCPP message ID for duplicate delivery protection",
    )

    model_config = ConfigDict(populate_by_name=True)


class GatewayMeterValueIngestRequest(BaseModel):
    """Normalized OCPP meter sample with power and cumulative imported energy."""

    connector_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("connector_id", "connectorId"),
        gt=0,
    )
    gateway_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("gateway_id", "chargePointId", "charge_point_id"),
        max_length=100,
    )
    connector_index: int | None = Field(
        default=None,
        validation_alias=AliasChoices("connector_index", "connectorIndex"),
        gt=0,
    )
    transaction_id: int | None = Field(
        default=None,
        validation_alias=AliasChoices("transaction_id", "transactionId"),
        ge=0,
    )
    power_kw: float = Field(ge=0, le=1000, allow_inf_nan=False)
    energy_meter_kwh: float = Field(
        validation_alias=AliasChoices(
            "energy_meter_kwh", "energyMeterKwh", "meter_energy_kwh"
        ),
        ge=0,
        le=1_000_000_000,
        allow_inf_nan=False,
    )
    observed_at: datetime | None = Field(
        default=None,
        validation_alias=AliasChoices("observed_at", "timestamp"),
    )
    idempotency_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("idempotency_key", "messageId", "message_id"),
        max_length=120,
    )

    model_config = ConfigDict(populate_by_name=True)


class ConnectorStatusIngestResponse(BaseModel):
    """
    Response payload confirming ingested connector status and observation timestamp (REQ-F2-17).
    """

    message: str
    connector_id: int
    charger_id: int
    station_id: int
    gateway_id: str
    previous_status: str | None = None
    status: str
    raw_status: str
    observed_at: datetime
    last_update: datetime
    applied: bool = True
    idempotent_replay: bool = False
    event_id: int | None = None


class MeterValueIngestResponse(BaseModel):
    message: str
    reading_id: int | None = None
    booking_id: int
    connector_id: int
    charger_id: int
    power_kw: float
    energy_meter_kwh: float
    observed_at: datetime
    applied: bool = True
    idempotent_replay: bool = False
    target_energy_reached: bool = False
    auto_stop_command_id: int | None = None
    auto_stop_status: str | None = None
    auto_stop_warning: str | None = None


class ConnectorStatusEventItem(BaseModel):
    """Single historical connector status event (REQ-F2-17)."""

    id: int
    connector_id: int
    charger_id: int
    gateway_id: str
    previous_status: str | None = None
    new_status: str
    raw_status: str
    error_code: str | None = None
    idempotency_key: str | None = None
    observed_at: datetime
    ingested_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ConnectorStatusHistoryResponse(BaseModel):
    """Telemetry status event history for a connector (REQ-F2-17)."""

    connector_id: int
    current_status: str
    last_update: datetime
    total_events: int
    events: list[ConnectorStatusEventItem] = Field(default_factory=list)

