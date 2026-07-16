"""Report endpoints — APISpec v1.0 (SD06)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import RedirectResponse

from app.core.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    SettingsDep,
    get_storage_service,
    require_roles,
)
from app.db.models.user import User, UserRole
from app.schemas.report import ReportGenerateRequest, ReportListResponse, ReportResponse
from app.services.report_service import ReportService
from app.services.storage_service import StorageService

router = APIRouter(tags=["reports"])

StorageDep = Annotated[StorageService, Depends(get_storage_service)]
_engineer_or_admin = require_roles(UserRole.ROAD_ENGINEER, UserRole.ADMINISTRATOR)
EngineerOrAdminDep = Annotated[User, Depends(_engineer_or_admin)]


@router.post(
    "/plans/{plan_id}/report",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate the plan report PDF (SD06 — one per plan)",
)
async def generate_report(
    plan_id: uuid.UUID,
    body: ReportGenerateRequest,
    actor: EngineerOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> ReportResponse:
    report = await ReportService(db, settings, storage).generate_for_plan(
        plan_id, body.title, body.executive_summary, actor
    )
    return ReportResponse.model_validate(report)


@router.get("/reports", response_model=ReportListResponse, summary="List reports")
async def list_reports(
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReportListResponse:
    items, total = await ReportService(db, settings, storage).list(limit=limit, offset=offset)
    return ReportListResponse(
        items=[ReportResponse.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/reports/{report_id}", response_model=ReportResponse, summary="Report detail")
async def get_report(
    report_id: uuid.UUID,
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> ReportResponse:
    svc = ReportService(db, settings, storage)
    report = await svc.get(report_id)
    dto = ReportResponse.model_validate(report)
    if report.file_path:
        dto.download_url = await svc.download_url(report_id)
    return dto


@router.get(
    "/reports/{report_id}/download",
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    summary="Redirect to the presigned PDF URL",
)
async def download_report(
    report_id: uuid.UUID,
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> RedirectResponse:
    url = await ReportService(db, settings, storage).download_url(report_id)
    return RedirectResponse(url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
