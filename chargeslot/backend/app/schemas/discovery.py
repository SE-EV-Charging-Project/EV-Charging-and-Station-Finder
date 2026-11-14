import enum
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from app.models.fault_report import FaultReportStatus, FaultSeverity, FaultType


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
    vehicle_compatible_max_power_kw: float | None = Field(
        default=None,
        description="Maximum effective power for the selected vehicle's compatible connectors",
    )
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


class StationTextSearchRequest(BaseModel):
    """
    Request payload for free-text station search (REQ-F2-11 / CS19-037).
    """
    query: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Search term matching station name, address, or area",
    )
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_km: float | None = Field(default=None, ge=1.0, le=50.0)
    sort_by: str | None = Field(default=None, description="Optional sort criteria: distance, price, power, availability")
    sort_order: str | None = Field(default=None, description="Optional sort direction: asc, desc")
    limit: int = Field(default=50, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class StationTextSearchResponse(BaseModel):
    """
    Structured free-text station search response (REQ-F2-11 / CS19-037).
    """
    query: str
    total: int
    stations: list[NearbyStationItem]


class StationClusterItem(BaseModel):
    """
    Aggregated spatial cluster of EV stations on map view when >50 stations are in view (REQ-F2-12 / CS19-038).
    """
    cluster_id: str
    latitude: float
    longitude: float
    station_count: int
    total_connectors: int
    available_connectors: int
    color_code: str
    badge_text: str
    station_ids: list[int]
    bounds: list[float] | None = None


class ClusteredMapViewResponse(BaseModel):
    """
    Response model for map view with marker clustering (REQ-F2-12 / CS19-038).
    When total_stations <= 50, is_clustered is False and individual_stations are returned.
    When total_stations > 50, is_clustered is True and clusters are returned.
    """
    is_clustered: bool
    threshold: int = 50
    total_stations: int
    clusters: list[StationClusterItem] = Field(default_factory=list)
    individual_stations: list[NearbyStationItem] = Field(default_factory=list)


class ClusteredMapViewRequest(BaseModel):
    """
    Request payload for querying map view with clustering (REQ-F2-12).
    """
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    radius_km: float = Field(default=50.0, ge=1.0, le=50.0)
    threshold: int = Field(default=50, ge=1, le=100)


class PaginatedStationListResponse(BaseModel):
    """
    Standard paginated list response with 20 items/page default per REQ-F2-12.
    """
    total: int
    page: int = 1
    page_size: int = 20
    total_pages: int
    has_next: bool
    has_prev: bool
    items: list[NearbyStationItem]


class StationOperatorSummary(BaseModel):
    """
    Summary of the station operator displayed on the station detail screen (REQ-F2-13).
    """

    id: int
    name: str
    organization: str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None

    model_config = ConfigDict(from_attributes=True)


class StationDetailConnectorItem(BaseModel):
    """
    Live connector detail item showing type, power, status, and last update timestamp (REQ-F2-13 / SR-F2-03).
    """

    id: int
    charger_id: int
    charger_name: str
    connector_type: str
    power_kw: float
    current_type: str
    status: str
    last_update: datetime | None = None
    is_out_of_service: bool = False
    out_of_service_reason: str | None = None
    expected_return_time: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class StationDetailChargerItem(BaseModel):
    """
    Charger grouping for the station detail screen (REQ-F2-13 / BR-11).
    """

    id: int
    name: str
    power_kw: float
    current_type: str
    is_active: bool
    is_out_of_service: bool = False
    out_of_service_reason: str | None = None
    expected_return_time: datetime | None = None
    connectors: list[StationDetailConnectorItem] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class StationDetailResponse(BaseModel):
    """
    Full station detail payload for REQ-F2-13 / SR-F2-03.
    """

    id: int
    name: str
    address: str
    latitude: float
    longitude: float
    distance_km: float | None = None
    operator: StationOperatorSummary
    amenities: list[str] = Field(default_factory=list)
    operating_hours: dict | str | None = None
    contact_phone: str | None = None
    contact_email: str | None = None
    price_per_kwh: float | None = None
    average_rating: float | None = None
    total_reviews: int = 0
    status: str
    is_active: bool
    availability_marker: StationAvailabilityMarker
    total_connectors: int
    available_connectors: int
    connectors: list[StationDetailConnectorItem] = Field(default_factory=list)
    chargers: list[StationDetailChargerItem] = Field(default_factory=list)
    last_status_update: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class FavouriteStationRequest(BaseModel):
    """
    Request payload for saving a charging station as a driver favourite (REQ-F2-14).
    """

    station_id: int = Field(..., gt=0, description="ID of the station to save as favourite")


class FavouriteStationItem(BaseModel):
    """
    Saved favourite station summary displayed in the driver's favourites list (REQ-F2-14).
    """

    station_id: int
    name: str
    address: str
    latitude: float
    longitude: float
    distance_km: float | None = None
    operating_hours: str | None = None
    amenities: list[str] = Field(default_factory=list)
    price_per_kwh: float | None = None
    average_rating: float | None = None
    total_reviews: int = 0
    status: str
    is_active: bool
    availability_marker: StationAvailabilityMarker
    favourited_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FavouriteStationActionResponse(BaseModel):
    """
    Confirmation payload after saving or removing a favourite station (REQ-F2-14).
    """

    message: str
    station_id: int
    is_favourite: bool
    favourite: FavouriteStationItem | None = None


class FavouriteStationListResponse(BaseModel):
    """
    List of favourite charging stations saved by the driver (REQ-F2-14).
    """

    total: int
    stations: list[FavouriteStationItem] = Field(default_factory=list)


class StationReviewCreateRequest(BaseModel):
    """
    Request payload for rating (1-5) and reviewing a station after a completed session (REQ-F2-15).
    """

    booking_id: int = Field(..., gt=0, description="Completed charging session / booking ID")
    rating: int = Field(..., ge=1, le=5, description="Station rating between 1 and 5")
    station_id: int | None = Field(
        default=None,
        gt=0,
        description="Optional station ID verified against the completed booking",
    )
    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional written review comment (max 1000 characters)",
    )


