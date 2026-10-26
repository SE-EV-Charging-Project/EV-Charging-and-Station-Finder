from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.user import (
    UserRegisterRequest,
    UserLoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    UserResponse,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver account",
    description="Registers a new user with name, email, phone, and password, assigning the Driver role by default (CS19-001, CS19-002, CS19-008, CS19-010)."
)
def register(
    request_data: UserRegisterRequest,
    req: Request,
    db: Session = Depends(get_db)
):
    client_ip = req.client.host if req.client else None
    user = AuthService.register_user(db=db, request=request_data, ip_address=client_ip)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Authenticate and obtain JWT tokens",
    description="Authenticates with email/phone and password, returning access and refresh JWT tokens (CS19-004, CS19-005, CS19-009)."
)
def login(
    request_data: UserLoginRequest,
    req: Request,
    db: Session = Depends(get_db)
):
    client_ip = req.client.host if req.client else None
    return AuthService.login_user(db=db, request=request_data, ip_address=client_ip)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Refresh access token",
    description="Exchanges a valid refresh token for a new short-lived access token (CS19-004)."
)
def refresh_token(
    request_data: RefreshTokenRequest,
    db: Session = Depends(get_db)
):
    return AuthService.refresh_access_token(db=db, refresh_token=request_data.refresh_token)
