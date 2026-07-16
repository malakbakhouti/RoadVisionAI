"""Dashboard read-side repository (CQRS — SD08)."""

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dashboard import DamageTypeStat, DashboardSnapshot, PciTrend


class DashboardRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_snapshot(
        self, *, region: str | None = None, province: str | None = None
    ) -> DashboardSnapshot | None:
        # snapshot_date is a DATE: same-day snapshots tie, so created_at breaks the tie
        stmt = select(DashboardSnapshot).order_by(
            DashboardSnapshot.snapshot_date.desc(), DashboardSnapshot.created_at.desc()
        )
        if region is not None:
            stmt = stmt.where(DashboardSnapshot.region == region)
        if province is not None:
            stmt = stmt.where(DashboardSnapshot.province == province)
        return (await self._session.execute(stmt.limit(1))).scalar_one_or_none()

    async def damage_stats(self, snapshot_id: uuid.UUID) -> list[DamageTypeStat]:
        stmt = (
            select(DamageTypeStat)
            .where(DamageTypeStat.snapshot_id == snapshot_id)
            .order_by(DamageTypeStat.count.desc())
        )
        return list((await self._session.execute(stmt)).scalars().all())

    async def pci_trends(
        self,
        *,
        road_section_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 500,
    ) -> list[PciTrend]:
        stmt = select(PciTrend).order_by(PciTrend.recorded_date.asc())
        if road_section_id is not None:
            stmt = stmt.where(PciTrend.road_section_id == road_section_id)
        if date_from is not None:
            stmt = stmt.where(PciTrend.recorded_date >= date_from)
        if date_to is not None:
            stmt = stmt.where(PciTrend.recorded_date <= date_to)
        return list((await self._session.execute(stmt.limit(limit))).scalars().all())
