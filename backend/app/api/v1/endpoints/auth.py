"""Auth endpoints — APISpec v1.0 §3, sequence SD01."""

from fastapi import APIRouter, Request, status

from app.core.dependencies import CurrentUserDep, DbSessionDep, SettingsDep
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["authentication"])


def _client_meta(request: Request) -> tuple[str | None, str | None]:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else None
    )
    return ip, request.headers.get("user-agent")


@router.post("/login", response_model=TokenResponse, summary="Authenticate (SD01)")
async def login(
    body: LoginRequest, request: Request, db: DbSessionDep, settings: SettingsDep
) -> TokenResponse:
    ip, ua = _client_meta(request)
    return await AuthService(db, settings).login(
        body.email, body.password, ip=ip, user_agent=ua
    )


@router.post("/refresh", response_model=TokenResponse, summary="Rotate tokens (SD01)")
async def refresh(
    body: RefreshRequest, db: DbSessionDep, settings: SettingsDep
) -> TokenResponse:
    return await AuthService(db, settings).refresh(body.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="Logout (SD01)")
async def logout(
    request: Request, user: CurrentUserDep, db: DbSessionDep, settings: SettingsDep
) -> None:
    ip, ua = _client_meta(request)
    await AuthService(db, settings).logout(user, ip=ip, user_agent=ua)


@router.get("/me", response_model=UserResponse, summary="Current user profile")
async def me(user: CurrentUserDep) -> UserResponse:
    return UserResponse.model_validate(user)
