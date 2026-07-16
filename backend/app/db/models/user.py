"""ORM models — users / roles / user_roles.

Mapped 1:1 on schema v4.2 (single source of truth — DataDictionary v1.0).
Rules honoured here:
  * ENUM `user_role` already exists in the DB  -> create_type=False
  * `version` is incremented by trigger fn_increment_version -> FetchedValue,
    optimistic locking is done manually in repositories (WHERE version = :expected,
    handle 409) per critical business rule #4.
  * created_at / updated_at are DB-managed (now() + trigger fn_set_updated_at).
  * Soft delete via deleted_at (business rule #5) — repositories must always
    filter `deleted_at IS NULL`.
"""

import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, FetchedValue, ForeignKey, String, Text, text
from sqlalchemy.dialects.postgresql import CITEXT, ENUM, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.ai_model import AiModel
    from app.db.models.inspection import Inspection
    from app.db.models.knowledge import KnowledgeDocument
    from app.db.models.maintenance import MaintenancePlan, MaintenanceRecommendation, Rule
    from app.db.models.notification import Notification


class UserRole(enum.StrEnum):
    """Mirror of the PostgreSQL ENUM `user_role` (schema v4.2)."""

    ADMINISTRATOR = "ADMINISTRATOR"
    ROAD_ENGINEER = "ROAD_ENGINEER"
    INSPECTION_AGENT = "INSPECTION_AGENT"


user_role_enum = ENUM(
    UserRole,
    name="user_role",
    create_type=False,
    values_callable=lambda e: [m.value for m in e],
)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(CITEXT(), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))

    specialization: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(200))
    vehicle_id: Mapped[str | None] = mapped_column(String(100))
    equipment_id: Mapped[str | None] = mapped_column(String(100))

    can_manage_users: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    can_manage_models: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))
    can_configure_ai: Mapped[bool | None] = mapped_column(Boolean, server_default=text("false"))

    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        server_onupdate=FetchedValue(),  # trigger fn_set_updated_at
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(
        nullable=False,
        server_default=text("1"),
        server_onupdate=FetchedValue(),  # trigger fn_increment_version
    )

    # --- Reverse relationships (paired with domain models via back_populates) ---
    trained_models: Mapped[list["AiModel"]] = relationship("AiModel", back_populates="trainer")
    inspections_created: Mapped[list["Inspection"]] = relationship(
        "Inspection", foreign_keys="Inspection.created_by", back_populates="creator"
    )
    inspections_validated: Mapped[list["Inspection"]] = relationship(
        "Inspection", foreign_keys="Inspection.validated_by", back_populates="validator"
    )
    knowledge_documents: Mapped[list["KnowledgeDocument"]] = relationship(
        "KnowledgeDocument", back_populates="uploader"
    )
    maintenance_plans: Mapped[list["MaintenancePlan"]] = relationship(
        "MaintenancePlan", back_populates="validator"
    )
    recommendations_rejected: Mapped[list["MaintenanceRecommendation"]] = relationship(
        "MaintenanceRecommendation",
        foreign_keys="MaintenanceRecommendation.rejected_by",
        back_populates="rejector",
    )
    recommendations_validated: Mapped[list["MaintenanceRecommendation"]] = relationship(
        "MaintenanceRecommendation",
        foreign_keys="MaintenanceRecommendation.validated_by",
        back_populates="validator",
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification", back_populates="user"
    )
    rules: Mapped[list["Rule"]] = relationship("Rule", back_populates="author")

    role_links: Mapped[list["UserRoleLink"]] = relationship(back_populates="user")


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    permissions: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'"))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
        server_onupdate=FetchedValue(),
    )

    user_links: Mapped[list["UserRoleLink"]] = relationship(back_populates="role_obj")


class UserRoleLink(Base):
    __tablename__ = "user_roles"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )

    user: Mapped[User] = relationship(back_populates="role_links")
    role_obj: Mapped[Role] = relationship(back_populates="user_links")
