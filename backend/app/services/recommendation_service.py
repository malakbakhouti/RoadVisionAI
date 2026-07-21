"""RecommendationService — deterministic recommendation generation (SD05, Step 1).

Chain: analysis_results + pci_scores  ->  RuleEngine  ->  maintenance_recommendations
Status is always EN_ATTENTE: rule #1 (Human-in-the-Loop) means no recommendation
is ever born validated. normative_refs starts empty — the RAG step grounds it.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.engines.rule_engine import AnalysisContext, evaluate
from app.db.models.inspection import AnalysisResult, PciScore
from app.db.models.maintenance import MaintenanceRecommendation, Rule
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository

log = structlog.get_logger("app.services.recommendation")


class RecommendationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._audit = AuditRepository(session)

    async def generate_for_analysis(
        self, analysis_result_id: uuid.UUID, actor: User
    ) -> MaintenanceRecommendation:
        analysis = (
            await self._session.execute(
                select(AnalysisResult).where(AnalysisResult.id == analysis_result_id)
            )
        ).scalar_one_or_none()
        if analysis is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"Analysis result {analysis_result_id} not found",
            )
        existing = (
            await self._session.execute(
                select(MaintenanceRecommendation.id).where(
                    MaintenanceRecommendation.analysis_result_id == analysis_result_id
                )
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"A recommendation already exists for this analysis ({existing})",
            )
        pci = (
            await self._session.execute(
                select(PciScore).where(PciScore.inspection_id == analysis.inspection_id)
            )
        ).scalar_one_or_none()
        if pci is None:
            raise HTTPException(status.HTTP_409_CONFLICT, "No PCI score for this inspection yet")

        rules = list(
            (await self._session.execute(select(Rule).where(Rule.is_active.is_(True)))).scalars()
        )
        ctx = AnalysisContext(
            pci=float(pci.score),
            severity_level=pci.severity_level,
            priority_level=pci.priority_level,
            dominant_damage_type=analysis.dominant_damage_type,
            total_detections=analysis.total_detections or 0,
        )
        decision = evaluate(rules, ctx)  # deterministic — LLM narrates later

        rec = MaintenanceRecommendation(
            analysis_result_id=analysis_result_id,
            strategy=decision.strategy,
            estimated_cost_min=decision.cost_min_mad,
            estimated_cost_max=decision.cost_max_mad,
            estimated_days=decision.estimated_days,
            deadline=(
                (datetime.now(UTC) + timedelta(days=decision.deadline_days)).date()
                if decision.deadline_days
                else None
            ),
            justification=(
                f"[Règle {decision.rule_code} — {decision.rule_name}] {decision.justification}"
            ),
            confidence=analysis.recommendation_confidence,
        )
        self._session.add(rec)
        await self._session.flush()
        await self._audit.log(
            action="RECOMMENDATION_GENERATED",
            entity_type="maintenance_recommendations",
            entity_id=rec.id,
            user_id=actor.id,
            new_value={
                "strategy": decision.strategy.value,
                "rule": decision.rule_code,
                "pci": ctx.pci,
            },
        )
        await self._session.commit()
        await self._session.refresh(rec)
        log.info(
            "recommendation_generated",
            recommendation_id=str(rec.id),
            strategy=decision.strategy.value,
            rule=decision.rule_code,
        )
        return rec

    async def get(self, rec_id: uuid.UUID) -> MaintenanceRecommendation:
        rec = (
            await self._session.execute(
                select(MaintenanceRecommendation).where(MaintenanceRecommendation.id == rec_id)
            )
        ).scalar_one_or_none()
        if rec is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Recommendation {rec_id} not found")
        return rec

    async def list_pending(self, *, limit: int, offset: int):
        from sqlalchemy import func

        base = select(MaintenanceRecommendation).where(
            MaintenanceRecommendation.status == "EN_ATTENTE"
        )
        total = (
            await self._session.execute(select(func.count()).select_from(base.subquery()))
        ).scalar_one()
        rows = (
            await self._session.execute(
                base.order_by(MaintenanceRecommendation.created_at.asc())
                .limit(limit)
                .offset(offset)
            )
        ).scalars()
        return list(rows.all()), total
