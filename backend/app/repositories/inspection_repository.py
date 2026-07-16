"""Inspection data access — filters, pagination, image loading (SD02)."""

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.db.models.enums import InspectionStatus
from app.db.models.inspection import Inspection
from app.db.models.road import RoadImage, RoadSection
from app.repositories.base import BaseRepository


class InspectionRepository(BaseRepository[Inspection]):
    model = Inspection

    async def get_detail(self, inspection_id: uuid.UUID) -> Inspection | None:
        stmt = (
            self._base_query()
            .where(Inspection.id == inspection_id)
            .options(selectinload(Inspection.road_images))
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def list_filtered(
        self,
        *,
        status: InspectionStatus | None = None,
        road_section_id: uuid.UUID | None = None,
        created_by: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Inspection], int]:
        stmt = self._base_query()
        if status is not None:
            stmt = stmt.where(Inspection.status == status)
        if road_section_id is not None:
            stmt = stmt.where(Inspection.road_section_id == road_section_id)
        if created_by is not None:
            stmt = stmt.where(Inspection.created_by == created_by)

        total = (
            await self._session.execute(select(func.count()).select_from(stmt.subquery()))
        ).scalar_one()
        rows = (
            await self._session.execute(
                stmt.order_by(Inspection.inspection_date.desc()).limit(limit).offset(offset)
            )
        ).scalars()
        return list(rows.all()), total

    async def road_section_exists(self, road_section_id: uuid.UUID) -> bool:
        stmt = select(func.count()).where(
            RoadSection.id == road_section_id, RoadSection.deleted_at.is_(None)
        )
        return (await self._session.execute(stmt)).scalar_one() > 0

    async def next_sequence_num(self, inspection_id: uuid.UUID) -> int:
        stmt = select(func.coalesce(func.max(RoadImage.sequence_num), 0)).where(
            RoadImage.inspection_id == inspection_id
        )
        return (await self._session.execute(stmt)).scalar_one() + 1
