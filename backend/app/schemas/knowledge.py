"""Knowledge / RAG DTOs — SD07."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source: str | None = None
    doc_type: str
    language: str
    version: str | None = None
    page_count: int | None = None
    status: str
    embedding_count: int
    uploaded_at: datetime


class RagSearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    top_k: int | None = Field(default=None, ge=1, le=20)
    threshold: float | None = Field(default=None, ge=0, le=1)


class RagHit(BaseModel):
    text: str
    similarity: float
    document_id: str
    title: str
    doc_type: str
    page_start: int
    page_end: int


class RagSearchResponse(BaseModel):
    query: str
    hits: list[RagHit]
