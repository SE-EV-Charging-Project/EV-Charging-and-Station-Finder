from datetime import datetime
from typing import Literal

from pydantic import AliasChoices, BaseModel, Field


class SessionStopCommandResponse(BaseModel):
    command_id: int
    booking_id: int
    connector_id: int
    transaction_id: int
    trigger: str
    status: str
    requested_at: datetime
    message: str
    already_requested: bool = False


class PendingSessionStopCommand(BaseModel):
    command_id: int
    booking_id: int
    connector_id: int
    transaction_id: int
    action: Literal["RemoteStopTransaction"] = "RemoteStopTransaction"
    trigger: str
    requested_at: datetime


class PendingSessionStopCommandsResponse(BaseModel):
    gateway_id: str
    commands: list[PendingSessionStopCommand] = Field(default_factory=list)


class GatewaySessionStopResultRequest(BaseModel):
    gateway_id: str = Field(
        validation_alias=AliasChoices("gateway_id", "chargePointId"),
        min_length=1,
        max_length=100,
    )
    result: Literal["Accepted", "Rejected"]
    error_code: str | None = Field(default=None, max_length=120)


class SessionStopTransactionRequest(BaseModel):
    gateway_id: str = Field(
        validation_alias=AliasChoices("gateway_id", "chargePointId"),
        min_length=1,
        max_length=100,
    )
    transaction_id: int = Field(
        validation_alias=AliasChoices("transaction_id", "transactionId"),
        ge=0,
    )
    meter_stop_wh: int = Field(
        validation_alias=AliasChoices("meter_stop_wh", "meterStop"),
        ge=0,
        le=1_000_000_000_000,
    )
    observed_at: datetime = Field(
        validation_alias=AliasChoices("observed_at", "timestamp")
    )
    idempotency_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("idempotency_key", "messageId", "message_id"),
        max_length=120,
    )


class SessionStopTransactionResponse(BaseModel):
    booking_id: int
    transaction_id: int
    status: str
    session_ended_at: datetime
    meter_stop_wh: int
    applied: bool = True
    idempotent_replay: bool = False
