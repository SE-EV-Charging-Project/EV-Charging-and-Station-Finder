"""
Auth package (SDD §Vehicles / §Auth).
"""

from app.auth.permissions import (
    enforce_driver_scope,
    scope_driver_query,
    enforce_operator_scope,
    scope_operator_query,
    authorize,
)

__all__ = [
    "enforce_driver_scope",
    "scope_driver_query",
    "enforce_operator_scope",
    "scope_operator_query",
    "authorize",
]
