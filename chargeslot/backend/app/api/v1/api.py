from fastapi import APIRouter
from app.api.v1.endpoints import auth, accounts, admin, vehicles

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(admin.router)
api_router.include_router(vehicles.router)