class StationReviewItem(BaseModel):
    """
    Single driver review item for a charging station (REQ-F2-15).
    """

    id: int
    user_id: int
    reviewer_name: str
    station_id: int
    booking_id: int
    rating: int
    comment: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class StationReviewCreateResponse(BaseModel):
    """
    Response payload returned when submitting a station rating and review (REQ-F2-15).
    """

    message: str
    review: StationReviewItem
    average_rating: float | None = None
    total_reviews: int


class StationReviewListResponse(BaseModel):
    """
    List of reviews and aggregated rating summary for a charging station (REQ-F2-15).
    """

    station_id: int
    average_rating: float | None = None
    total_reviews: int
    reviews: list[StationReviewItem] = Field(default_factory=list)


class _FaultyChargerReportFields(BaseModel):
    """Shared fault report payload fields for REQ-F2-16."""

    description: str = Field(
        ...,
        min_length=5,
        max_length=1000,
        description="Description of the charger fault (5-1000 characters)",
    )
    station_id: int | None = Field(
        default=None,
        gt=0,
        description="Optional station ID verified against the reported charger",
    )
    connector_id: int | None = Field(
        default=None,
        gt=0,
        description="Optional affected connector ID on the charger",
    )
    fault_type: FaultType = Field(
        default=FaultType.HARDWARE_FAULT,
        description="Category of charger fault",
    )
    severity: FaultSeverity = Field(
        default=FaultSeverity.MEDIUM,
        description="Severity of the fault (low, medium, high, critical)",
    )


class FaultyChargerReportByPathRequest(_FaultyChargerReportFields):
    """Request body when charger_id is supplied in the URL path (REQ-F2-16)."""

    pass


class FaultyChargerReportCreateRequest(_FaultyChargerReportFields):
    """Request payload for reporting a faulty charger via /report-faulty-charger (REQ-F2-16)."""

    charger_id: int = Field(..., gt=0, description="ID of the faulty charger")


class FaultyChargerReportStatusUpdateRequest(BaseModel):
    """Operator status update request for a forwarded fault report (REQ-F2-16)."""

    status: FaultReportStatus = Field(
        ...,
        description="New workflow status (acknowledged or resolved)",
    )
    operator_notes: str | None = Field(
        default=None,
        max_length=500,
        description="Optional operator triage or resolution notes",
    )


class FaultForwardingSummary(BaseModel):
    """Details confirming delivery/forwarding of a fault report to the station operator (REQ-F2-16)."""

    operator_id: int
    operator_name: str
    organization: str | None = None
    forwarded_to_email: str | None = None
    forwarded_to_phone: str | None = None
    channels: list[str] = Field(default_factory=list)
    forwarded_at: datetime


class FaultyChargerReportItem(BaseModel):
    """Faulty charger report DTO returned to reporters and station operators (REQ-F2-16)."""

    id: int
    reporter_user_id: int
    reporter_name: str
    operator_id: int
    station_id: int
    station_name: str
    charger_id: int
    charger_name: str
    connector_id: int | None = None
    fault_type: str
    severity: str
    description: str
    status: str
    forwarding: FaultForwardingSummary
    operator_notes: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class FaultyChargerReportCreateResponse(BaseModel):
    """Confirmation payload returned when a faulty charger report is submitted and forwarded (REQ-F2-16)."""

    message: str
    report: FaultyChargerReportItem


class FaultyChargerReportListResponse(BaseModel):
    """List of faulty charger reports scoped to the caller's role (REQ-F2-16)."""

    total: int
    reports: list[FaultyChargerReportItem] = Field(default_factory=list)




