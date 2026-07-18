"""Week 3 Step 3 — END-TO-END pipeline test.

The full story, against the real database and a real YOLO model:
  register + promote model -> create inspection + image -> run worker
  -> damage_detections rows -> pci_scores row -> analysis_results summary
  -> inspection TERMINEE. Plus the ERREUR path.

COCO stand-in mapping ('person'->POTHOLE, 'bus'->RUTTING) lets yolo11n.pt
produce guaranteed detections on bus.jpg without a road-damage model.
"""

import json
import uuid
from pathlib import Path

import pytest
from app.core.config import get_settings
from app.db.session import get_session_factory, init_engine
from app.services.storage_service import StoredObject
from app.workers import analysis_worker
from app.workers.analysis_worker import run_analysis
from sqlalchemy import text

WEIGHTS = Path("/tmp/yolo11n.pt")
TEST_IMAGE = Path("/tmp/bus.jpg")
WEIGHTS_BYTES = WEIGHTS.read_bytes() if WEIGHTS.exists() else b""
IMAGE_BYTES = TEST_IMAGE.read_bytes() if TEST_IMAGE.exists() else b""
pytestmark = pytest.mark.skipif(
    not (WEIGHTS.exists() and TEST_IMAGE.exists()), reason="test artifacts missing"
)


class FakeStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put_object(self, *, bucket, object_name, data, content_type):
        self.objects[f"{bucket}/{object_name}"] = data
        return StoredObject(bucket=bucket, object_name=object_name)

    async def get_object(self, bucket, object_name):
        return self.objects[f"{bucket}/{object_name}"]

    async def presigned_get_url(self, bucket, object_name):
        return f"http://fake/{bucket}/{object_name}"


async def _seed_pipeline_fixture(storage: FakeStorage) -> uuid.UUID:
    """Real DB rows: model (active), section, inspection (EN_COURS), image."""
    init_engine()
    ids = {k: uuid.uuid4() for k in ("model", "section", "inspection", "image")}
    async with get_session_factory()() as s:
        admin_id = (
            await s.execute(text("SELECT id FROM users WHERE username='admin'"))
        ).scalar_one()
        # model: weights + config in fake MinIO, active row in ai_models
        storage.objects["models/e2e/v1/best.pt"] = WEIGHTS_BYTES
        storage.objects["models/e2e/v1/model_config.json"] = json.dumps(
            {"class_mapping": {"person": "POTHOLE", "bus": "RUTTING"}}
        ).encode()
        await s.execute(text("UPDATE ai_models SET is_active=false WHERE is_active=true"))
        await s.execute(
            text(
                "INSERT INTO ai_models (id, name, version, weights_path, status, "
                "is_active, trained_by) "
                "VALUES (:id, :name, 'v1', 'models/e2e/v1/best.pt', 'PRODUCTION', true, :usr)"
            ),
            {"id": ids["model"], "name": f"e2e-{ids['model'].hex[:6]}", "usr": admin_id},
        )
        await s.execute(
            text(
                "INSERT INTO road_sections (id, section_code, road_name, road_type) "
                "VALUES (:id, :code, 'RN E2E', 'NATIONALE')"
            ),
            {"id": ids["section"], "code": f"E2E-{ids['section'].hex[:8]}"},
        )
        await s.execute(
            text(
                "INSERT INTO inspections (id, road_section_id, created_by, status) "
                "VALUES (:id, :sec, :usr, 'EN_COURS')"
            ),
            {"id": ids["inspection"], "sec": ids["section"], "usr": admin_id},
        )
        storage.objects[f"road-images/{ids['inspection']}/bus.jpg"] = IMAGE_BYTES
        await s.execute(
            text(
                "INSERT INTO road_images (id, inspection_id, filename, storage_path, "
                "mime_type, sequence_num) VALUES (:id, :insp, 'bus.jpg', :path, 'image/jpeg', 1)"
            ),
            {
                "id": ids["image"],
                "insp": ids["inspection"],
                "path": f"road-images/{ids['inspection']}/bus.jpg",
            },
        )
        await s.commit()
    return ids["inspection"]


