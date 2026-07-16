"""Inspection DTOs — contracts of APISpec v1.0 §6.2 / §7 (SD02)."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.db.models.enums import InspectionStatus


class InspectionCreate(BaseModel):
    road_section_id: uuid.UUID
    inspection_date: datetime | None = None
    weather_cond: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class InspectionUpdate(BaseModel):
    """PATCH body — optimistic locking: expected `version` is mandatory (rule #4)."""

    version: int = Field(ge=1)
    weather_cond: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class RoadImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    filename: str
    storage_path: str
    file_size: int | None = None
    mime_type: str
    width: int | None = None
    height: int | None = None
    gps_lat: Decimal | None = None
    gps_lng: Decimal | None = None
    sequence_num: int
    captured_at: datetime
    download_url: str | None = None  # presigned, filled by the service


class InspectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    road_section_id: uuid.UUID
    created_by: uuid.UUID
    validated_by: uuid.UUID | None = None
    status: InspectionStatus
    inspection_date: datetime
    weather_cond: str | None = None
    notes: str | None = None
    version: int
    created_at: datetime
    updated_at: datetime


class InspectionDetailResponse(InspectionResponse):
    images: list[RoadImageResponse] = []


class InspectionListResponse(BaseModel):
    items: list[InspectionResponse]
    total: int
    limit: int
    offset: int


class AnalysisAccepted(BaseModel):
    """202 payload of POST /inspections/{id}/analyse (async pattern, rule #3)."""

    inspection_id: uuid.UUID
    status: InspectionStatus
    detail: str
