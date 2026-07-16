"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import decimal
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.road import RoadSection

from app.db.models.enums import (
    TrendDirection,
)


class DashboardSnapshot(Base):
    __tablename__ = "dashboard_snapshots"
    __table_args__ = (
        CheckConstraint(
            "avg_pci_score IS NULL OR avg_pci_score >= 0::numeric AND avg_pci_score <= 100::numeric",
            name="chk_snapshot_avg_pci",
        ),
        CheckConstraint(
            "coverage_rate >= 0::numeric AND coverage_rate <= 100::numeric",
            name="dashboard_snapshots_coverage_rate_check",
        ),
        CheckConstraint("critical_sections >= 0", name="chk_snapshot_critical"),
        CheckConstraint("total_detections >= 0", name="chk_snapshot_detections"),
        CheckConstraint("total_inspections >= 0", name="chk_snapshot_inspections"),
        PrimaryKeyConstraint("id", name="dashboard_snapshots_pkey"),
        UniqueConstraint("snapshot_date", "region", "province", name="uq_snapshot_date_region"),
        Index("idx_snapshot_date", "snapshot_date"),
        Index("idx_snapshot_region", "region", "province"),
        {
            "comment": "Daily KPI snapshots for the Dashboard. Computed by a background "
            "job. Not real-time."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    snapshot_date: Mapped[datetime.date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    total_inspections: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    total_detections: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    critical_sections: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    avg_pci_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    total_budget: Mapped[decimal.Decimal | None] = mapped_column(Numeric(16, 2))
    coverage_rate: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 2),
        comment="Percentage of the road network covered by at least one inspection. Range [0,100].",
    )
    region: Mapped[str | None] = mapped_column(
        String(100), comment="Administrative region filter. NULL means national aggregate."
    )
    province: Mapped[str | None] = mapped_column(
        String(100), comment="Administrative province filter. NULL means regional aggregate."
    )

    damage_type_stats: Mapped[list["DamageTypeStat"]] = relationship(
        "DamageTypeStat", back_populates="snapshot"
    )
    pci_trends: Mapped[list["PciTrend"]] = relationship("PciTrend", back_populates="snapshot")


class DamageTypeStat(Base):
    __tablename__ = "damage_type_stats"
    __table_args__ = (
        CheckConstraint(
            "avg_severity IS NULL OR avg_severity >= 0::numeric AND avg_severity <= 1::numeric",
            name="damage_type_stats_avg_severity_check",
        ),
        CheckConstraint("count >= 0", name="chk_dts_count"),
        CheckConstraint(
            "percentage >= 0::numeric AND percentage <= 100::numeric",
            name="damage_type_stats_percentage_check",
        ),
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["dashboard_snapshots.id"],
            ondelete="CASCADE",
            name="damage_type_stats_snapshot_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="damage_type_stats_pkey"),
        Index("idx_dts_snapshot", "snapshot_id"),
        {"comment": "Aggregated damage detection counts per type per dashboard snapshot."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    damage_type: Mapped[str] = mapped_column(
        String(200),
        nullable=False,
        comment="Damage type name (denormalised from damage_types.name for snapshot stability).",
    )
    count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    percentage: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 2))
    avg_severity: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4),
        comment="Average severity score for this damage type in the snapshot period. Range [0,1].",
    )
    period: Mapped[str | None] = mapped_column(String(50))

    snapshot: Mapped["DashboardSnapshot"] = relationship(
        "DashboardSnapshot", back_populates="damage_type_stats"
    )


class PciTrend(Base):
    __tablename__ = "pci_trends"
    __table_args__ = (
        CheckConstraint(
            "pci_value >= 0::numeric AND pci_value <= 100::numeric",
            name="pci_trends_pci_value_check",
        ),
        ForeignKeyConstraint(
            ["road_section_id"],
            ["road_sections.id"],
            ondelete="CASCADE",
            name="pci_trends_road_section_id_fkey",
        ),
        ForeignKeyConstraint(
            ["snapshot_id"],
            ["dashboard_snapshots.id"],
            ondelete="CASCADE",
            name="pci_trends_snapshot_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="pci_trends_pkey"),
        Index("idx_pci_trend_date", "recorded_date"),
        Index("idx_pci_trend_section", "road_section_id"),
        Index("idx_pci_trends_snapshot", "snapshot_id"),
        {
            "comment": "Historical PCI values per road section. Feeds the predictive "
            "maintenance module."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    road_section_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    pci_value: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    recorded_date: Mapped[datetime.date] = mapped_column(
        Date, nullable=False, server_default=text("CURRENT_DATE")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    trend: Mapped[TrendDirection | None] = mapped_column(
        Enum(
            TrendDirection,
            values_callable=lambda cls: [member.value for member in cls],
            name="trend_direction",
        ),
        comment="PCI evolution direction compared to previous snapshot for this road section.",
    )

    road_section: Mapped["RoadSection"] = relationship("RoadSection", back_populates="pci_trends")
    snapshot: Mapped["DashboardSnapshot"] = relationship(
        "DashboardSnapshot", back_populates="pci_trends"
    )
