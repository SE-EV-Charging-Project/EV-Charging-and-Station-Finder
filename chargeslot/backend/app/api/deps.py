from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserRole
from app.utils.security import decode_token

# HTTPBearer extracts the Bearer token from Authorization header
security = HTTPBearer(auto_error=False)


def get_current_user(
    db: Session = Depends(get_db),
    credentials: HTTPAuthorizationCredentials | None = Depends(security)
) -> User:
    """
    Validates JWT access token and retrieves current authenticated user.
    Enforces server-side authentication (CS19-011 / REQ-F1-11).
    Raises 401 Unauthorized for missing, expired, invalid, or wrong-type tokens.
    """
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Bearer token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials: invalid or expired token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_type = payload.get("type")
    if token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type: access token required.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id_str = payload.get("sub")
    if not user_id_str:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials: missing subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials: invalid subject.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account.",
        )

    return user


def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Returns the current verified active user."""
    return current_user


class RequireRoles:
    """
    Callable dependency class enforcing server-side Role-Based Access Control (RBAC).
    Matches SRS REQ-F1-11:
    'The system shall enforce role-based access on the server for every protected endpoint
    and shall return an authorization error when the caller\'s role is insufficient.'
    """
    def __init__(self, *roles: UserRole | str):
        self.allowed_roles = {
            r.value if isinstance(r, UserRole) else str(r) for r in roles
        }

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        user_role_str = (
            current_user.role.value
            if isinstance(current_user.role, UserRole)
            else str(current_user.role)
        )
        if user_role_str not in self.allowed_roles:
            role_names = ", ".join(sorted(self.allowed_roles))
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions for this resource. Required role: {role_names}",
            )
        return current_user


def require_roles(*roles: UserRole | str) -> RequireRoles:
    """Dependency factory helper to enforce role requirements on endpoints."""
    return RequireRoles(*roles)


# Standard role guards
require_admin = RequireRoles(UserRole.ADMIN)
require_operator = RequireRoles(UserRole.OPERATOR, UserRole.ADMIN)
require_driver = RequireRoles(UserRole.DRIVER, UserRole.ADMIN)
