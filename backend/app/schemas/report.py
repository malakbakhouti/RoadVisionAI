"""Report DTOs — APISpec v1.0 (SD06). PDF generation is a placeholder in Step 5;
the full 12-section ReportLab builder arrives with the AI pipeline."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ReportGenerateRequest(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    executive_summary: str | None = None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    plan_id: uuid.UUID
    xai_explanation_id: uuid.UUID | None = None
    title: str
    executive_summary: str | None = None
    estimated_budget: Decimal | None = None
    estimated_duration: int | None = None
    normative_refs: list = []
    file_path: str | None = None
    file_size: int | None = None
    generated_at: datetime
    created_at: datetime
    download_url: str | None = None


class ReportListResponse(BaseModel):
    items: list[ReportResponse]
    total: int
    limit: int
    offset: int
