"""Recommendation endpoints — SD05 (generation; HITL validation arrives Step 4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.dependencies import (
    CurrentUserDep,
    DbSessionDep,
    SettingsDep,
    get_chroma_client,
    get_embedder,
    get_llm_provider,
    require_roles,
)
from app.db.models.user import User, UserRole
from app.schemas.recommendation import (
    RecommendationListResponse,
    RecommendationResponse,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["recommendations"])

EngineerOrAdminDep = Annotated[
    User, Depends(require_roles(UserRole.ROAD_ENGINEER, UserRole.ADMINISTRATOR))
]


@router.post(
    "/analysis-results/{analysis_result_id}/recommendation",
    response_model=RecommendationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate the maintenance recommendation (RuleEngine, deterministic)",
)
async def generate_recommendation(
    analysis_result_id: uuid.UUID,
    actor: EngineerOrAdminDep,
    db: DbSessionDep,
    settings: SettingsDep,
) -> RecommendationResponse:
    # Build the RAG search callable (KnowledgeService) + optional Gemini
    from app.ai.rag.knowledge_service import KnowledgeService

    llm = get_llm_provider(settings)

    async def rag_search(query: str) -> list:
        # RAG is best-effort: if the vector store is unreachable, the pipeline
        # degrades gracefully and flags missing normative refs (rule #6).
        try:
            chroma = get_chroma_client(settings)
            embedder = get_embedder(settings)
            knowledge = KnowledgeService(db, settings, chroma, embedder)
            return await knowledge.search(query)
        except Exception:
            return []

    rec = await RecommendationService(
        db, rag_search=rag_search, llm_provider=llm
    ).generate_for_analysis(analysis_result_id, actor)
    return RecommendationResponse.model_validate(rec)


@router.get(
    "/recommendations",
    response_model=RecommendationListResponse,
    summary="List pending recommendations (HITL inbox)",
)
async def list_recommendations(
    user: CurrentUserDep,
    db: DbSessionDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RecommendationListResponse:
    items, total = await RecommendationService(db).list_pending(limit=limit, offset=offset)
    return RecommendationListResponse(
        items=[RecommendationResponse.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/recommendations/{rec_id}",
    response_model=RecommendationResponse,
    summary="Recommendation detail",
)
async def get_recommendation(
    rec_id: uuid.UUID, user: CurrentUserDep, db: DbSessionDep
) -> RecommendationResponse:
    rec = await RecommendationService(db).get(rec_id)
    return RecommendationResponse.model_validate(rec)
