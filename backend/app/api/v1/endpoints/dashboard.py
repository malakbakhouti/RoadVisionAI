"""Dashboard endpoints — APISpec v1.0 §6.5, sequence SD08 (CQRS reads)."""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import CurrentUserDep, DbSessionDep, require_roles
from app.db.models.user import User, UserRole
from app.schemas.dashboard import (
    DashboardSummaryResponse,
    PciTrendPoint,
    SnapshotResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

AdminDep = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]


@router.get("/summary", response_model=DashboardSummaryResponse, summary="KPI summary (SD08)")
async def summary(
    user: CurrentUserDep,
    db: DbSessionDep,
    region: str | None = None,
    province: str | None = None,
) -> DashboardSummaryResponse:
    return await DashboardService(db).summary(region=region, province=province)


@router.get("/pci-trends", response_model=list[PciTrendPoint], summary="PCI evolution")
async def pci_trends(
    user: CurrentUserDep,
    db: DbSessionDep,
    road_section_id: uuid.UUID | None = None,
    date_from: Annotated[date | None, Query()] = None,
    date_to: Annotated[date | None, Query()] = None,
) -> list[PciTrendPoint]:
    return await DashboardService(db).pci_trends(
        road_section_id=road_section_id, date_from=date_from, date_to=date_to
    )


@router.post(
    "/snapshots",
    response_model=SnapshotResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Compute a snapshot now (admin — also the daily job's entry point)",
)
async def trigger_snapshot(actor: AdminDep, db: DbSessionDep) -> SnapshotResponse:
    return await DashboardService(db).trigger_snapshot(actor)
