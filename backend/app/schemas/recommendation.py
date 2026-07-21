"""Recommendation DTOs — SD05."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import MaintenanceStrategy, RecStatus


class RecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    analysis_result_id: uuid.UUID
    strategy: MaintenanceStrategy
    estimated_cost_min: Decimal | None = None
    estimated_cost_max: Decimal | None = None
    estimated_days: int | None = None
    deadline: date | None = None
    justification: str | None = None
    normative_refs: list = []
    confidence: Decimal | None = None
    status: RecStatus
    validated_by: uuid.UUID | None = None
    validated_at: datetime | None = None
    rejection_reason: str | None = None
    created_at: datetime
    version: int


class RecommendationListResponse(BaseModel):
    items: list[RecommendationResponse]
    total: int
    limit: int
    offset: int
