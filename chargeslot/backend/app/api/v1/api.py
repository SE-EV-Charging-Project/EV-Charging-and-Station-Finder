from fastapi import APIRouter
from app.api.v1.endpoints import auth, accounts, admin, vehicles, stations, chargers

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(admin.router)
api_router.include_router(vehicles.router)
api_router.include_router(stations.router)
api_router.include_router(chargers.router)



