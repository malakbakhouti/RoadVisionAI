"""ModelRegistryService — the ai_models registry (SM4, UC3, TechStack §4).

Deliberately NOT MLflow: the registry is the ai_models table (metadata,
metrics, lineage) plus the MinIO `models/` bucket (weights + model_config.json).
The database enforces the single-production-model invariant via the partial
unique index uq_one_active_model; promotion is therefore transactional:
deactivate the current model and activate the new one in one commit.
"""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.ai_model import AiModel
from app.db.models.enums import ModelStatus
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.services.storage_service import StorageService

log = structlog.get_logger("app.ai.registry")


class ModelRegistryService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: StorageService) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage
        self._audit = AuditRepository(session)

    # --- registration (SM4: -> STAGING) --------------------------------------
    async def register(
        self,
        *,
        name: str,
        version: str,
        weights: bytes,
        class_mapping: dict[str, str],
        metadata: dict[str, Any],
        actor: User,
    ) -> AiModel:
        exists = (
            await self._session.execute(
                select(AiModel.id).where(AiModel.name == name, AiModel.version == version)
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"Model {name}:{version} already registered"
            )

        bucket = self._settings.minio_bucket_models
        prefix = f"{name}/{version}"
        await self._storage.put_object(
            bucket=bucket,
            object_name=f"{prefix}/best.pt",
            data=weights,
            content_type="application/octet-stream",
        )
        config = {"class_mapping": class_mapping, "registered_at": datetime.now(UTC).isoformat()}
        await self._storage.put_object(
            bucket=bucket,
            object_name=f"{prefix}/model_config.json",
            data=json.dumps(config, indent=2).encode(),
            content_type="application/json",
        )

        model = AiModel(
            name=name,
            version=version,
            weights_path=f"{bucket}/{prefix}/best.pt",
            model_size_mb=round(len(weights) / (1024 * 1024), 2),
            status=ModelStatus.STAGING,
            trained_by=actor.id,
            **{k: v for k, v in metadata.items() if v is not None},
        )
        self._session.add(model)
        await self._session.flush()
        await self._audit.log(
            action="MODEL_REGISTERED",
            entity_type="ai_models",
            entity_id=model.id,
            user_id=actor.id,
            new_value={"name": name, "version": version, "size_mb": float(model.model_size_mb)},
        )
        await self._session.commit()
        await self._session.refresh(model)
        log.info("model_registered", model_id=str(model.id), name=name, version=version)
        return model

    # --- promotion (SM4: STAGING -> PRODUCTION, single active) -----------------
    async def promote(self, model_id: uuid.UUID, actor: User) -> AiModel:
        model = (
            await self._session.execute(select(AiModel).where(AiModel.id == model_id))
        ).scalar_one_or_none()
        if model is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Model {model_id} not found")
        if model.is_active:
            raise HTTPException(status.HTTP_409_CONFLICT, "Model is already in production")

        # One transaction: retire the incumbent, crown the successor.
        # uq_one_active_model would reject any state with two actives.
        await self._session.execute(
            update(AiModel)
            .where(AiModel.is_active.is_(True))
            .values(
                is_active=False,
                status=ModelStatus.DEPRECATED,
                deprecated_at=datetime.now(UTC),
            )
        )
        model.is_active = True
        model.status = ModelStatus.PRODUCTION
        model.deployed_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.log(
            action="MODEL_PROMOTED",
            entity_type="ai_models",
            entity_id=model.id,
            user_id=actor.id,
            new_value={"name": model.name, "version": model.version},
        )
        await self._session.commit()
        await self._session.refresh(model)
        log.info("model_promoted", model_id=str(model.id))
        return model

    # --- retrieval -------------------------------------------------------------
    async def get_active(self) -> AiModel | None:
        stmt = select(AiModel).where(AiModel.is_active.is_(True))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list(self) -> list[AiModel]:
        stmt = select(AiModel).order_by(AiModel.trained_at.desc())
        return list((await self._session.execute(stmt)).scalars().all())

    async def load_artifacts(self, model: AiModel) -> tuple[bytes, dict[str, str]]:
        """Download weights + class mapping from MinIO."""
        if not model.weights_path:
            raise HTTPException(status.HTTP_409_CONFLICT, "Model has no weights_path")
        bucket, _, object_name = model.weights_path.partition("/")
        weights = await self._storage.get_object(bucket, object_name)
        prefix = object_name.rsplit("/", 1)[0]
        try:
            config_raw = await self._storage.get_object(bucket, f"{prefix}/model_config.json")
            mapping = json.loads(config_raw).get("class_mapping", {})
        except Exception:  # config absent: fall back to defaults
            mapping = {}
        return weights, mapping
