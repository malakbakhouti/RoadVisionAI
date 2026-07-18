"""Step 4 — inspection module integration tests.

Real PostgreSQL (schema v4.2 + triggers) for everything; MinIO replaced by an
in-memory fake through the DI override (the storage contract is thin and the
real MinIO path is exercised in the deployed stack).
"""

import io
import uuid

import httpx
import pytest
from app.core.dependencies import get_storage_service
from app.db.session import get_session_factory, init_engine
from app.main import create_app
from app.services.storage_service import StoredObject
from PIL import Image

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_image(self, *, inspection_id, filename, data, content_type):
        obj = StoredObject(bucket="road-images", object_name=f"{inspection_id}/{filename}")
        self.objects[obj.storage_path] = data
        return obj

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
async def road_section_id() -> uuid.UUID:
    """A real road_sections row (deleted afterwards is unnecessary: unique code)."""
    from sqlalchemy import text

    init_engine()
    sid = uuid.uuid4()
    async with get_session_factory()() as s:
        await s.execute(
            text(
                "INSERT INTO road_sections (id, section_code, road_name, road_type) "
                "VALUES (:id, :code, 'RN1 — Rabat-Sale (test)', 'NATIONALE')"
            ),
            {"id": sid, "code": f"TEST-{sid.hex[:8]}"},
        )
        await s.commit()
    return sid


async def _auth_headers(client: httpx.AsyncClient) -> dict:
    resp = await client.post("/api/auth/login", json=ADMIN)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _jpeg_bytes(w: int = 64, h: int = 48) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), (120, 120, 120)).save(buf, format="JPEG")
    return buf.getvalue()


async def _create_inspection(client, headers, road_section_id) -> dict:
    resp = await client.post(
        "/api/inspections",
        json={"road_section_id": str(road_section_id), "notes": "test"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_create_and_get_inspection(client, road_section_id) -> None:
    headers = await _auth_headers(client)
    body = await _create_inspection(client, headers, road_section_id)
    assert body["status"] == "EN_ATTENTE"
    assert body["version"] == 1

    resp = await client.get(f"/api/inspections/{body['id']}", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["images"] == []


async def test_create_with_unknown_section_is_404(client) -> None:
    headers = await _auth_headers(client)
    resp = await client.post(
        "/api/inspections",
        json={"road_section_id": str(uuid.uuid4())},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_list_filters_by_status(client, road_section_id) -> None:
    headers = await _auth_headers(client)
    await _create_inspection(client, headers, road_section_id)
    resp = await client.get(
        "/api/inspections",
        params={"status": "EN_ATTENTE", "road_section_id": str(road_section_id)},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert all(i["status"] == "EN_ATTENTE" for i in body["items"])


async def test_patch_with_stale_version_is_409(client, road_section_id) -> None:
    headers = await _auth_headers(client)
    created = await _create_inspection(client, headers, road_section_id)

    ok = await client.patch(
        f"/api/inspections/{created['id']}",
        json={"version": 1, "notes": "updated"},
        headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json()["version"] == 2  # bumped by DB trigger fn_increment_version

    stale = await client.patch(
        f"/api/inspections/{created['id']}",
        json={"version": 1, "notes": "conflict"},
        headers=headers,
    )
    assert stale.status_code == 409  # critical business rule #4


async def test_upload_image_stores_and_records(client, road_section_id, fake_storage) -> None:
    headers = await _auth_headers(client)
    created = await _create_inspection(client, headers, road_section_id)

    resp = await client.post(
        f"/api/inspections/{created['id']}/images",
        files={"file": ("route.jpg", _jpeg_bytes(640, 480), "image/jpeg")},
        data={"gps_lat": "34.0209", "gps_lng": "-6.8416"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    img = resp.json()
    assert img["width"] == 640 and img["height"] == 480
    assert img["sequence_num"] == 1
    assert img["storage_path"] in fake_storage.objects  # bytes really "stored"

    second = await client.post(
        f"/api/inspections/{created['id']}/images",
        files={"file": ("route2.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    assert second.json()["sequence_num"] == 2

    detail = await client.get(f"/api/inspections/{created['id']}", headers=headers)
    images = detail.json()["images"]
    assert len(images) == 2
    assert images[0]["download_url"].startswith("http://fake-minio/")


async def test_upload_rejects_non_image(client, road_section_id) -> None:
    headers = await _auth_headers(client)
    created = await _create_inspection(client, headers, road_section_id)
    resp = await client.post(
        f"/api/inspections/{created['id']}/images",
        files={"file": ("notes.txt", b"not an image", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 415


async def test_analyse_is_202_and_moves_state_machine(
    client, road_section_id, monkeypatch
) -> None:
    # The worker pipeline has its own e2e suite (test_analysis_pipeline);
    # here we test the 202 contract + SM1 transition in isolation.
    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("app.workers.analysis_worker.run_analysis", _noop)
    headers = await _auth_headers(client)
    created = await _create_inspection(client, headers, road_section_id)

    no_images = await client.post(
        f"/api/inspections/{created['id']}/analyse", headers=headers
    )
    assert no_images.status_code == 400  # cannot analyse without images

    await client.post(
        f"/api/inspections/{created['id']}/images",
        files={"file": ("route.jpg", _jpeg_bytes(), "image/jpeg")},
        headers=headers,
    )
    accepted = await client.post(
        f"/api/inspections/{created['id']}/analyse", headers=headers
    )
    assert accepted.status_code == 202  # critical business rule #3
    assert accepted.json()["status"] == "EN_COURS"  # SM1 transition

    again = await client.post(
        f"/api/inspections/{created['id']}/analyse", headers=headers
    )
    assert again.status_code == 409  # already EN_COURS


async def test_soft_delete_then_404(client, road_section_id) -> None:
    headers = await _auth_headers(client)
    created = await _create_inspection(client, headers, road_section_id)
    resp = await client.delete(f"/api/inspections/{created['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.get(f"/api/inspections/{created['id']}", headers=headers)
    assert resp.status_code == 404  # rule #5: soft-deleted rows are invisible
