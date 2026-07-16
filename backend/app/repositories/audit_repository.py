"""Audit repository — INSERT-only, mirroring the immutable audit_logs design."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit import AuditLog


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def log(
        self,
        *,
        action: str,
        entity_type: str,
        entity_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        new_value: dict | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self._session.add(
            AuditLog(
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                user_id=user_id,
                new_value=new_value,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        )
        await self._session.flush()
