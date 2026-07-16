"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import decimal
import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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
    from app.db.models.ai_model import AiModel
    from app.db.models.maintenance import MaintenancePlan, MaintenanceRecommendation
    from app.db.models.road import DamageType, RoadImage, RoadSection
    from app.db.models.user import User

from app.db.models.enums import (
    InspectionStatus,
    PriorityLevel,
    SeverityLevel,
)


class Inspection(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(
            "deleted_at IS NULL OR deleted_at >= created_at", name="chk_inspections_deleted_at"
        ),
        CheckConstraint("updated_at >= created_at", name="chk_inspections_updated_at"),
        ForeignKeyConstraint(
            ["created_by"], ["users.id"], ondelete="RESTRICT", name="inspections_created_by_fkey"
        ),
        ForeignKeyConstraint(
            ["road_section_id"],
            ["road_sections.id"],
            ondelete="RESTRICT",
            name="inspections_road_section_id_fkey",
        ),
        ForeignKeyConstraint(
            ["validated_by"],
            ["users.id"],
            ondelete="SET NULL",
            name="inspections_validated_by_fkey",
        ),
        PrimaryKeyConstraint("id", name="inspections_pkey"),
        Index("idx_inspections_created_by", "created_by"),
        Index("idx_inspections_deleted", "deleted_at", postgresql_where="(deleted_at IS NULL)"),
        Index(
            "idx_inspections_in_cours",
            "created_by",
            "updated_at",
            postgresql_where="(status = 'EN_COURS'::inspection_status)",
        ),
        Index(
            "idx_inspections_pending",
            "road_section_id",
            "created_at",
            postgresql_where="(status = 'EN_ATTENTE'::inspection_status)",
        ),
        Index("idx_inspections_section_date", "road_section_id", "inspection_date"),
        Index("idx_inspections_status", "status"),
        {
            "comment": "Core inspection entity. Links road section, agent (created_by) "
            "and engineer (validated_by)."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    road_section_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    status: Mapped[InspectionStatus] = mapped_column(
        Enum(
            InspectionStatus,
            values_callable=lambda cls: [member.value for member in cls],
            name="inspection_status",
        ),
        nullable=False,
        server_default=text("'EN_ATTENTE'::inspection_status"),
    )
    inspection_date: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    validated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    weather_cond: Mapped[str | None] = mapped_column(String(100))
    notes: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(True), comment="Soft delete — NULL means active."
    )

    creator: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by], back_populates="inspections_created"
    )
    road_section: Mapped["RoadSection"] = relationship("RoadSection", back_populates="inspections")
    validator: Mapped[Optional["User"]] = relationship(
        "User", foreign_keys=[validated_by], back_populates="inspections_validated"
    )
    analysis_results: Mapped["AnalysisResult"] = relationship(
        "AnalysisResult", uselist=False, back_populates="inspection"
    )
    pci_scores: Mapped["PciScore"] = relationship(
        "PciScore", uselist=False, back_populates="inspection"
    )
    road_images: Mapped[list["RoadImage"]] = relationship("RoadImage", back_populates="inspection")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    __table_args__ = (
        CheckConstraint(
            "processing_time_ms >= 0", name="analysis_results_processing_time_ms_check"
        ),
        CheckConstraint(
            "recommendation_confidence >= 0::numeric AND recommendation_confidence <= 1::numeric",
            name="analysis_results_recommendation_confidence_check",
        ),
        CheckConstraint("total_detections >= 0", name="analysis_results_total_detections_check"),
        ForeignKeyConstraint(
            ["inspection_id"],
            ["inspections.id"],
            ondelete="CASCADE",
            name="analysis_results_inspection_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="analysis_results_pkey"),
        UniqueConstraint("inspection_id", name="uq_analysis_inspection"),
        Index("idx_analysis_severity", "overall_severity"),
        {
            "comment": "1:1 with Inspection. Aggregated output of the full AI pipeline "
            "per inspection."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    total_detections: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    dominant_damage_type: Mapped[str | None] = mapped_column(String(200))
    overall_severity: Mapped[SeverityLevel | None] = mapped_column(
        Enum(
            SeverityLevel,
            values_callable=lambda cls: [member.value for member in cls],
            name="severity_level",
        )
    )
    recommendation_confidence: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4),
        comment="Overall AI confidence in the generated maintenance recommendation. Range [0,1].",
    )
    processing_time_ms: Mapped[int | None] = mapped_column(
        BigInteger, comment="Total AI pipeline processing time in milliseconds."
    )

    inspection: Mapped["Inspection"] = relationship("Inspection", back_populates="analysis_results")
    maintenance_recommendations: Mapped["MaintenanceRecommendation"] = relationship(
        "MaintenanceRecommendation", uselist=False, back_populates="analysis_result"
    )


class DamageDetection(Base):
    __tablename__ = "damage_detections"
    __table_args__ = (
        CheckConstraint("bbox_height > 0::numeric", name="damage_detections_bbox_height_check"),
        CheckConstraint("bbox_width > 0::numeric", name="damage_detections_bbox_width_check"),
        CheckConstraint("bbox_x >= 0::numeric", name="damage_detections_bbox_x_check"),
        CheckConstraint("bbox_y >= 0::numeric", name="damage_detections_bbox_y_check"),
        CheckConstraint(
            "confidence_score >= 0::numeric AND confidence_score <= 1::numeric",
            name="damage_detections_confidence_score_check",
        ),
        CheckConstraint(
            "severity_score >= 0::numeric AND severity_score <= 1::numeric",
            name="damage_detections_severity_score_check",
        ),
        ForeignKeyConstraint(
            ["damage_type_id"],
            ["damage_types.id"],
            ondelete="RESTRICT",
            name="damage_detections_damage_type_id_fkey",
        ),
        ForeignKeyConstraint(
            ["model_id"],
            ["ai_models.id"],
            ondelete="SET NULL",
            name="damage_detections_model_id_fkey",
        ),
        ForeignKeyConstraint(
            ["road_image_id"],
            ["road_images.id"],
            ondelete="CASCADE",
            name="damage_detections_road_image_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="damage_detections_pkey"),
        Index("idx_detections_confidence", "confidence_score"),
        Index("idx_detections_image", "road_image_id"),
        Index("idx_detections_model", "model_id"),
        Index("idx_detections_severity", "severity_score"),
        Index("idx_detections_type", "damage_type_id"),
        {"comment": "YOLOv11 detection output. One row per detected damage per image."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    road_image_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    damage_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    bbox_x: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    bbox_y: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    bbox_width: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    bbox_height: Mapped[decimal.Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    confidence_score: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 4), nullable=False, comment="YOLOv11 detection confidence score. Range [0,1]."
    )
    severity_score: Mapped[decimal.Decimal] = mapped_column(
        Numeric(5, 4),
        nullable=False,
        comment="Computed severity score derived from type weight and area. Range [0,1].",
    )
    detected_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    area_m2: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(10, 4),
        comment="Estimated damage area in square metres, derived from bounding box and GPS scale.",
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        comment="Which AI model version produced this detection. Enables per-model performance tracking.",
    )

    damage_type: Mapped["DamageType"] = relationship(
        "DamageType", back_populates="damage_detections"
    )
    model: Mapped[Optional["AiModel"]] = relationship("AiModel", back_populates="damage_detections")
    road_image: Mapped["RoadImage"] = relationship("RoadImage", back_populates="damage_detections")


class PciScore(Base):
    __tablename__ = "pci_scores"
    __table_args__ = (
        CheckConstraint(
            "priority_score >= 0::numeric AND priority_score <= 1::numeric",
            name="pci_scores_priority_score_check",
        ),
        CheckConstraint(
            "score >= 0::numeric AND score <= 100::numeric", name="pci_scores_score_check"
        ),
        ForeignKeyConstraint(
            ["inspection_id"],
            ["inspections.id"],
            ondelete="CASCADE",
            name="pci_scores_inspection_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="pci_scores_pkey"),
        UniqueConstraint("inspection_id", name="uq_pci_inspection"),
        Index("idx_pci_priority", "priority_level"),
        Index("idx_pci_score", "score"),
        Index("idx_pci_severity", "severity_level"),
        {"comment": "1:1 with Inspection. PCI computed by PCIEngine using ASTM D6433."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    inspection_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    score: Mapped[decimal.Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    severity_level: Mapped[SeverityLevel] = mapped_column(
        Enum(
            SeverityLevel,
            values_callable=lambda cls: [member.value for member in cls],
            name="severity_level",
        ),
        nullable=False,
    )
    priority_level: Mapped[PriorityLevel] = mapped_column(
        Enum(
            PriorityLevel,
            values_callable=lambda cls: [member.value for member in cls],
            name="priority_level",
        ),
        nullable=False,
    )
    computed_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    priority_score: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4),
        comment="Multicriteria priority score combining PCI, traffic volume, road type and history. Range [0,1].",
    )

    inspection: Mapped["Inspection"] = relationship("Inspection", back_populates="pci_scores")


class XaiExplanation(Base):
    __tablename__ = "xai_explanations"
    __table_args__ = (
        CheckConstraint(
            "confidence_score >= 0::numeric AND confidence_score <= 1::numeric",
            name="xai_explanations_confidence_score_check",
        ),
        CheckConstraint(
            "jsonb_typeof(agents_involved) = 'array'::text",
            name="xai_explanations_agents_involved_check",
        ),
        CheckConstraint(
            "jsonb_typeof(normative_refs) = 'array'::text",
            name="xai_explanations_normative_refs_check",
        ),
        CheckConstraint(
            "jsonb_typeof(priority_breakdown) = 'object'::text",
            name="xai_explanations_priority_breakdown_check",
        ),
        CheckConstraint(
            "jsonb_typeof(rules_applied) = 'array'::text",
            name="xai_explanations_rules_applied_check",
        ),
        PrimaryKeyConstraint("id", name="xai_explanations_pkey"),
        Index("idx_xai_generated_at", "generated_at"),
        {
            "comment": "XAI output: rules, normative refs, priority decomposition. "
            "Generated by XAIService."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    rules_applied: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="JSON array of Rule codes activated by the RuleEngine for this inspection.",
    )
    normative_refs: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="JSON array of normative document references retrieved via RAG.",
    )
    priority_breakdown: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default=text("'{}'::jsonb"),
        comment="JSON object decomposing the Priority Score by factor (PCI, traffic, road_type, history, climate).",
    )
    confidence_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 4))
    severity_justification: Mapped[str | None] = mapped_column(Text)
    strategy_justification: Mapped[str | None] = mapped_column(Text)
    agents_involved: Mapped[dict | None] = mapped_column(
        JSONB,
        server_default=text("'[]'::jsonb"),
        comment="JSON array of LangGraph agent names that contributed to the decision.",
    )

    inspection_reports: Mapped[list["InspectionReport"]] = relationship(
        "InspectionReport", back_populates="xai_explanation"
    )


class InspectionReport(Base):
    __tablename__ = "inspection_reports"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM title) <> ''::text", name="chk_report_title"),
        CheckConstraint(
            "estimated_duration IS NULL OR estimated_duration > 0",
            name="inspection_reports_estimated_duration_check",
        ),
        CheckConstraint("file_size IS NULL OR file_size >= 0", name="chk_report_file_size"),
        CheckConstraint("generated_at >= created_at", name="chk_report_generated_at"),
        CheckConstraint(
            "normative_refs IS NULL OR jsonb_typeof(normative_refs) = 'array'::text",
            name="inspection_reports_normative_refs_check",
        ),
        ForeignKeyConstraint(
            ["plan_id"],
            ["maintenance_plans.id"],
            ondelete="CASCADE",
            name="inspection_reports_plan_id_fkey",
        ),
        ForeignKeyConstraint(
            ["xai_explanation_id"],
            ["xai_explanations.id"],
            ondelete="SET NULL",
            name="inspection_reports_xai_explanation_id_fkey",
        ),
        PrimaryKeyConstraint("id", name="inspection_reports_pkey"),
        UniqueConstraint("plan_id", name="uq_report_plan"),
        Index("idx_reports_generated_at", "generated_at"),
        Index(
            "idx_reports_xai",
            "xai_explanation_id",
            postgresql_where="(xai_explanation_id IS NOT NULL)",
        ),
        {"comment": "1:1 with MaintenancePlan. PDF report generated by ReportAgent + ReportLab."},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    generated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    xai_explanation_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    executive_summary: Mapped[str | None] = mapped_column(Text)
    damage_assessment: Mapped[str | None] = mapped_column(Text)
    pci_analysis: Mapped[str | None] = mapped_column(Text)
    priority_ranking: Mapped[str | None] = mapped_column(Text)
    recommendations: Mapped[str | None] = mapped_column(Text)
    estimated_budget: Mapped[decimal.Decimal | None] = mapped_column(Numeric(14, 2))
    estimated_duration: Mapped[int | None] = mapped_column(Integer)
    risk_analysis: Mapped[str | None] = mapped_column(Text)
    xai_justification: Mapped[str | None] = mapped_column(Text)
    normative_refs: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    file_path: Mapped[str | None] = mapped_column(
        String(500), comment="MinIO object path to the generated PDF file."
    )
    file_size: Mapped[int | None] = mapped_column(
        BigInteger, comment="Size of the generated PDF file in bytes."
    )

    plan: Mapped["MaintenancePlan"] = relationship(
        "MaintenancePlan", back_populates="inspection_reports"
    )
    xai_explanation: Mapped[Optional["XaiExplanation"]] = relationship(
        "XaiExplanation", back_populates="inspection_reports"
    )
