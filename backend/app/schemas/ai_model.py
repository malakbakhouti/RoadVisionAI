"""AI model registry DTOs — UC3 (administration), SM4 lifecycle."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import ModelStatus


class ModelRegisterMetadata(BaseModel):
    """Optional training metadata carried at registration (JSON form field)."""

    description: str | None = None
    dataset_name: str | None = None
    dataset_version: str | None = None
    dataset_size: int | None = Field(default=None, ge=1)
    num_classes: int | None = Field(default=None, ge=1)
    epochs: int | None = Field(default=None, ge=1)
    batch_size: int | None = Field(default=None, ge=1)
    image_size: int | None = Field(default=None, ge=32)
    map50: float | None = Field(default=None, ge=0, le=1)
    map50_95: float | None = Field(default=None, ge=0, le=1)
    precision_score: float | None = Field(default=None, ge=0, le=1)
    recall_score: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None


class AiModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: uuid.UUID
    name: str
    version: str
    framework: str
    status: ModelStatus
    is_active: bool
    weights_path: str | None = None
    model_size_mb: Decimal | None = None
    dataset_name: str | None = None
    dataset_version: str | None = None
    num_classes: int | None = None
    epochs: int | None = None
    map50: Decimal | None = None
    map50_95: Decimal | None = None
    trained_at: datetime
    deployed_at: datetime | None = None
    deprecated_at: datetime | None = None
