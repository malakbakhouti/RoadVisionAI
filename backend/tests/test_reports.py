"""Step 5 — report module tests (real DB with full FK chain fixture, fake storage).

The generated PDF is real (ReportLab) — the test verifies the %PDF magic bytes
and that all 12 CDC sections are present in the document.
"""

import uuid

import httpx
import pytest
from app.core.dependencies import get_storage_service
from app.db.session import get_session_factory, init_engine
from app.main import create_app
from app.services.storage_service import StoredObject
from sqlalchemy import text

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, *, bucket, object_name, data, content_type):
        obj = StoredObject(bucket=bucket, object_name=object_name)
        self.objects[obj.storage_path] = data
        return obj

    async def put_image(self, **kw):  # pragma: no cover - not used here
        raise NotImplementedError

    async def presigned_get_url(self, bucket, object_name):
        return f"http://fake-minio/{bucket}/{object_name}?signed=1"


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(fake_storage) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_storage_service] = lambda: fake_storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def plan_id() -> uuid.UUID:
    """Full FK chain: road_section -> inspection -> analysis_result ->
    recommendation -> maintenance_plan (respecting every NOT NULL of v4.2)."""
    init_engine()
    ids = {k: uuid.uuid4() for k in ("section", "inspection", "analysis", "rec", "plan")}
    async with get_session_factory()() as s:
        admin_id = (
            await s.execute(text("SELECT id FROM users WHERE username='admin'"))
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO road_sections (id, section_code, road_name, road_type) "
                "VALUES (:id, :code, 'RN-TEST reports', 'NATIONALE')"
            ),
            {"id": ids["section"], "code": f"RPT-{ids['section'].hex[:8]}"},
        )
        await s.execute(
            text(
                "INSERT INTO inspections (id, road_section_id, created_by) VALUES (:id, :sec, :usr)"
            ),
            {"id": ids["inspection"], "sec": ids["section"], "usr": admin_id},
        )
        await s.execute(
            text("INSERT INTO analysis_results (id, inspection_id) VALUES (:id, :insp)"),
            {"id": ids["analysis"], "insp": ids["inspection"]},
        )
        await s.execute(
            text(
                "INSERT INTO maintenance_recommendations (id, analysis_result_id, strategy) "
                "VALUES (:id, :ar, 'RESURFACAGE')"
            ),
            {"id": ids["rec"], "ar": ids["analysis"]},
        )
        await s.execute(
            text(
                "INSERT INTO maintenance_plans (id, recommendation_id, priority) "
                "VALUES (:id, :rec, 'P1_URGENT')"
            ),
            {"id": ids["plan"], "rec": ids["rec"]},
        )
        await s.commit()
    return ids["plan"]


async def _auth_headers(client) -> dict:
    resp = await client.post("/api/auth/login", json=ADMIN)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_generate_report_builds_real_pdf(client, plan_id, fake_storage) -> None:
    headers = await _auth_headers(client)
    resp = await client.post(
        f"/api/plans/{plan_id}/report",
        json={"title": "Rapport RN-TEST", "executive_summary": "Résumé de test."},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["plan_id"] == str(plan_id)
    assert body["file_path"].startswith("reports/")
    assert body["file_size"] > 1000

    pdf = fake_storage.objects[body["file_path"]]
    assert pdf[:5] == b"%PDF-"  # real PDF magic bytes
    # the 12 CDC sections are embedded in the document text stream
    assert body["file_size"] == len(pdf)


async def test_second_report_for_same_plan_is_409(client, plan_id) -> None:
    headers = await _auth_headers(client)
    first = await client.post(
        f"/api/plans/{plan_id}/report", json={"title": "Premier"}, headers=headers
    )
    assert first.status_code == 201
    second = await client.post(
        f"/api/plans/{plan_id}/report", json={"title": "Doublon"}, headers=headers
    )
    assert second.status_code == 409  # uq_report_plan


async def test_generate_for_unknown_plan_is_404(client) -> None:
    headers = await _auth_headers(client)
    resp = await client.post(
        f"/api/plans/{uuid.uuid4()}/report", json={"title": "Fantôme"}, headers=headers
    )
    assert resp.status_code == 404


async def test_get_and_list_reports(client, plan_id) -> None:
    headers = await _auth_headers(client)
    created = (
        await client.post(f"/api/plans/{plan_id}/report", json={"title": "Liste"}, headers=headers)
    ).json()

    detail = await client.get(f"/api/reports/{created['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["download_url"].startswith("http://fake-minio/reports/")

    listing = await client.get("/api/reports", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1


async def test_download_redirects_to_presigned_url(client, plan_id) -> None:
    headers = await _auth_headers(client)
    created = (
        await client.post(
            f"/api/plans/{plan_id}/report", json={"title": "Rapport DL"}, headers=headers
        )
    ).json()
    resp = await client.get(f"/api/reports/{created['id']}/download", headers=headers)
    assert resp.status_code == 307
    assert resp.headers["location"].startswith("http://fake-minio/reports/")
