"""ORM models — generated from the LIVE schema v4.2 database (sqlacodegen),
then reviewed and organised by domain. The database remains the single source
of truth; do not edit columns here without a schema-level ADR.
"""

import datetime
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKeyConstraint,
    Index,
    PrimaryKeyConstraint,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.db.models.user import User

from app.db.models.enums import (
    NotifType,
)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "priority::text = ANY (ARRAY['LOW'::character varying, 'NORMAL'::character varying, 'HIGH'::character varying, 'CRITICAL'::character varying]::text[])",
            name="notifications_priority_check",
        ),
        CheckConstraint("read_at IS NULL OR read_at >= created_at", name="chk_notif_read_at"),
        ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="CASCADE", name="notifications_user_id_fkey"
        ),
        PrimaryKeyConstraint("id", name="notifications_pkey"),
        Index("idx_notif_is_read", "is_read", postgresql_where="(is_read = false)"),
        Index("idx_notif_user_created", "user_id", "created_at"),
        {
            "comment": "User notifications. entity_type/entity_id provide loose coupling "
            "to source entity."
        },
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid, primary_key=True, server_default=text("gen_random_uuid()")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    type: Mapped[NotifType] = mapped_column(
        Enum(
            NotifType,
            values_callable=lambda cls: [member.value for member in cls],
            name="notif_type",
        ),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'NORMAL'::character varying")
    )
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime(True), nullable=False, server_default=text("now()")
    )
    entity_type: Mapped[str | None] = mapped_column(
        String(100),
        comment="Discriminator for the source entity (e.g. 'Inspection', 'MaintenancePlan').",
    )
    entity_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, comment="UUID of the source entity. No FK — loose coupling by design."
    )
    read_at: Mapped[datetime.datetime | None] = mapped_column(
        DateTime(True), comment="Timestamp when the user read the notification. NULL means unread."
    )

    user: Mapped["User"] = relationship("User", back_populates="notifications")
