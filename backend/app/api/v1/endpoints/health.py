"""Infrastructure endpoints — liveness & readiness (TechStack §7 monitoring).

These are operational probes consumed by Docker healthchecks and Nginx.
They are intentionally OUTSIDE APISpec v1.0's 17 business endpoints and
carry no authentication.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.core.dependencies import DbSessionDep, SettingsDep

router = APIRouter(tags=["infrastructure"])


class HealthResponse(BaseModel):
    status: str
    app: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    postgis: str | None = None


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        status="ok",
        app=settings.app_name,
        version=settings.version,
        environment=settings.environment,
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe (checks DB)")
async def ready(db: DbSessionDep) -> ReadyResponse:
    result = await db.execute(text("SELECT 1"))
    result.scalar_one()
    postgis = (await db.execute(text("SELECT PostGIS_Lib_Version()"))).scalar_one()
    return ReadyResponse(status="ready", database="up", postgis=postgis)
