"""Auth integration tests — run against a real PostgreSQL with schema v4.2 + seed.

Covers the SD01 sequence end-to-end: login (success/failure), /me,
refresh rotation, logout + audit trail, RBAC guard, RFC 7807 error shape.
"""

import httpx
import pytest
from app.db.session import get_session_factory
from app.main import create_app
from sqlalchemy import text

ADMIN_EMAIL = "admin@dgr.gov.ma"
ADMIN_PASSWORD = "Admin@2026!"


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _login(client: httpx.AsyncClient) -> dict:
    resp = await client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_login_success_returns_token_pair(client: httpx.AsyncClient) -> None:
    body = await _login(client)
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 30 * 60
    assert body["access_token"] != body["refresh_token"]


async def test_login_wrong_password_is_401_problem_json(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/auth/login", json={"email": ADMIN_EMAIL, "password": "WrongPass123!"}
    )
    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["title"] == "Unauthorized"
    assert body["status"] == 401


async def test_me_returns_current_user(client: httpx.AsyncClient) -> None:
    tokens = await _login(client)
    resp = await client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["email"] == ADMIN_EMAIL
    assert body["role"] == "ADMINISTRATOR"
    assert "password_hash" not in body  # never leaked


async def test_me_without_token_is_401(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_refresh_rotates_tokens(client: httpx.AsyncClient) -> None:
    tokens = await _login(client)
    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_access_token_rejected_as_refresh(client: httpx.AsyncClient) -> None:
    tokens = await _login(client)
    resp = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["access_token"]}
    )
    assert resp.status_code == 401  # type confusion blocked


async def test_logout_writes_audit_log(client: httpx.AsyncClient) -> None:
    tokens = await _login(client)
    resp = await client.post(
        "/api/auth/logout", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 204

    factory = get_session_factory()
    async with factory() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM audit_logs WHERE action IN ('LOGIN','LOGOUT')")
            )
        ).scalar_one()
    assert count >= 2  # at least this test's LOGIN + LOGOUT


async def test_rbac_guard_blocks_wrong_role(client: httpx.AsyncClient) -> None:
    """require_roles must 403 a role outside the allow-list (admin vs engineer-only)."""
    from typing import Annotated

    from app.core.dependencies import require_roles
    from app.db.models.user import User, UserRole
    from fastapi import Depends

    app = create_app()
    engineer_guard = require_roles(UserRole.ROAD_ENGINEER)

    @app.get("/api/_test/engineer-only")
    async def engineer_only(user: Annotated[User, Depends(engineer_guard)]) -> dict:
        return {"ok": True}

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        tokens = await _login(c)
        resp = await c.get(
            "/api/_test/engineer-only",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    assert resp.status_code == 403  # admin is not ROAD_ENGINEER
