"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import decimal
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    Boolean,
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
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.inspection import AnalysisResult, InspectionReport
    from app.db.models.user import User

from app.db.models.enums import (
    MaintenanceStrategy,
    PlanStatus,
    PriorityLevel,
    RecStatus,
)


class Rule(Base):
    __tablename__ = "rules"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM code) <> ''::text", name="chk_rule_code"),
        CheckConstraint("TRIM(BOTH FROM name) <> ''::text", name="chk_rule_name"),
        CheckConstraint("priority > 0", name="rules_priority_check"),
        CheckConstraint("updated_at >= created_at", name="chk_rules_updated_at"),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="SET NULL", name="rules_created_by_fkey"
        ),
        PrimaryKeyConstraint("id", name="rules_pkey"),
        UniqueConstraint("code", name="uq_rule_code"),
        Index("idx_rules_active", "is_active", postgresql_where="(is_active = true)"),
        Index("idx_rules_priority", "priority"),
        {
            "comment": "Business rules evaluated by RuleEngine (e.g. PCI<40 -> "
            "P1_URGENT). Configurable by Administrator."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    condition: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="Rule condition expression evaluated by the RuleEngine service.",
    )
    action: Mapped[str] = mapped_column(
        Text, nullable=False, comment="Action triggered when condition evaluates to true."
    )
    priority: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default=text("10"),
        comment="Evaluation order — lower value means higher priority.",
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)

    author: Mapped[Optional["User"]] = relationship("User", back_populates="rules")


class MaintenanceRecommendation(Base):
    __tablename__ = "maintenance_recommendations"
    __table_args__ = (
        CheckConstraint(
            "confidence >= 0::numeric AND confidence <= 1::numeric",
            name="maintenance_recommendations_confidence_check",
        ),
        CheckConstraint(
            "estimated_cost_max IS NULL OR estimated_cost_min IS NULL OR estimated_cost_max >= estimated_cost_min",
            name="maintenance_recommendations_check",
        ),
        CheckConstraint(
            "estimated_cost_min >= 0::numeric",
            name="maintenance_recommendations_estimated_cost_min_check",
        ),
        CheckConstraint(
            "estimated_days > 0", name="maintenance_recommendations_estimated_days_check"
        ),
        CheckConstraint(
            "normative_refs IS NULL OR jsonb_typeof(normative_refs) = 'array'::text",
            name="maintenance_recommendations_normative_refs_check",
        ),
        CheckConstraint(
            "rejected_at IS NULL OR rejected_at >= created_at", name="chk_rec_rejected_at"
        ),
        CheckConstraint(
            "status = 'VALIDEE'::rec_status AND validated_by IS NOT NULL AND validated_at IS NOT NULL OR status = 'REJETEE'::rec_status AND rejected_by IS NOT NULL AND rejected_at IS NOT NULL OR (status <> ALL (ARRAY['VALIDEE'::rec_status, 'REJETEE'::rec_status]))",
            name="chk_rec_validation",
        ),
        CheckConstraint("updated_at >= created_at", name="chk_rec_updated_at"),
        CheckConstraint(
            "validated_at IS NULL OR validated_at >= created_at", name="chk_rec_validated_at"
        ),
        ForeignKeyConstraint(
            ["analysis_result_id"],
            ["analysis_results.id"],
            ondelete="CASCADE",
            name="maintenance_recommendations_analysis_result_id_fkey",
        ),
        ForeignKeyConstraint(
            ["rejected_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="maintenance_recommendations_rejected_by_fkey",
        ),
        ForeignKeyConstraint(
            ["validated_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="maintenance_recommendations_validated_by_fkey",
        ),
        PrimaryKeyConstraint("id", name="maintenance_recommendations_pkey"),
        UniqueConstraint("analysis_result_id", name="uq_rec_analysis"),
        Index("idx_rec_created_at", "created_at"),
        Index(
            "idx_rec_pending", "created_at", postgresql_where="(status = 'EN_ATTENTE'::rec_status)"
        ),
        Index("idx_rec_rejected_by", "rejected_by", postgresql_where="(rejected_by IS NOT NULL)"),
        Index("idx_rec_status_strategy", "status", "strategy"),
        Index(
            "idx_rec_validated_by", "validated_by", postgresql_where="(validated_by IS NOT NULL)"
        ),
        {
            "comment": "1:1 with AnalysisResult. Generated by PlanningAgent, validated by "
            "RoadEngineer."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    analysis_result_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    strategy: Mapped[MaintenanceStrategy] = mapped_column(
        Enum(
            MaintenanceStrategy,
            values_callable=lambda cls: [member.value for member in cls],
            name="maintenance_strategy",
        ),
        nullable=False,
    )
    status: Mapped[RecStatus] = mapped_column(
        Enum(
            RecStatus,
            values_callable=lambda cls: [member.value for member in cls],
            name="rec_status",
        ),
        nullable=False,
        server_default=text("'EN_ATTENTE'::rec_status"),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    estimated_cost_min: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    estimated_cost_max: Mapped[decimal.Decimal | None] = mapped_column(Numeric(12, 2))
    estimated_days: Mapped[int | None] = mapped_column(Integer)
    deadline: Mapped[datetime.date | None] = mapped_column(Date)
    justification: Mapped[str | None] = mapped_column(Text)
    normative_refs: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment='JSON array of normative references cited by the RAG pipeline (e.g. ["ASTM D6433 §4.2", "DGR Art.7.3"]).',
    )
    confidence: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 4))
    validated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    validated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    rejected_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    rejected_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))

    analysis_result: Mapped["AnalysisResult"] = relationship(
        "AnalysisResult", back_populates="maintenance_recommendations"
    )
    rejector: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[rejected_by], back_populates="recommendations_rejected"
    )
    validator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[validated_by], back_populates="recommendations_validated"
    )
    maintenance_plans: Mapped["MaintenancePlan"] = relationship(
        "MaintenancePlan", uselist=False, back_populates="recommendation"
    )


