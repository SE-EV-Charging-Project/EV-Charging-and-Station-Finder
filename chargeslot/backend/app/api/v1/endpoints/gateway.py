import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_operator, security
from app.core.config import settings
from app.db.session import get_db
from app.gateway.ingest import get_connector_status_history, ingest_status
from app.models.user import User, UserRole
from app.schemas.gateway import (
    ConnectorStatusHistoryResponse,
    ConnectorStatusIngestResponse,
    GatewayStatusIngestRequest,
)

gateway_ocpp_router = APIRouter(tags=["Gateway Telemetry"])
router = APIRouter(prefix="/gateway", tags=["Gateway Telemetry"])


def authenticate_gateway_or_staff(
    db: Session = Depends(get_db),
    x_gateway_secret: str | None = Header(default=None, alias="X-Gateway-Secret"),
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> User | None:
    """
    Authenticate gateway status ingestion via either a shared OCPP gateway webhook
    secret (X-Gateway-Secret) or a Bearer JWT belonging to an Operator or Admin.
    """
    if x_gateway_secret is not None:
        if not secrets.compare_digest(x_gateway_secret, settings.GATEWAY_WEBHOOK_SECRET):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid gateway webhook secret.",
            )
        return None

    if credentials is not None:
        user = get_current_user(db=db, credentials=credentials)
        role_value = user.role.value if isinstance(user.role, UserRole) else str(user.role)
        if role_value not in {UserRole.OPERATOR.value, UserRole.ADMIN.value}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only operators, admins, or authenticated charge point gateways can ingest telemetry.",
            )
        return user

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Gateway authentication required (X-Gateway-Secret or Bearer token).",
        headers={"WWW-Authenticate": "Bearer"},
    )


@gateway_ocpp_router.post(
    "/ocpp/1.6j",
    response_model=ConnectorStatusIngestResponse,
    status_code=status.HTTP_200_OK,
    summary="Ingest connector status from OCPP 1.6J charge point gateway",
)
def ingest_ocpp_connector_status(
    payload: GatewayStatusIngestRequest,
    request: Request,
    db: Session = Depends(get_db),
    actor_user: User | None = Depends(authenticate_gateway_or_staff),
) -> ConnectorStatusIngestResponse:
    """
    Ingest a connector status update from the charge point gateway (OCPP 1.6J)
    and persist one of Available, Occupied, Reserved, Faulted, or Offline along
    with observation timestamp (REQ-F2-17 / CS19-043).
    """
    client_ip = request.client.host if request.client else None
    return ingest_status(
        db=db,
        connector_id=payload.connector_id,
        state=payload.status,
        observed_at=payload.observed_at,
        gateway_id=payload.gateway_id,
        connector_index=payload.connector_index,
        error_code=payload.error_code,
        idempotency_key=payload.idempotency_key,
        actor_user=actor_user,
        client_ip=client_ip,
    )


router.include_router(gateway_ocpp_router)


@router.get(
    "/connectors/{connector_id}/status-history",
    response_model=ConnectorStatusHistoryResponse,
    status_code=status.HTTP_200_OK,
    summary="List recent ingested telemetry status events for a connector",
)
def read_connector_status_history(
    connector_id: int,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_operator),
) -> ConnectorStatusHistoryResponse:
    """Retrieve connector telemetry history (Operator scoped to own station or Admin)."""
    return get_connector_status_history(
        db=db,
        connector_id=connector_id,
        limit=limit,
        actor_user=current_user,
    )

