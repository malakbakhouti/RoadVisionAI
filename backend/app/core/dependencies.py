"""Central dependency-injection wiring (SAD §5 — layered architecture).

routers -> services -> repositories -> AsyncSession.
Step 2 adds: bearer extraction, get_current_user, RBAC guards.
"""

import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.security import TokenError, decode_token
from app.db.models.user import User, UserRole
from app.db.session import get_db
from app.repositories.user_repository import UserRepository
from app.services.storage_service import StorageService

# --- Infrastructure ----------------------------------------------------------
SettingsDep = Annotated[Settings, Depends(get_settings)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db)]

# --- Storage (MinIO) -----------------------------------------------------------
_storage_singleton: StorageService | None = None


def get_storage_service(settings: SettingsDep) -> StorageService:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = StorageService(settings)
    return _storage_singleton


# --- RAG (ChromaDB + embeddings, SD07) -----------------------------------------
_chroma_singleton = None
_embedder_singleton = None


def get_chroma_client(settings: SettingsDep):
    global _chroma_singleton
    if _chroma_singleton is None:
        import chromadb

        _chroma_singleton = chromadb.HttpClient(
            host=settings.chroma_host, port=settings.chroma_port
        )
    return _chroma_singleton


_llm_singleton = None


def get_llm_provider(settings: SettingsDep):
    """Returns a Gemini provider, or None if no API key is configured
    (the pipeline then falls back to rule justifications)."""
    global _llm_singleton
    if not settings.gemini_api_key:
        return None
    if _llm_singleton is None:
        from app.ai.agents.gemini_provider import GeminiProvider

        _llm_singleton = GeminiProvider(
            settings.gemini_api_key, settings.gemini_model, settings.gemini_temperature
        )
    return _llm_singleton


def get_embedder(settings: SettingsDep):
    global _embedder_singleton
    if _embedder_singleton is None:
        from app.ai.rag.embeddings import E5Embedder

        _embedder_singleton = E5Embedder(settings.embedding_model)
    return _embedder_singleton


# --- Security (SD01, RBAC per UC0-UC3) ---------------------------------------
_bearer = HTTPBearer(auto_error=False)

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Not authenticated",
    headers={"WWW-Authenticate": "Bearer"},
)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSessionDep,
    settings: SettingsDep,
) -> User:
    if credentials is None:
        raise _UNAUTHORIZED
    try:
        payload = decode_token(credentials.credentials, "access", settings)
    except TokenError as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, str(exc), headers={"WWW-Authenticate": "Bearer"}
        ) from exc
    user = await UserRepository(db).get_by_id(uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    return user


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """RBAC guard factory — e.g. Depends(require_roles(UserRole.ROAD_ENGINEER))."""

    async def _guard(user: CurrentUserDep) -> User:
        if user.role not in roles:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Requires role: {', '.join(r.value for r in roles)}",
            )
        return user

    return _guard
