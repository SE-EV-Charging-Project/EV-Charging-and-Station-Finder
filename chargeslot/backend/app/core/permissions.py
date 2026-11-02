from fastapi import HTTPException, status
from sqlalchemy.orm import Query

from app.api.deps import (
    get_current_user,
    get_current_active_user,
    require_roles,
    RequireRoles,
    require_admin,
    require_operator,
    require_driver,
)
from app.models.user import User, UserRole


def enforce_operator_scope(current_user: User, resource_operator_id: int) -> bool:
    """
    Enforces Station Operator data scoping rule per SRS REQ-F1-12 / CS19-012:
    'A Station Operator shall see and manage only their own stations and their data.
    The system shall restrict a Station Operator to the stations, chargers, tariffs
    and reports that belong to that operator.'

    - Administrators have global scope across all stations.
    - Operators can only access resources where resource_operator_id == current_user.id.
    - Drivers and other roles are denied with HTTP 403 Forbidden.
    """
    if current_user.role == UserRole.ADMIN:
        return True

    if current_user.role == UserRole.OPERATOR:
        if current_user.id == resource_operator_id:
            return True
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: Station Operators are restricted to their own stations, chargers, tariffs, and reports (REQ-F1-12).",
        )

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions: Station Operator or Administrator role required.",
    )


def scope_operator_query(
    query: Query,
    model: type,
    current_user: User,
    operator_id_attr: str = "operator_id",
) -> Query:
    """
    Filters a SQLAlchemy query by the current user's operator scope.
    - If Admin: returns query unaltered (global scope).
    - If Operator: filters by operator_id == current_user.id.
    - If Driver/Other: raises HTTP 403 Forbidden.
    """
    if current_user.role == UserRole.ADMIN:
        return query

    if current_user.role == UserRole.OPERATOR:
        return query.filter(getattr(model, operator_id_attr) == current_user.id)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions: Station Operator or Administrator role required.",
    )


def enforce_driver_scope(current_user: User, resource_user_id: int) -> bool:
    """
    Enforces Driver tenancy isolation rule per SRS REQ-F1-26 / CS19-026:
    'The system shall ensure that a driver can view and modify only their own profile and vehicles.'

    - Administrators have global scope across user profiles and vehicles.
    - Drivers can only access resources where resource_user_id == current_user.id.
    - Foreign drivers or other roles are denied with HTTP 403 Forbidden.
    """
    if current_user.role == UserRole.ADMIN:
        return True

    if current_user.id == resource_user_id:
        return True

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access denied: Drivers can view and modify only their own profile and vehicles (REQ-F1-26).",
    )


def scope_driver_query(
    query: Query,
    model: type,
    current_user: User,
    user_id_attr: str = "user_id",
) -> Query:
    """
    Filters a SQLAlchemy query by the current user's driver tenancy scope (REQ-F1-26).
    - If Admin: returns query unaltered.
    - If Driver: filters by user_id == current_user.id.
    - If Other: raises HTTP 403 Forbidden.
    """
    if current_user.role == UserRole.ADMIN:
        return query

    if current_user.role == UserRole.DRIVER:
        return query.filter(getattr(model, user_id_attr) == current_user.id)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions: Driver or Administrator role required.",
    )


def authorize(
    principal: User,
    action: str,
    resource_id: int | None = None,
    resource_owner_id: int | None = None,
) -> bool:
    """
    Internal module contract helper matching SW Architecture §11:
    'F1 -> F2/F3/F4: authorize(principal, action, resource_id)'
    Validates principal status and enforces role / operator scoping.
    """
    if not principal.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    if principal.role == UserRole.ADMIN:
        return True

    if action in [
        "view_station",
        "manage_station",
        "manage_charger",
        "set_tariff",
        "view_operator_reports",
        "operator_data_scope",
    ]:
        if principal.role != UserRole.OPERATOR:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Action '{action}' requires Station Operator or Administrator role.",
            )
        if resource_owner_id is not None and resource_owner_id != principal.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Station Operators are restricted to their own stations and data (REQ-F1-12).",
            )
        return True

    return True


__all__ = [
    "get_current_user",
    "get_current_active_user",
    "require_roles",
    "RequireRoles",
    "require_admin",
    "require_operator",
    "require_driver",
    "enforce_operator_scope",
    "scope_operator_query",
    "enforce_driver_scope",
    "scope_driver_query",
    "authorize",
]
