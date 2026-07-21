"""RecommendationService — LangGraph pipeline + XAI (SD05, Steps 1+3).

Chain: analysis + pci_scores
    -> LangGraph [RuleEngine -> RAG retrieve -> Gemini narrate]
    -> maintenance_recommendations (EN_ATTENTE, rule #1 HITL)
    -> xai_explanations (rules, normative refs, priority breakdown, agents)

The strategy is ALWAYS the deterministic RuleEngine's; Gemini only narrates and
grounds. normative_refs come from the RAG (rule #6). If no LLM key / no RAG hit,
the pipeline degrades gracefully to the rule justification and flags the gap.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.agents.recommendation_pipeline import run_pipeline
from app.ai.engines.rule_engine import AnalysisContext
from app.db.models.inspection import AnalysisResult, PciScore, XaiExplanation
from app.db.models.maintenance import MaintenanceRecommendation, Rule
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository

log = structlog.get_logger("app.services.recommendation")


class RecommendationService:
    def __init__(self, session: AsyncSession, rag_search=None, llm_provider=None) -> None:
        self._session = session
        self._rag_search = rag_search
        self._llm = llm_provider
        self._audit = AuditRepository(session)

    async def _default_rag(self, query: str) -> list[dict]:
        return []

    async def _default_llm(self, *, system: str, prompt: str) -> str:
        return ""  # forces fallback to rule justification

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
                status.HTTP_404_NOT_FOUND, f"Analysis result {analysis_result_id} not found"
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

        # --- LangGraph pipeline (deterministic decision + grounded narration) ---
        result = await run_pipeline(
            ctx=ctx,
            rules=rules,
            rag_search=self._rag_search or self._default_rag,
            llm_generate=(self._llm.generate if self._llm is not None else self._default_llm),
        )
        decision = result.decision

        # --- XAI record ---
        xai = XaiExplanation(
            rules_applied=[{"code": decision.rule_code, "name": decision.rule_name}],
            normative_refs=result.normative_refs,
            priority_breakdown={
                "pci": ctx.pci,
                "severity": ctx.severity_level.value,
                "priority": ctx.priority_level.value,
                "dominant_type": ctx.dominant_damage_type,
                "detections": ctx.total_detections,
            },
            confidence_score=analysis.recommendation_confidence,
            severity_justification=(
                f"PCI {ctx.pci:.2f} classé {ctx.severity_level.value} "
                f"(priorité {ctx.priority_level.value})."
            ),
            strategy_justification=result.justification,
            agents_involved=result.agents_involved,
        )
        self._session.add(xai)
        await self._session.flush()

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
            justification=result.justification,
            normative_refs=result.normative_refs,
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
                "normative_refs": len(result.normative_refs),
                "missing_refs": result.missing_normative_refs,
            },
        )
        await self._session.commit()
        await self._session.refresh(rec)
        log.info(
            "recommendation_generated",
            recommendation_id=str(rec.id),
            strategy=decision.strategy.value,
            refs=len(result.normative_refs),
            missing_refs=result.missing_normative_refs,
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
