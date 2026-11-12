from fastapi import FastAPI
from app.core.config import settings
from app.api.v1.api import api_router
from app.api.v1.endpoints.dashboard import ws_router as dashboard_ws_router
from app.api.v1.endpoints.gateway import gateway_ocpp_router

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc"
)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "service": "chargeslot-api"
    }


app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(gateway_ocpp_router, prefix="/gateway")
app.include_router(dashboard_ws_router)