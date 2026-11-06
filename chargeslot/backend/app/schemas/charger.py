from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, field_validator
from app.models.charger import CurrentType, ConnectorStatus
from app.models.vehicle import ConnectorType


class ConnectorCreateRequest(BaseModel):
    """
    Payload for adding a connector to a charger (REQ-F2-02).
    """
    connector_type: ConnectorType = Field(..., description="Standard connector type: CCS2, CHAdeMO, Type 2, GB/T")


class ConnectorUpdateRequest(BaseModel):
    """
    Payload for updating connector properties.
    """
    connector_type: ConnectorType | None = None
    status: ConnectorStatus | None = None


class ConnectorResponse(BaseModel):
    """
    Connector data response model.
    """
    id: int
    charger_id: int
    connector_type: ConnectorType
    status: ConnectorStatus
    last_update: datetime
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChargerCreateRequest(BaseModel):
    """
    Payload for creating a new Charger under a Station (REQ-F2-02 / Appendix B.4).
    """
    name: str | None = Field(default=None, max_length=50, description="Optional charger label/identifier e.g. 'Charger 1'")
    power_kw: float = Field(..., ge=1.0, le=400.0, description="Rated power in kW [1.0, 400.0]")
    current_type: CurrentType = Field(..., description="Electrical current type: AC or DC")
    gateway_id: str = Field(..., min_length=1, max_length=100, description="Identifier of matching charge point in gateway")
    connectors: list[ConnectorCreateRequest] = Field(default_factory=list, description="Connectors attached to this charger")

    @field_validator("name", "gateway_id")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if not s and v is not None:
                raise ValueError("Field cannot be only whitespace")
            return s
        return v


class ChargerUpdateRequest(BaseModel):
    """
    Payload for editing charger specifications (REQ-F2-02).
    """
    name: str | None = Field(default=None, max_length=50)
    power_kw: float | None = Field(default=None, ge=1.0, le=400.0)
    current_type: CurrentType | None = None
    gateway_id: str | None = Field(default=None, min_length=1, max_length=100)
    is_active: bool | None = None
    is_out_of_service: bool | None = None

    @field_validator("name", "gateway_id")
    @classmethod
    def strip_whitespace(cls, v: str | None) -> str | None:
        if v is not None:
            s = v.strip()
            if not s:
                raise ValueError("Field cannot be only whitespace")
            return s
        return v


class ChargerResponse(BaseModel):
    """
    Charger data response model including attached connectors.
    """
    id: int
    station_id: int
    name: str | None
    power_kw: float
    current_type: CurrentType
    gateway_id: str
    is_active: bool
    is_out_of_service: bool
    connectors: list[ConnectorResponse]
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ChargerListResponse(BaseModel):
    """
    List response for chargers belonging to a station.
    """
    items: list[ChargerResponse]
    total: int


class ChargerDeleteResponse(BaseModel):
    """
    Confirmation response on charger deletion.
    """
    message: str
    id: int


class ConnectorDeleteResponse(BaseModel):
    """
    Confirmation response on connector deletion.
    """
    message: str
    id: int
