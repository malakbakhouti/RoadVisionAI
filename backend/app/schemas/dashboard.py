"""Dashboard DTOs — CQRS read model (SD08, APISpec §6.5).

The dashboard NEVER aggregates transactional tables at request time: it reads
pre-computed dashboard_snapshots / damage_type_stats / pci_trends rows.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from app.db.models.enums import TrendDirection


class SnapshotResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    snapshot_date: date
    total_inspections: int | None = None
    total_detections: int | None = None
    avg_pci_score: Decimal | None = None
    critical_sections: int | None = None
    total_budget: Decimal | None = None
    coverage_rate: Decimal | None = None
    region: str | None = None
    province: str | None = None
    created_at: datetime


class DamageTypeStatResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    damage_type: str
    count: int
    percentage: Decimal | None = None
    avg_severity: Decimal | None = None
    period: str | None = None


class PciTrendPoint(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    road_section_id: uuid.UUID
    pci_value: Decimal
    recorded_date: date
    trend: TrendDirection | None = None


class DashboardSummaryResponse(BaseModel):
    snapshot: SnapshotResponse | None
    damage_stats: list[DamageTypeStatResponse]
    message: str | None = None
