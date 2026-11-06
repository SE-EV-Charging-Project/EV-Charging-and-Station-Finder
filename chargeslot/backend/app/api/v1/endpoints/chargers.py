from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import require_operator, get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.charger import (
    ChargerCreateRequest,
    ChargerUpdateRequest,
    ChargerResponse,
    ChargerListResponse,
    ChargerDeleteResponse,
    ConnectorCreateRequest,
    ConnectorUpdateRequest,
    ConnectorResponse,
    ConnectorDeleteResponse,
    ChargerOutOfServiceRequest,
    ChargerReturnToServiceRequest,
    ChargerOutOfServiceResponse,
)
from app.services.charger_service import ChargerService

router = APIRouter(tags=["Chargers & Connectors"])


# =========================================================================
# Station Chargers Endpoints
# =========================================================================

@router.post(
    "/stations/{station_id}/chargers",
    response_model=ChargerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add charger to station",
    description="Adds a new charger with connectors to a station managed by the authenticated operator (REQ-F2-02 / CS19-028).",
)
def add_charger(
    station_id: int,
    payload: ChargerCreateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerResponse:
    client_ip = request.client.host if request.client else None
    charger = ChargerService.add_charger_to_station(
        db=db,
        user=current_user,
        station_id=station_id,
        data=payload,
        ip_address=client_ip,
    )
    return ChargerResponse.model_validate(charger)


@router.get(
    "/stations/{station_id}/chargers",
    response_model=ChargerListResponse,
    status_code=status.HTTP_200_OK,
    summary="List chargers of a station",
    description="Returns all chargers and their connectors for an operator's station (REQ-F2-02).",
)
def list_station_chargers(
    station_id: int,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerListResponse:
    items, total = ChargerService.list_chargers(
        db=db,
        user=current_user,
        station_id=station_id,
    )
    return ChargerListResponse(
        items=[ChargerResponse.model_validate(c) for c in items],
        total=total,
    )


# =========================================================================
# Individual Charger CRUD Endpoints
# =========================================================================

@router.get(
    "/chargers/{charger_id}",
    response_model=ChargerResponse,
    status_code=status.HTTP_200_OK,
    summary="Get charger details",
    description="Retrieves charger details and attached connectors with operator scoping (REQ-F2-02).",
)
def get_charger(
    charger_id: int,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerResponse:
    charger = ChargerService.get_charger(
        db=db,
        user=current_user,
        charger_id=charger_id,
    )
    return ChargerResponse.model_validate(charger)


@router.put(
    "/chargers/{charger_id}",
    response_model=ChargerResponse,
    status_code=status.HTTP_200_OK,
    summary="Update charger details",
    description="Edits charger power rating, current type, gateway ID, or active status (REQ-F2-02).",
)
def update_charger(
    charger_id: int,
    payload: ChargerUpdateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerResponse:
    client_ip = request.client.host if request.client else None
    charger = ChargerService.update_charger(
        db=db,
        user=current_user,
        charger_id=charger_id,
        data=payload,
        ip_address=client_ip,
    )
    return ChargerResponse.model_validate(charger)


@router.delete(
    "/chargers/{charger_id}",
    response_model=ChargerDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a charger",
    description="Removes a charger and all its connectors from the station (REQ-F2-02).",
)
def delete_charger(
    charger_id: int,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerDeleteResponse:
    client_ip = request.client.host if request.client else None
    cid = ChargerService.remove_charger(
        db=db,
        user=current_user,
        charger_id=charger_id,
        ip_address=client_ip,
    )
    return ChargerDeleteResponse(
        message="Charger successfully removed.",
        id=cid,
    )


# =========================================================================
# Out-of-Service Marking Endpoints (REQ-F2-05 / CS19-031)
# =========================================================================

@router.patch(
    "/chargers/{charger_id}/out-of-service",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark charger out of service",
    description="Allows a station operator to mark a charger out of service with mandatory reason and expected return time (REQ-F2-05 / CS19-031).",
)
@router.post(
    "/chargers/{charger_id}/out-of-service",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def mark_charger_out_of_service(
    charger_id: int,
    payload: ChargerOutOfServiceRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerOutOfServiceResponse:
    client_ip = request.client.host if request.client else None
    charger, affected_count = ChargerService.mark_out_of_service(
        db=db,
        user=current_user,
        charger_id=charger_id,
        reason=payload.reason,
        expected_return_time=payload.expected_return_time,
        ip_address=client_ip,
    )
    return ChargerOutOfServiceResponse(
        charger_id=charger.id,
        station_id=charger.station_id,
        name=charger.name,
        is_out_of_service=charger.is_out_of_service,
        out_of_service_reason=charger.out_of_service_reason,
        expected_return_time=charger.expected_return_time,
        out_of_service_at=charger.out_of_service_at,
        affected_connectors_count=affected_count,
        message=f"Charger '{charger.name or charger.id}' marked out of service until {charger.expected_return_time.isoformat()} (REQ-F2-05).",
    )


@router.patch(
    "/chargers/{charger_id}/return-to-service",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Return charger to service",
    description="Returns an out-of-service charger back to operational status and restores connectors to Available (REQ-F2-05 / CS19-031).",
)
@router.post(
    "/chargers/{charger_id}/return-to-service",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    include_in_schema=False,
)
def return_charger_to_service(
    charger_id: int,
    payload: ChargerReturnToServiceRequest | None = None,
    request: Request = None,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ChargerOutOfServiceResponse:
    client_ip = request.client.host if request and request.client else None
    note = payload.note if payload else None
    charger, affected_count = ChargerService.return_to_service(
        db=db,
        user=current_user,
        charger_id=charger_id,
        note=note,
        ip_address=client_ip,
    )
    return ChargerOutOfServiceResponse(
        charger_id=charger.id,
        station_id=charger.station_id,
        name=charger.name,
        is_out_of_service=charger.is_out_of_service,
        out_of_service_reason=charger.out_of_service_reason,
        expected_return_time=charger.expected_return_time,
        out_of_service_at=charger.out_of_service_at,
        affected_connectors_count=affected_count,
        message=f"Charger '{charger.name or charger.id}' successfully returned to active service.",
    )


@router.get(
    "/chargers/{charger_id}/out-of-service",
    response_model=ChargerOutOfServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get charger out-of-service status",
    description="Inspects whether a charger is out of service, reason, and expected return time (REQ-F2-05 / CS19-031).",
)
def get_charger_out_of_service(
    charger_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ChargerOutOfServiceResponse:
    data = ChargerService.get_out_of_service_status(
        db=db,
        user=current_user,
        charger_id=charger_id,
    )
    return ChargerOutOfServiceResponse(**data)



# =========================================================================
# Individual Connector CRUD Endpoints
# =========================================================================

@router.post(
    "/chargers/{charger_id}/connectors",
    response_model=ConnectorResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add connector to charger",
    description="Attaches a new physical connector of specified type to an existing charger (REQ-F2-02).",
)
def add_connector(
    charger_id: int,
    payload: ConnectorCreateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ConnectorResponse:
    client_ip = request.client.host if request.client else None
    connector = ChargerService.add_connector(
        db=db,
        user=current_user,
        charger_id=charger_id,
        data=payload,
        ip_address=client_ip,
    )
    return ConnectorResponse.model_validate(connector)


@router.put(
    "/connectors/{connector_id}",
    response_model=ConnectorResponse,
    status_code=status.HTTP_200_OK,
    summary="Update connector details",
    description="Modifies connector type or status with operator scoping (REQ-F2-02).",
)
def update_connector(
    connector_id: int,
    payload: ConnectorUpdateRequest,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ConnectorResponse:
    client_ip = request.client.host if request.client else None
    connector = ChargerService.update_connector(
        db=db,
        user=current_user,
        connector_id=connector_id,
        data=payload,
        ip_address=client_ip,
    )
    return ConnectorResponse.model_validate(connector)


@router.delete(
    "/connectors/{connector_id}",
    response_model=ConnectorDeleteResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove a connector",
    description="Deletes an individual connector from a charger (REQ-F2-02).",
)
def delete_connector(
    connector_id: int,
    request: Request,
    current_user: User = Depends(require_operator),
    db: Session = Depends(get_db),
) -> ConnectorDeleteResponse:
    client_ip = request.client.host if request.client else None
    cid = ChargerService.remove_connector(
        db=db,
        user=current_user,
        connector_id=connector_id,
        ip_address=client_ip,
    )
    return ConnectorDeleteResponse(
        message="Connector successfully removed.",
        id=cid,
    )
