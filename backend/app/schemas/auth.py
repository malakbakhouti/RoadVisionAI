"""Auth DTOs — request/response contracts of APISpec §3 (SD01)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.db.models.user import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds (access token)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    email: str
    role: UserRole
    is_active: bool
    specialization: str | None = None
    region: str | None = None
    can_manage_users: bool | None = None
    can_manage_models: bool | None = None
    can_configure_ai: bool | None = None
    last_login: datetime | None = None
    created_at: datetime
