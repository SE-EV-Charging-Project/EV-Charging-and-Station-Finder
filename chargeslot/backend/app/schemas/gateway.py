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

