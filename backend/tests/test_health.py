"""Skeleton smoke tests — app boots, /health responds, /ready hits PostgreSQL+PostGIS."""

import httpx
import pytest
from app.main import create_app


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_health_returns_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["app"] == "RoadVisionAI"


async def test_ready_checks_database_and_postgis(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["database"] == "up"
    assert body["postgis"] is not None  # PostGIS_Lib_Version() answered


async def test_openapi_schema_is_generated(client: httpx.AsyncClient) -> None:
    resp = await client.get("/openapi.json")
    assert resp.status_code == 200
    assert resp.json()["info"]["title"] == "RoadVisionAI"
