"""DashboardService — CQRS read + on-demand snapshot trigger (SD08)."""

import uuid
from datetime import date

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard import (
    DamageTypeStatResponse,
    DashboardSummaryResponse,
    PciTrendPoint,
    SnapshotResponse,
)
from app.workers.snapshot_job import compute_snapshot

log = structlog.get_logger("app.services.dashboard")


class DashboardService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = DashboardRepository(session)
        self._audit = AuditRepository(session)

    async def summary(
        self, *, region: str | None = None, province: str | None = None
    ) -> DashboardSummaryResponse:
        snapshot = await self._repo.latest_snapshot(region=region, province=province)
        if snapshot is None:
            return DashboardSummaryResponse(
                snapshot=None,
                damage_stats=[],
                message="No snapshot computed yet — POST /api/dashboard/snapshots (admin)",
            )
        stats = await self._repo.damage_stats(snapshot.id)
        return DashboardSummaryResponse(
            snapshot=SnapshotResponse.model_validate(snapshot),
            damage_stats=[DamageTypeStatResponse.model_validate(s) for s in stats],
        )

    async def pci_trends(
        self,
        *,
        road_section_id: uuid.UUID | None,
        date_from: date | None,
        date_to: date | None,
    ) -> list[PciTrendPoint]:
        rows = await self._repo.pci_trends(
            road_section_id=road_section_id, date_from=date_from, date_to=date_to
        )
        return [PciTrendPoint.model_validate(r) for r in rows]

    async def trigger_snapshot(self, actor: User) -> SnapshotResponse:
        snapshot = await compute_snapshot(self._session)
        await self._audit.log(
            action="SNAPSHOT_COMPUTED",
            entity_type="dashboard_snapshots",
            entity_id=snapshot.id,
            user_id=actor.id,
        )
        await self._session.commit()
        await self._session.refresh(snapshot)
        return SnapshotResponse.model_validate(snapshot)
