"""Dashboard snapshot job — CQRS write side (SD08).

Aggregates the transactional tables into one dashboard_snapshots row plus its
damage_type_stats children. Designed to run daily (worker dispatch arrives
with the workers step) and to be triggerable on demand by an administrator —
which also makes the dashboard demonstrable before the AI pipeline exists.
"""

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.dashboard import DamageTypeStat, DashboardSnapshot
from app.db.models.inspection import DamageDetection, Inspection, PciScore
from app.db.models.road import DamageType

log = structlog.get_logger("app.workers.snapshot")

CRITICAL_PCI_THRESHOLD = 40  # ASTM D6433: PCI < 40 = poor/very poor


async def compute_snapshot(session: AsyncSession) -> DashboardSnapshot:
    """Aggregate live tables into a new snapshot (idempotent per run)."""
    total_inspections = (
        await session.execute(
            select(func.count()).select_from(Inspection).where(Inspection.deleted_at.is_(None))
        )
    ).scalar_one()
    total_detections = (
        await session.execute(select(func.count()).select_from(DamageDetection))
    ).scalar_one()
    avg_pci = (await session.execute(select(func.avg(PciScore.score)))).scalar_one()
    critical_sections = (
        await session.execute(
            select(func.count(func.distinct(Inspection.road_section_id)))
            .select_from(PciScore)
            .join(Inspection, Inspection.id == PciScore.inspection_id)
            .where(PciScore.score < CRITICAL_PCI_THRESHOLD)
        )
    ).scalar_one()

    snapshot = DashboardSnapshot(
        total_inspections=total_inspections,
        total_detections=total_detections,
        avg_pci_score=avg_pci,
        critical_sections=critical_sections,
    )
    session.add(snapshot)
    await session.flush()

    # Per-damage-type distribution
    rows = (
        await session.execute(
            select(DamageType.code, func.count(DamageDetection.id))
            .join(DamageDetection, DamageDetection.damage_type_id == DamageType.id)
            .group_by(DamageType.code)
        )
    ).all()
    total = sum(count for _, count in rows) or 1
    for code, count in rows:
        session.add(
            DamageTypeStat(
                snapshot_id=snapshot.id,
                damage_type=code,
                count=count,
                percentage=round(100 * count / total, 2),
            )
        )
    await session.flush()
    log.info(
        "snapshot_computed",
        snapshot_id=str(snapshot.id),
        inspections=total_inspections,
        detections=total_detections,
    )
    return snapshot
