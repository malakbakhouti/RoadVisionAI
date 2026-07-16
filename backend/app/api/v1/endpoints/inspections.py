"""Inspection endpoints — APISpec v1.0 §6.2 & §7, sequences SD02/SD03 (entry), UC1."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status

from app.core.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    SettingsDep,
    get_storage_service,
    require_roles,
)
from app.db.models.enums import InspectionStatus
from app.db.models.user import User, UserRole
from app.schemas.inspection import (
    AnalysisAccepted,
    InspectionCreate,
    InspectionDetailResponse,
    InspectionListResponse,
    InspectionResponse,
    InspectionUpdate,
    RoadImageResponse,
)
from app.services.inspection_service import InspectionService
from app.services.storage_service import StorageService

router = APIRouter(prefix="/inspections", tags=["inspections"])

StorageDep = Annotated[StorageService, Depends(get_storage_service)]

_agent_or_admin = require_roles(UserRole.INSPECTION_AGENT, UserRole.ADMINISTRATOR)
_admin_only = require_roles(UserRole.ADMINISTRATOR)
AgentOrAdminDep = Annotated[User, Depends(_agent_or_admin)]
AdminDep = Annotated[User, Depends(_admin_only)]


def _service(db, settings, storage) -> InspectionService:
    return InspectionService(db, settings, storage)


@router.post(
    "",
    response_model=InspectionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create inspection (UC1, agent)",
)
async def create_inspection(
    body: InspectionCreate,
    actor: AgentOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> InspectionResponse:
    inspection = await _service(db, settings, storage).create(body, actor)
    return InspectionResponse.model_validate(inspection)


@router.get("", response_model=InspectionListResponse, summary="List inspections")
async def list_inspections(
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    status_filter: Annotated[InspectionStatus | None, Query(alias="status")] = None,
    road_section_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> InspectionListResponse:
    items, total = await _service(db, settings, storage).list(
        status=status_filter, road_section_id=road_section_id, limit=limit, offset=offset
    )
    return InspectionListResponse(
        items=[InspectionResponse.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{inspection_id}",
    response_model=InspectionDetailResponse,
    summary="Inspection detail with images",
)
async def get_inspection(
    inspection_id: uuid.UUID,
    user: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> InspectionDetailResponse:
    inspection = await _service(db, settings, storage).get_detail(inspection_id)
    detail = InspectionDetailResponse.model_validate(inspection)
    detail.images = [RoadImageResponse.model_validate(img) for img in inspection.road_images]
    for dto in detail.images:
        bucket, _, object_name = dto.storage_path.partition("/")
        dto.download_url = await storage.presigned_get_url(bucket, object_name)
    return detail


@router.patch(
    "/{inspection_id}",
    response_model=InspectionResponse,
    summary="Update inspection (optimistic locking — 409 on stale version)",
)
async def update_inspection(
    inspection_id: uuid.UUID,
    body: InspectionUpdate,
    actor: AgentOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> InspectionResponse:
    inspection = await _service(db, settings, storage).update(inspection_id, body, actor)
    return InspectionResponse.model_validate(inspection)


@router.delete(
    "/{inspection_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete inspection (admin)",
)
async def delete_inspection(
    inspection_id: uuid.UUID,
    actor: AdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> None:
    await _service(db, settings, storage).soft_delete(inspection_id, actor)


@router.post(
    "/{inspection_id}/images",
    response_model=RoadImageResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload road image to MinIO (SD02)",
)
async def upload_image(
    inspection_id: uuid.UUID,
    actor: AgentOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    gps_lat: Annotated[float | None, Form(ge=-90, le=90)] = None,
    gps_lng: Annotated[float | None, Form(ge=-180, le=180)] = None,
) -> RoadImageResponse:
    image = await _service(db, settings, storage).upload_image(
        inspection_id, file, gps_lat=gps_lat, gps_lng=gps_lng, actor=actor
    )
    return RoadImageResponse.model_validate(image)


@router.post(
    "/{inspection_id}/analyse",
    response_model=AnalysisAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request AI analysis — async 202 pattern (SD03 entry)",
)
async def request_analysis(
    inspection_id: uuid.UUID,
    actor: CurrentUserDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> AnalysisAccepted:
    return await _service(db, settings, storage).request_analysis(inspection_id, actor)
