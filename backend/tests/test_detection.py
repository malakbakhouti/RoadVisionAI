"""Week 3 Step 1 — model registry + real YOLO inference tests.

Uses a REAL yolo11n.pt (COCO) as stand-in weights: registration, promotion
(single-active invariant against the real uq_one_active_model index), artifact
round-trip, and true Ultralytics inference with class mapping and
damage_detections-compatible output.
"""

import uuid
from pathlib import Path

import httpx
import pytest
from app.core.dependencies import get_storage_service
from app.main import create_app
from app.services.storage_service import StoredObject

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}
WEIGHTS = Path("/tmp/yolo11n.pt")
WEIGHTS_BYTES = WEIGHTS.read_bytes() if WEIGHTS.exists() else b""
TEST_IMAGE = Path("/tmp/bus.jpg")


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, *, bucket, object_name, data, content_type):
        self.objects[f"{bucket}/{object_name}"] = data
        return StoredObject(bucket=bucket, object_name=object_name)

    async def get_object(self, bucket, object_name):
        return self.objects[f"{bucket}/{object_name}"]

    async def presigned_get_url(self, bucket, object_name):
        return f"http://fake-minio/{bucket}/{object_name}"


@pytest.fixture
def fake_storage() -> FakeStorage:
    return FakeStorage()


@pytest.fixture
async def client(fake_storage) -> httpx.AsyncClient:
    app = create_app()
    app.dependency_overrides[get_storage_service] = lambda: fake_storage
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test", timeout=60
    ) as c:
        yield c


async def _auth(client) -> dict:
    resp = await client.post("/api/auth/login", json=ADMIN)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _unique(name: str) -> str:
    return f"{name}-{uuid.uuid4().hex[:6]}"


async def _register(client, headers, name, version="v1") -> dict:
    resp = await client.post(
        "/api/models",
        data={"name": name, "version": version,
              "metadata": '{"epochs": 50, "map50": 0.349, "dataset_name": "test"}'},
        files={"weights": ("best.pt", WEIGHTS_BYTES, "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


@pytest.mark.skipif(not WEIGHTS.exists(), reason="yolo11n.pt not available")
async def test_register_stores_weights_and_config(client, fake_storage) -> None:
    headers = await _auth(client)
    model = await _register(client, headers, _unique("yolo-test"))
    assert model["status"] == "STAGING"
    assert model["is_active"] is False
    assert float(model["model_size_mb"]) > 5
    assert model["map50"] == "0.349" or float(model["map50"]) == 0.349
    # weights + config really stored
    assert model["weights_path"] in fake_storage.objects
    config_path = model["weights_path"].replace("best.pt", "model_config.json")
    assert config_path in fake_storage.objects


@pytest.mark.skipif(not WEIGHTS.exists(), reason="yolo11n.pt not available")
async def test_duplicate_name_version_is_409(client) -> None:
    headers = await _auth(client)
    name = _unique("dup")
    await _register(client, headers, name)
    resp = await client.post(
        "/api/models",
        data={"name": name, "version": "v1"},
        files={"weights": ("best.pt", b"x" * 10, "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 409


@pytest.mark.skipif(not WEIGHTS.exists(), reason="yolo11n.pt not available")
async def test_promotion_enforces_single_active(client) -> None:
    """Two successive promotions: the DB invariant uq_one_active_model holds."""
    headers = await _auth(client)
    m1 = await _register(client, headers, _unique("champion"))
    m2 = await _register(client, headers, _unique("challenger"))

    p1 = await client.post(f"/api/models/{m1['id']}/promote", headers=headers)
    assert p1.status_code == 200 and p1.json()["is_active"] is True

    p2 = await client.post(f"/api/models/{m2['id']}/promote", headers=headers)
    assert p2.status_code == 200 and p2.json()["is_active"] is True

    listing = (await client.get("/api/models", headers=headers)).json()
    actives = [m for m in listing if m["is_active"]]
    assert len(actives) == 1 and actives[0]["id"] == m2["id"]
    demoted = next(m for m in listing if m["id"] == m1["id"])
    assert demoted["status"] == "DEPRECATED" and demoted["deprecated_at"] is not None

    again = await client.post(f"/api/models/{m2['id']}/promote", headers=headers)
    assert again.status_code == 409  # already in production


@pytest.mark.skipif(
    not (WEIGHTS.exists() and TEST_IMAGE.exists()), reason="test artifacts missing"
)
async def test_detector_runs_real_inference_with_mapping() -> None:
    """True Ultralytics inference; COCO classes mapped via model_config mapping."""
    from app.ai.detection.detector import Detector

    mapping = {"person": "POTHOLE", "bus": "RUTTING"}  # stand-in mapping for COCO
    detector = await Detector.from_weights(
        WEIGHTS_BYTES, mapping, model_id=uuid.uuid4()
    )
    detections = await detector.detect(TEST_IMAGE)

    assert len(detections) >= 2  # bus.jpg: persons + bus at conf>=0.5
    codes = {d.damage_code for d in detections}
    assert codes <= {"POTHOLE", "RUTTING"}
    for d in detections:
        # every value satisfies damage_detections CHECK constraints by construction
        assert 0 <= d.bbox_x <= 1 and 0 <= d.bbox_y <= 1
        assert 0 < d.bbox_width <= 1 and 0 < d.bbox_height <= 1
        assert 0.5 <= d.confidence <= 1
        assert 0 <= d.severity <= 1


def test_class_mapping_resolution() -> None:
    from app.ai.detection.class_mapping import resolve_code

    assert resolve_code("pothole", None) == "POTHOLE"
    assert resolve_code("Longitudinal-Crack", None) == "LONGITUDINAL_CRACK"
    assert resolve_code("pothole", {"pothole": "CUSTOM"}) == "CUSTOM"
    assert resolve_code("New Class", None) == "NEW_CLASS"  # normalisation fallback
