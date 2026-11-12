import enum
from pydantic import BaseModel, Field, ConfigDict


class MarkerColor(str, enum.Enum):
    """
    Availability marker color codes (SRS §5.2.1 / REQ-F2-08).
    GREEN: All or multiple connectors available.
    AMBER: Partially available (some occupied/reserved).
    RED: Fully occupied or reserved (0 available).
    GREY: Offline, faulted, out of service, or 0 operational connectors.
    """
    GREEN = "green"
    AMBER = "amber"
    RED = "red"
    GREY = "grey"


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
    price_per_kwh: float | None = Field(default=None, description="Tariff price per kWh in INR (REQ-F2-10)")
    color_code: str | None = Field(default=None, description="Marker colour: green, amber, red, grey (REQ-F2-08)")
    status_label: str | None = Field(default=None, description="Accessibility text label e.g. Available, Occupied")
    badge_text: str | None = Field(default=None, description="Badge text e.g. '3/4 Available'")

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


class StationAvailabilityMarker(BaseModel):
    """
    Station availability marker model for map display (REQ-F2-08 / CS19-034).
    Colour-codes each station marker by availability and shows the number of available
    connectors out of the total, using a text label as well as colour.
    """
    station_id: int
    name: str
    latitude: float
    longitude: float
    total_connectors: int = Field(..., description="Total connectors at this station")
    available_connectors: int = Field(..., description="Currently available connectors")
    occupied_connectors: int = Field(default=0, description="Occupied connectors")
    reserved_connectors: int = Field(default=0, description="Reserved connectors")
    offline_connectors: int = Field(default=0, description="Offline or faulted connectors")
    color_code: MarkerColor = Field(..., description="Colour code: green, amber, red, or grey")
    hex_color: str = Field(..., description="Hex representation: #4CAF50, #FF9800, #F44336, #9E9E9E")
    status_label: str = Field(..., description="Text label for colour-blind accessibility (REQ-F2-08)")
    badge_text: str = Field(..., description="Available out of total text, e.g. '3/4 Available'")
    is_operational: bool = Field(default=True, description="Whether station has operational connectors")

    model_config = ConfigDict(from_attributes=True)


class StationAvailabilityMarkersResponse(BaseModel):
    """
    Collection response of station availability markers for home map (REQ-F2-08 / §5.2.2 SR-F2-01).
    """
    total: int
    markers: list[StationAvailabilityMarker]


class BatchAvailabilityMarkersRequest(BaseModel):
    """
    Request payload to query or update availability markers for specific stations (REQ-F2-08).
    """
    station_ids: list[int] = Field(..., min_length=1, max_length=200, description="List of station IDs")


class StationFilterRequest(BaseModel):
    """
    Payload for filtering stations by multiple criteria (REQ-F2-09 / CS19-035).
    Filters by connector types, minimum power, availability now, max price,
    amenities, and vehicle compatibility.
    """
    connector_types: list[str] | None = Field(
        default=None,
        description="Filter by connector types: CCS2, CHAdeMO, Type 2, GB/T",
    )
    min_power_kw: float | None = Field(
        default=None,
        ge=0.0,
        le=500.0,
        description="Minimum charger power rating in kW",
    )
    available_now: bool | None = Field(
        default=None,
        description="Only return stations with at least one currently available connector",
    )
    max_price_kwh: float | None = Field(
        default=None,
        ge=0.0,
        description="Maximum tariff price per kWh in INR",
    )
    amenities: list[str] | None = Field(
        default=None,
        description="Required amenities (e.g. WiFi, Restroom, Cafe)",
    )
    vehicle_id: int | None = Field(
        default=None,
        description="Selected vehicle ID for compatibility filtering",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Optional driver latitude for proximity filtering",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Optional driver longitude for proximity filtering",
    )
    radius_km: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Search radius in kilometers [1.0, 50.0]",
    )
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)
    sort_by: str | None = Field(default=None, description="Sort criteria: distance, price, power, availability (REQ-F2-10)")
    sort_order: str | None = Field(default=None, description="Sort direction: 'asc' or 'desc'")


class StationFilterResponse(BaseModel):
    """
    Response model for filtered station results (REQ-F2-09).
    """
    total: int
    applied_filters: dict = Field(default_factory=dict)
    stations: list[NearbyStationItem]


class StationSortBy(str, enum.Enum):
    """
    Supported station sorting criteria (REQ-F2-10 / CS19-036).
    """
    DISTANCE = "distance"
    PRICE = "price"
    POWER = "power"
    AVAILABILITY = "availability"


class SortOrder(str, enum.Enum):
    """
    Sort order direction: ascending or descending.
    """
    ASC = "asc"
    DESC = "desc"


class StationSortRequest(BaseModel):
    """
    Request payload for sorting stations by distance, price, power, or availability (REQ-F2-10 / CS19-036).
    """
    sort_by: StationSortBy = Field(
        default=StationSortBy.DISTANCE,
        description="Sort criteria: distance, price, power, availability (REQ-F2-10)",
    )
    sort_order: SortOrder | None = Field(
        default=None,
        description="Sort direction: 'asc' or 'desc'. Defaults per criteria (distance/price: asc, power/availability: desc)",
    )
    latitude: float | None = Field(
        default=None,
        ge=-90.0,
        le=90.0,
        description="Driver latitude coordinate [-90.0, 90.0]",
    )
    longitude: float | None = Field(
        default=None,
        ge=-180.0,
        le=180.0,
        description="Driver longitude coordinate [-180.0, 180.0]",
    )
    radius_km: float = Field(
        default=10.0,
        ge=1.0,
        le=50.0,
        description="Search radius in kilometers [1.0, 50.0]",
    )
    station_ids: list[int] | None = Field(
        default=None,
        description="Optional explicit station IDs to sort",
    )
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class StationSortResponse(BaseModel):
    """
    Structured sorted station response (REQ-F2-10 / CS19-036).
    """
    total: int
    sort_by: str
    sort_order: str
    stations: list[NearbyStationItem]



