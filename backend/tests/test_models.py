"""Step 3 — every ORM model must SELECT cleanly against the real v4.2 database."""

import app.db.models as m
from app.db.session import get_session_factory, init_engine
from sqlalchemy import func, select

ALL_MODELS = [
    m.User, m.Role, m.UserRoleLink, m.AuditLog, m.DamageType, m.GisLocation,
    m.RoadSection, m.RoadImage, m.Inspection, m.AnalysisResult, m.DamageDetection,
    m.PciScore, m.XaiExplanation, m.InspectionReport, m.Rule,
    m.MaintenanceRecommendation, m.MaintenancePlan, m.KnowledgeDocument,
    m.Embedding, m.AiModel, m.DashboardSnapshot, m.DamageTypeStat, m.PciTrend,
    m.Notification,
]


async def test_all_24_models_are_mapped() -> None:
    from app.db.base import Base

    assert len(Base.metadata.tables) == 24


async def test_every_model_selects_against_live_schema() -> None:
    init_engine()
    async with get_session_factory()() as session:
        for model in ALL_MODELS:
            (await session.execute(select(func.count()).select_from(model))).scalar_one()
            (await session.execute(select(model).limit(1))).scalars().first()


async def test_seeded_damage_types_match_cdc() -> None:
    init_engine()
    async with get_session_factory()() as session:
        rows = (await session.execute(select(m.DamageType))).scalars().all()
    weights = {r.code: float(r.pci_weight) for r in rows}
    assert weights["POTHOLE"] == 0.350
    assert weights["STRIPING"] == 0.050
    assert len(weights) == 8
