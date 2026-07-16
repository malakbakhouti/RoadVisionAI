"""ORM models registry — import all models so Base.metadata is complete (Alembic, Step 3)."""

from app.db.models.audit import AuditLog
from app.db.models.user import Role, User, UserRole, UserRoleLink

__all__ = ["AuditLog", "Role", "User", "UserRole", "UserRoleLink"]
