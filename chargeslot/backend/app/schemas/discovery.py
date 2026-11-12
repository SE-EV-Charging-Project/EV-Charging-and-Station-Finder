from pydantic import BaseModel, Field, ConfigDict


class NearbyStationSearchRequest(BaseModel):
    """
    Request payload for searching stations nearby the driver's current or chosen location
    (REQ-F2-07 / CS19-033 / SRS §5.2.1 / Appendix B.4).
    Radius range is strictly 1.0 to 50.0 km (default 10.0 km).
    """
    latitude: float = Field(
        ...,
        ge=-90.0,
        le=90.0,
        description="Driver latitude coordinate [-90.0, 90.0]",
    )
    longitude: float = Field(
        ...,
        ge=-180.0,
        le=180.0,
        description="Driver longitude coordinate [-180.0, 180.0]",
    )
    radius_km: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Search radius in kilometers [1.0, 50.0] (default: 10.0)",
    )
    limit: int = Field(
        default=50,
        ge=1,
        le=100,
        description="Maximum number of stations to return",
    )


class NearbyStationItem(BaseModel):
    """
    Represents an EV charging station in nearby search results,
    suitable for list rendering and map pin plotting with distance and connector availability.
    """
    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    distance_km: float = Field(..., description="Great-circle distance in km from driver's search location")
    operating_hours: str
    amenities: list[str] = Field(default_factory=list)
    contact_phone: str
    contact_email: str | None = None
    status: str
    is_active: bool
    total_chargers: int = 0
    total_connectors: int = 0
    available_connectors: int = 0
    connector_types: list[str] = Field(default_factory=list)
    max_power_kw: float | None = None

    model_config = ConfigDict(from_attributes=True)


class NearbyStationSearchResponse(BaseModel):
    """
    Structured search results response including origin coordinates, radius,
    and sorted stations for map & list views (REQ-F2-07).
    """
    center_latitude: float
    center_longitude: float
    radius_km: float
    total_found: int
    stations: list[NearbyStationItem]

