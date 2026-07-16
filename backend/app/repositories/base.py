"""Generic repository — shared data-access patterns (SAD §5, Repository Pattern).

Encodes the two critical business rules every module must honour:
  #4 Optimistic locking: UPDATE ... WHERE id = :id AND version = :expected;
     rowcount 0 -> 409 Conflict (the DB trigger fn_increment_version bumps
     `version`, the application never writes it).
  #5 Soft delete: reads exclude `deleted_at IS NOT NULL` when the entity
     supports it; deletes set the timestamp instead of removing rows.
"""

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[ModelT: Base]:
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # --- read -----------------------------------------------------------------
    def _base_query(self) -> Select:
        stmt = select(self.model)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))
        return stmt

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        stmt = self._base_query().where(self.model.id == entity_id)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_or_404(self, entity_id: uuid.UUID) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"{self.model.__name__} {entity_id} not found"
            )
        return entity

    async def list(self, *, limit: int = 50, offset: int = 0) -> tuple[list[ModelT], int]:
        total = (
            await self._session.execute(
                select(func.count()).select_from(self._base_query().subquery())
            )
        ).scalar_one()
        rows = (
            (await self._session.execute(self._base_query().limit(limit).offset(offset)))
            .scalars()
            .all()
        )
        return list(rows), total

    # --- write ------------------------------------------------------------------
    async def add(self, entity: ModelT) -> ModelT:
        self._session.add(entity)
        await self._session.flush()
        await self._session.refresh(entity)
        return entity

    async def update_with_version(
        self, entity_id: uuid.UUID, expected_version: int, values: dict[str, Any]
    ) -> None:
        """Critical business rule #4 — optimistic locking, 409 on stale version."""
        stmt = (
            update(self.model)
            .where(self.model.id == entity_id, self.model.version == expected_version)
            .values(**values)
        )
        result = await self._session.execute(stmt)
        if result.rowcount == 0:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{self.model.__name__} {entity_id} was modified by another user "
                f"(expected version {expected_version})",
            )

    async def soft_delete(self, entity_id: uuid.UUID) -> None:
        """Critical business rule #5 — never hard-delete soft-deletable entities."""
        if not hasattr(self.model, "deleted_at"):
            raise NotImplementedError(f"{self.model.__name__} does not support soft delete")
        entity = await self.get_or_404(entity_id)
        entity.deleted_at = datetime.now(UTC)
        await self._session.flush()
