"""User repository — data access only, no business rules (SAD §5 layering).

Soft delete rule (critical business rule #5): every query filters
`deleted_at IS NULL`.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.user import User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        stmt = select(User).where(User.id == user_id, User.deleted_at.is_(None))
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def touch_last_login(self, user: User) -> None:
        user.last_login = datetime.now(UTC)
        await self._session.flush()
