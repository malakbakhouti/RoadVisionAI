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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.inspection import DamageDetection
    from app.db.models.user import User

from app.db.models.enums import (
    ModelFramework,
    ModelStatus,
)


class AiModel(Base):
    __tablename__ = "ai_models"
    __table_args__ = (
        CheckConstraint("TRIM(BOTH FROM name) <> ''::text", name="chk_model_name"),
        CheckConstraint("batch_size > 0", name="ai_models_batch_size_check"),
        CheckConstraint("dataset_size > 0", name="ai_models_dataset_size_check"),
        CheckConstraint(
            "deployed_at IS NULL OR deployed_at >= trained_at", name="chk_model_deployed_at"
        ),
        CheckConstraint(
            "deprecated_at IS NULL OR deprecated_at >= trained_at", name="chk_model_deprecated_at"
        ),
        CheckConstraint("epochs > 0", name="ai_models_epochs_check"),
        CheckConstraint(
            "f1_score >= 0::numeric AND f1_score <= 1::numeric", name="ai_models_f1_score_check"
        ),
        CheckConstraint("image_size > 0", name="ai_models_image_size_check"),
        CheckConstraint("inference_ms > 0::numeric", name="ai_models_inference_ms_check"),
        CheckConstraint(
            "learning_rate IS NULL OR learning_rate > 0::numeric", name="chk_model_learning_rate"
        ),
        CheckConstraint(
            "map50 >= 0::numeric AND map50 <= 1::numeric", name="ai_models_map50_check"
        ),
        CheckConstraint(
            "map50_95 >= 0::numeric AND map50_95 <= 1::numeric", name="ai_models_map50_95_check"
        ),
        CheckConstraint("model_size_mb >= 0::numeric", name="ai_models_model_size_mb_check"),
        CheckConstraint("num_classes > 0", name="ai_models_num_classes_check"),
        CheckConstraint(
            "precision_score >= 0::numeric AND precision_score <= 1::numeric",
            name="ai_models_precision_score_check",
        ),
        CheckConstraint(
            "recall_score >= 0::numeric AND recall_score <= 1::numeric",
            name="ai_models_recall_score_check",
        ),
        CheckConstraint("updated_at >= created_at", name="chk_model_updated_at"),
        CheckConstraint(
            "weights_path IS NULL OR TRIM(BOTH FROM weights_path) <> ''::text",
            name="chk_model_weights_path",
        ),
        ForeignKeyConstraint(
            ["trained_by"], ["users.id"], ondelete="SET NULL", name="ai_models_trained_by_fkey"
        ),
        PrimaryKeyConstraint("id", name="ai_models_pkey"),
        UniqueConstraint("name", "version", name="uq_model_name_version"),
        Index("idx_ai_models_is_active", "is_active", postgresql_where="(is_active = true)"),
        Index("idx_ai_models_map50", "map50"),
        Index("idx_ai_models_status", "status"),
        Index("idx_ai_models_trained", "trained_at"),
        Index(
            "uq_one_active_model", "is_active", postgresql_where="(is_active = true)", unique=True
        ),
        {
            "comment": "AI model registry. Tracks all YOLOv11 versions, metrics and "
            "lifecycle status."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    framework: Mapped[ModelFramework] = mapped_column(
        Enum(
            ModelFramework,
            values_callable=lambda cls: [member.value for member in cls],
            name="model_framework",
        ),
        nullable=False,
        server_default=text("'YOLOV11'::model_framework"),
    )
    status: Mapped[ModelStatus] = mapped_column(
        Enum(
            ModelStatus,
            values_callable=lambda cls: [member.value for member in cls],
            name="model_status",
        ),
        nullable=False,
        server_default=text("'STAGING'::model_status"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("false"),
        comment="Only one model can be active at a time. Enforced at database level by the partial unique index uq_one_active_model.",
    )
    trained_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    description: Mapped[str | None] = mapped_column(Text)
    dataset_name: Mapped[str | None] = mapped_column(String(200))
    dataset_version: Mapped[str | None] = mapped_column(String(50))
    dataset_size: Mapped[int | None] = mapped_column(Integer)
    num_classes: Mapped[int | None] = mapped_column(Integer)
    epochs: Mapped[int | None] = mapped_column(Integer)
    batch_size: Mapped[int | None] = mapped_column(Integer)
    image_size: Mapped[int | None] = mapped_column(Integer)
    learning_rate: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 6))
    map50: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4), comment="Mean Average Precision at IoU threshold 0.50."
    )
    map50_95: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4), comment="Mean Average Precision averaged over IoU thresholds 0.50 to 0.95."
    )
    precision_score: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4), comment="TP / (TP + FP) — ratio of correct detections."
    )
    recall_score: Mapped[decimal.Decimal | None] = mapped_column(
        Numeric(5, 4), comment="TP / (TP + FN) — ratio of detected real damages."
    )
    f1_score: Mapped[decimal.Decimal | None] = mapped_column(Numeric(5, 4))
    inference_ms: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 2))
    weights_path: Mapped[str | None] = mapped_column(
        String(500), comment="Path to .pt weights file in MinIO or local storage."
    )
    model_size_mb: Mapped[decimal.Decimal | None] = mapped_column(Numeric(8, 2))
    deployed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    deprecated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime(True))
    trained_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    notes: Mapped[str | None] = mapped_column(Text)

    trainer: Mapped[Optional["User"]] = relationship("User", back_populates="trained_models")
    damage_detections: Mapped[list["DamageDetection"]] = relationship(
        "DamageDetection", back_populates="model"
    )