async def test_full_pipeline_end_to_end() -> None:
    storage = FakeStorage()
    analysis_worker._detector_cache.clear()
    inspection_id = await _seed_pipeline_fixture(storage)

    await run_analysis(inspection_id, get_settings(), storage)

    async with get_session_factory()() as s:
        status = (
            await s.execute(
                text("SELECT status FROM inspections WHERE id=:id"), {"id": inspection_id}
            )
        ).scalar_one()
        assert status == "TERMINEE"  # SM1 completed

        detections = (
            await s.execute(
                text(
                    "SELECT dt.code, dd.confidence_score, dd.severity_score, "
                    "dd.bbox_width, dd.bbox_height FROM damage_detections dd "
                    "JOIN damage_types dt ON dt.id = dd.damage_type_id "
                    "JOIN road_images ri ON ri.id = dd.road_image_id "
                    "WHERE ri.inspection_id = :id"
                ),
                {"id": inspection_id},
            )
        ).all()
        assert len(detections) >= 2  # bus.jpg: persons + bus
        assert {row[0] for row in detections} <= {"POTHOLE", "RUTTING"}
        for _, conf, sev, w, h in detections:
            assert 0.5 <= float(conf) <= 1 and 0 <= float(sev) <= 1
            assert 0 < float(w) <= 1 and 0 < float(h) <= 1

        pci = (
            await s.execute(
                text(
                    "SELECT score, severity_level, priority_level FROM pci_scores "
                    "WHERE inspection_id=:id"
                ),
                {"id": inspection_id},
            )
        ).one()
        assert 0 <= float(pci[0]) < 100  # detections exist -> score below perfect
        assert pci[1] in ("FAIBLE", "MODERE", "GRAVE", "CRITIQUE")

        summary = (
            await s.execute(
                text(
                    "SELECT total_detections, dominant_damage_type, processing_time_ms "
                    "FROM analysis_results WHERE inspection_id=:id"
                ),
                {"id": inspection_id},
            )
        ).one()
        assert summary[0] == len(detections)
        assert summary[1] in ("POTHOLE", "RUTTING")
        assert summary[2] > 0


async def test_rerun_is_idempotent() -> None:
    """Re-analysis replaces previous outputs (uq_analysis_inspection honoured)."""
    storage = FakeStorage()
    analysis_worker._detector_cache.clear()
    inspection_id = await _seed_pipeline_fixture(storage)

    await run_analysis(inspection_id, get_settings(), storage)
    await run_analysis(inspection_id, get_settings(), storage)  # second run

    async with get_session_factory()() as s:
        n_analysis = (
            await s.execute(
                text("SELECT count(*) FROM analysis_results WHERE inspection_id=:id"),
                {"id": inspection_id},
            )
        ).scalar_one()
        assert n_analysis == 1


async def test_failure_flips_inspection_to_erreur() -> None:
    """Corrupt weights -> pipeline fails -> SM1: EN_COURS -> ERREUR, no partial rows."""
    storage = FakeStorage()
    analysis_worker._detector_cache.clear()
    inspection_id = await _seed_pipeline_fixture(storage)
    # sabotage: replace weights with garbage
    key = next(k for k in storage.objects if k.endswith("best.pt"))
    storage.objects[key] = b"not a model"

    await run_analysis(inspection_id, get_settings(), storage)

    async with get_session_factory()() as s:
        status = (
            await s.execute(
                text("SELECT status FROM inspections WHERE id=:id"), {"id": inspection_id}
            )
        ).scalar_one()
        assert status == "ERREUR"
        n = (
            await s.execute(
                text("SELECT count(*) FROM pci_scores WHERE inspection_id=:id"),
                {"id": inspection_id},
            )
        ).scalar_one()
        assert n == 0  # rollback left no partial results
