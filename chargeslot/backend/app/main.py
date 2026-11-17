from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse

from app.core.config import settings
from app.api.v1.api import api_router
from app.api.v1.endpoints.dashboard import ws_router as dashboard_ws_router
from app.api.v1.endpoints.gateway import gateway_ocpp_router

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url=f"{settings.API_V1_STR}/docs",
    redoc_url=f"{settings.API_V1_STR}/redoc"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "service": "chargeslot-api"
    }


@app.get("/", include_in_schema=False)
def serve_frontend_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.is_file():
        return FileResponse(
            index_file,
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )
    return {"status": "ok", "service": "chargeslot-api"}


@app.get("/static/{file_path:path}", include_in_schema=False)
def serve_frontend_static(file_path: str):
    target = (STATIC_DIR / file_path).resolve()
    # Guard against directory traversal
    if not str(target).startswith(str(STATIC_DIR)) or not target.is_file():
        raise HTTPException(status_code=404, detail="Static asset not found")
    return FileResponse(
        target,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(gateway_ocpp_router, prefix="/gateway")
app.include_router(dashboard_ws_router)
