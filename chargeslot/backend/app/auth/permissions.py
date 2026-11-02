"""
Permissions module (REQ-F1-26 / CS19-026 / auth/permissions.py).
Enforces driver tenancy isolation: drivers can view and modify only their own profile and vehicles.
"""

from app.core.permissions import (
    enforce_driver_scope,
    scope_driver_query,
    enforce_operator_scope,
    scope_operator_query,
    authorize,
    get_current_user,
    get_current_active_user,
    require_roles,
    RequireRoles,
    require_admin,
    require_operator,
    require_driver,
)

__all__ = [
    "enforce_driver_scope",
    "scope_driver_query",
    "enforce_operator_scope",
    "scope_operator_query",
    "authorize",
    "get_current_user",
    "get_current_active_user",
    "require_roles",
    "RequireRoles",
    "require_admin",
    "require_operator",
    "require_driver",
]
