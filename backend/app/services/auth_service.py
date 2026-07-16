"""AuthService — authentication business logic (SD01 sequence, APISpec §3).

Owns the transaction boundary (commit/rollback) per SAD §5: repositories
flush, the service commits.
"""

import uuid

import structlog
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.db.models.user import User
from app.repositories.audit_repository import AuditRepository
from app.repositories.user_repository import UserRepository
from app.schemas.auth import TokenResponse

log = structlog.get_logger("app.services.auth")

_INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._audit = AuditRepository(session)

    def _issue_tokens(self, user: User) -> TokenResponse:
        return TokenResponse(
            access_token=create_access_token(user.id, user.role.value, self._settings),
            refresh_token=create_refresh_token(user.id, self._settings),
            expires_in=self._settings.access_token_expire_minutes * 60,
        )

    async def login(
        self, email: str, password: str, *, ip: str | None, user_agent: str | None
    ) -> TokenResponse:
        user = await self._users.get_by_email(email)
        if user is None or not verify_password(password, user.password_hash):
            # Same error whether the account exists or not (no user enumeration).
            log.warning("login_failed", email=email, ip=ip)
            raise _INVALID_CREDENTIALS
        if not user.is_active:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Account is deactivated")

        await self._users.touch_last_login(user)
        await self._audit.log(
            action="LOGIN",
            entity_type="users",
            entity_id=user.id,
            user_id=user.id,
            ip_address=ip,
            user_agent=user_agent,
        )
        await self._session.commit()
        log.info("login_success", user_id=str(user.id), role=user.role.value)
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(refresh_token, "refresh", self._settings)
        except TokenError as exc:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}
            ) from exc
        user = await self._users.get_by_id(uuid.UUID(payload["sub"]))
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User no longer active")
        log.info("token_refreshed", user_id=str(user.id))
        return self._issue_tokens(user)

    async def logout(self, user: User, *, ip: str | None, user_agent: str | None) -> None:
        """Stateless logout: audit the event; client discards its tokens.

        Schema v4.2 has no token store (and must not be modified), so
        server-side revocation is an evolution pathway. The 30-min access
        TTL bounds residual validity.
        """
        await self._audit.log(
            action="LOGOUT",
            entity_type="users",
            entity_id=user.id,
            user_id=user.id,
            ip_address=ip,
            user_agent=user_agent,
        )
        await self._session.commit()
        log.info("logout", user_id=str(user.id))