class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"
    __table_args__ = (
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="chk_plan_dates",
        ),
        CheckConstraint("total_budget >= 0::numeric", name="maintenance_plans_total_budget_check"),
        CheckConstraint("updated_at >= created_at", name="chk_plan_updated_at"),
        CheckConstraint(
            "validated_at IS NULL OR validated_at >= created_at", name="chk_plan_validated_at"
        ),
        ForeignKeyConstraint(
            ["recommendation_id"],
            ["maintenance_recommendations.id"],
            ondelete="CASCADE",
            name="maintenance_plans_recommendation_id_fkey",
        ),
        ForeignKeyConstraint(
            ["validated_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="maintenance_plans_validated_by_fkey",
        ),
        PrimaryKeyConstraint("id", name="maintenance_plans_pkey"),
        UniqueConstraint("recommendation_id", name="uq_plan_recommendation"),
        Index(
            "idx_plan_brouillon",
            "created_at",
            postgresql_where="(status = 'BROUILLON'::plan_status)",
        ),
        Index("idx_plan_start_date", "start_date"),
        Index("idx_plan_status_priority", "status", "priority"),
        Index(
            "idx_plan_validated_by", "validated_by", postgresql_where="(validated_by IS NOT NULL)"
        ),
        Index(
            "idx_plan_valide", "validated_at", postgresql_where="(status = 'VALIDE'::plan_status)"
        ),
        {"comment": "1:1 with MaintenanceRecommendation. Operational schedule and budget."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    recommendation_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    priority: Mapped[PriorityLevel] = mapped_column(
        Enum(
            PriorityLevel,
            values_callable=lambda cls: [member.value for member in cls],
            name="priority_level",
        ),
        nullable=False,
    )
    status: Mapped[PlanStatus] = mapped_column(
        Enum(
            PlanStatus,
            values_callable=lambda cls: [member.value for member in cls],
            name="plan_status",
        ),
        nullable=False,
        server_default=text("'BROUILLON'::plan_status"),
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    total_budget: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    start_date: Mapped[datetime.date | None] = mapped_column(Date)
    end_date: Mapped[datetime.date | None] = mapped_column(Date)
    validated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    validated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    engineer_notes: Mapped[str | None] = mapped_column(
        Text,
        comment="Free-text notes added by the Road Engineer during validation or modification.",
    )

    recommendation: Mapped["MaintenanceRecommendation"] = relationship(
        "MaintenanceRecommendation", back_populates="maintenance_plans"
    )
    validator: Mapped[Optional["User"]] = relationship("User", back_populates="maintenance_plans")
    inspection_reports: Mapped["InspectionReport"] = relationship(
        "InspectionReport", uselist=False, back_populates="plan"
    )
