from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session
from app.db.session import get_db
from app.schemas.user import UserRegisterRequest, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new driver account",
    description="Registers a new user with name, email, phone, and password, assigning the Driver role by default."
)
def register(
    request_data: UserRegisterRequest,
    req: Request,
    db: Session = Depends(get_db)
):
    client_ip = req.client.host if req.client else None
    user = AuthService.register_user(db=db, request=request_data, ip_address=client_ip)
    return user
