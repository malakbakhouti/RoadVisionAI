"""InspectionService — business logic of the inspection workflow (SD02, UC1).

Transaction ownership: this service commits; repositories only flush.
Critical rules enforced here:
  #3 async 202: /analyse never blocks — it flips the state machine and returns
     immediately (worker dispatch arrives with the AI pipeline step).
  #4 optimistic locking on PATCH (409 on stale version).
  #5 soft delete only.
"""

import io
import uuid

import structlog
from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.models.enums import InspectionStatus
from app.db.models.inspection import Inspection
from app.db.models.road import RoadImage
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.inspection_repository import InspectionRepository
from app.schemas.inspection import (
    AnalysisAccepted,
    InspectionCreate,
    InspectionUpdate,
)
from app.services.storage_service import StorageService

log = structlog.get_logger("app.services.inspection")

ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png"}
MAX_IMAGE_BYTES = 25 * 1024 * 1024  # aligned with nginx client_max_body_size


class InspectionService:
    def __init__(self, session: AsyncSession, settings: Settings, storage: StorageService) -> None:
        self._session = session
        self._settings = settings
        self._storage = storage
        self._repo = InspectionRepository(session)
        self._audit = AuditRepository(session)

    # --- CRUD -------------------------------------------------------------------
    async def create(self, data: InspectionCreate, actor: User) -> Inspection:
        if not await self._repo.road_section_exists(data.road_section_id):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Road section {data.road_section_id} not found"
            )
        inspection = Inspection(
            road_section_id=data.road_section_id,
            created_by=actor.id,
            weather_cond=data.weather_cond,
            notes=data.notes,
            **({"inspection_date": data.inspection_date} if data.inspection_date else {}),
        )
        await self._repo.add(inspection)
        await self._audit.log(
            action="INSPECTION_CREATED",
            entity_type="inspections",
            entity_id=inspection.id,
            user_id=actor.id,
        )
        await self._session.commit()
        await self._session.refresh(inspection)
        log.info("inspection_created", inspection_id=str(inspection.id))
        return inspection

    async def get_detail(self, inspection_id: uuid.UUID) -> Inspection:
        inspection = await self._repo.get_detail(inspection_id)
        if inspection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inspection {inspection_id} not found")
        return inspection

    async def list(self, **filters) -> tuple[list[Inspection], int]:
        return await self._repo.list_filtered(**filters)

    async def update(
        self, inspection_id: uuid.UUID, data: InspectionUpdate, actor: User
    ) -> Inspection:
        await self._repo.get_or_404(inspection_id)
        values = data.model_dump(exclude={"version"}, exclude_none=True)
        if values:
            # Rule #4 — WHERE version = expected, 409 on stale (trigger bumps version)
            await self._repo.update_with_version(inspection_id, data.version, values)
            await self._audit.log(
                action="INSPECTION_UPDATED",
                entity_type="inspections",
                entity_id=inspection_id,
                user_id=actor.id,
                new_value=values,
            )
            await self._session.commit()
        return await self._repo.get_or_404(inspection_id)

    async def soft_delete(self, inspection_id: uuid.UUID, actor: User) -> None:
        await self._repo.soft_delete(inspection_id)  # rule #5
        await self._audit.log(
            action="INSPECTION_DELETED",
            entity_type="inspections",
            entity_id=inspection_id,
            user_id=actor.id,
        )
        await self._session.commit()

    # --- Images (SD02 / APISpec §7) -----------------------------------------------
    async def upload_image(
        self,
        inspection_id: uuid.UUID,
        upload: UploadFile,
        *,
        gps_lat: float | None,
        gps_lng: float | None,
        actor: User,
    ) -> RoadImage:
        inspection = await self._repo.get_or_404(inspection_id)

        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"Unsupported image type '{content_type}' (allowed: JPEG, PNG)",
            )
        data = await upload.read()
        if len(data) == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Empty file")
        if len(data) > MAX_IMAGE_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"Image exceeds {MAX_IMAGE_BYTES // (1024 * 1024)} MB limit",
            )

        # Dimensions via Pillow (also validates the payload really is an image)
        try:
            with Image.open(io.BytesIO(data)) as img:
                width, height = img.size
        except Exception as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is not a valid image") from exc

        stored = await self._storage.put_image(
            inspection_id=inspection.id,
            filename=upload.filename or "image.jpg",
            data=data,
            content_type=content_type,
        )
        image = RoadImage(
            inspection_id=inspection.id,
            filename=upload.filename or "image.jpg",
            storage_path=stored.storage_path,
            file_size=len(data),
            mime_type=content_type,
            width=width,
            height=height,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            sequence_num=await self._repo.next_sequence_num(inspection.id),
        )
        self._session.add(image)
        await self._session.flush()
        await self._audit.log(
            action="IMAGE_UPLOADED",
            entity_type="road_images",
            entity_id=image.id,
            user_id=actor.id,
            new_value={"inspection_id": str(inspection.id), "filename": image.filename},
        )
        await self._session.commit()
        await self._session.refresh(image)
        log.info("image_uploaded", inspection_id=str(inspection.id), image_id=str(image.id))
        return image

    # --- Analyse (async 202 — SD03 entry point) --------------------------------------
    async def request_analysis(self, inspection_id: uuid.UUID, actor: User) -> AnalysisAccepted:
        inspection = await self._repo.get_detail(inspection_id)
        if inspection is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inspection {inspection_id} not found")
        if not inspection.road_images:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Cannot analyse an inspection without images",
            )
        if inspection.status not in (InspectionStatus.EN_ATTENTE, InspectionStatus.ERREUR):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Inspection is {inspection.status.value}; analysis can only start "
                "from EN_ATTENTE or ERREUR",
            )
        # State machine SM1: EN_ATTENTE -> EN_COURS. Rule #3: respond 202 now;
        # the AI worker dispatch plugs in here in the AI pipeline step.
        await self._repo.update_with_version(
            inspection.id, inspection.version, {"status": InspectionStatus.EN_COURS}
        )
        await self._audit.log(
            action="ANALYSIS_REQUESTED",
            entity_type="inspections",
            entity_id=inspection.id,
            user_id=actor.id,
        )
        await self._session.commit()
        return AnalysisAccepted(
            inspection_id=inspection.id,
            status=InspectionStatus.EN_COURS,
            detail="Analysis scheduled — poll GET /api/inspections/{id} for status",
        )
