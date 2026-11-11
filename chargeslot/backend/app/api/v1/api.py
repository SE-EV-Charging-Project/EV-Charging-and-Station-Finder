from fastapi import APIRouter
from app.api.v1.endpoints import (
    auth,
    accounts,
    admin,
    vehicles,
    stations,
    chargers,
    maintenance,
    discovery,
    gateway,
    dashboard,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(accounts.router)
api_router.include_router(admin.router)
api_router.include_router(vehicles.router)
api_router.include_router(discovery.router)
api_router.include_router(dashboard.router)
api_router.include_router(stations.router)
api_router.include_router(chargers.router)
api_router.include_router(maintenance.router)
api_router.include_router(gateway.router)



