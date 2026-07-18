"""AI model registry endpoints — UC3 (administration), SM4 lifecycle."""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from app.ai.detection.class_mapping import DEFAULT_CLASS_TO_CODE
from app.ai.detection.model_registry import ModelRegistryService
from app.core.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    SettingsDep,
    get_storage_service,
    require_roles,
)
from app.db.models.user import User, UserRole
from app.schemas.ai_model import AiModelResponse, ModelRegisterMetadata
from app.services.storage_service import StorageService

router = APIRouter(prefix="/models", tags=["ai-models"])

StorageDep = Annotated[StorageService, Depends(get_storage_service)]
AdminDep = Annotated[User, Depends(require_roles(UserRole.ADMINISTRATOR))]

MAX_WEIGHTS_BYTES = 500 * 1024 * 1024


@router.post(
    "",
    response_model=AiModelResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a trained model (weights -> MinIO, metadata -> ai_models)",
)
async def register_model(
    actor: AdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
    weights: Annotated[UploadFile, File(description=".pt weights file")],
    name: Annotated[str, Form(min_length=3, max_length=200)],
    version: Annotated[str, Form(min_length=1, max_length=50)],
    class_mapping: Annotated[
        str | None, Form(description="JSON {yolo_class: DAMAGE_CODE}; defaults to v1 mapping")
    ] = None,
    metadata: Annotated[str | None, Form(description="JSON ModelRegisterMetadata")] = None,
) -> AiModelResponse:
    data = await weights.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty weights file")
    if len(data) > MAX_WEIGHTS_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Weights exceed 500 MB")

    try:
        mapping = json.loads(class_mapping) if class_mapping else dict(DEFAULT_CLASS_TO_CODE)
        meta = ModelRegisterMetadata.model_validate_json(metadata) if metadata else None
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    model = await ModelRegistryService(db, settings, storage).register(
        name=name,
        version=version,
        weights=data,
        class_mapping=mapping,
        metadata=meta.model_dump() if meta else {},
        actor=actor,
    )
    return AiModelResponse.model_validate(model)


@router.get("", response_model=list[AiModelResponse], summary="List registered models")
async def list_models(
    user: CurrentUserDep, db: DbSessionDep, settings: SettingsDep, storage: StorageDep
) -> list[AiModelResponse]:
    models = await ModelRegistryService(db, settings, storage).list()
    return [AiModelResponse.model_validate(m) for m in models]


@router.post(
    "/{model_id}/promote",
    response_model=AiModelResponse,
    summary="Promote to production (SM4 — single active model)",
)
async def promote_model(
    model_id: uuid.UUID,
    actor: AdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
    storage: StorageDep,
) -> AiModelResponse:
    model = await ModelRegistryService(db, settings, storage).promote(model_id, actor)
    return AiModelResponse.model_validate(model)
