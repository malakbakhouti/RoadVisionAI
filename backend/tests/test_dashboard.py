"""Step 6 — dashboard CQRS tests against the real database."""

import httpx
import pytest
from app.main import create_app

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _auth_headers(client) -> dict:
    resp = await client.post("/api/auth/login", json=ADMIN)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_snapshot_then_summary(client) -> None:
    headers = await _auth_headers(client)

    created = await client.post("/api/dashboard/snapshots", headers=headers)
    assert created.status_code == 201, created.text
    snap = created.json()
    assert snap["total_inspections"] >= 1  # inspections exist from earlier tests

    summary = await client.get("/api/dashboard/summary", headers=headers)
    assert summary.status_code == 200
    body = summary.json()
    assert body["snapshot"]["id"] == snap["id"]  # latest snapshot is served
    assert isinstance(body["damage_stats"], list)


async def test_pci_trends_empty_is_ok(client) -> None:
    headers = await _auth_headers(client)
    resp = await client.get("/api/dashboard/pci-trends", headers=headers)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


async def test_snapshot_requires_admin_role(client) -> None:
    resp = await client.post("/api/dashboard/snapshots")
    assert resp.status_code == 401  # no token at all
