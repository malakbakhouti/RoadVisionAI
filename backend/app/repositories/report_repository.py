"""Report data access (inspection_reports — one report per maintenance plan)."""

import uuid

from sqlalchemy import select

from app.db.models.inspection import InspectionReport
from app.db.models.maintenance import MaintenancePlan
from app.repositories.base import BaseRepository


class ReportRepository(BaseRepository[InspectionReport]):
    model = InspectionReport

    async def get_by_plan(self, plan_id: uuid.UUID) -> InspectionReport | None:
        stmt = select(InspectionReport).where(InspectionReport.plan_id == plan_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def plan_exists(self, plan_id: uuid.UUID) -> bool:
        stmt = select(MaintenancePlan.id).where(MaintenancePlan.id == plan_id)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None
