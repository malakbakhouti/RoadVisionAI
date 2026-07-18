"""Analysis worker — turns the 202 into a real pipeline (SD03, SM1).

Flow per inspection:
    images (MinIO) -> active YOLO model -> damage_detections
                   -> PCIEngine (ASTM D6433) -> pci_scores
                   -> analysis_results summary -> inspection TERMINEE | ERREUR

Design points:
  * Runs in a FastAPI background task with ITS OWN session (the request
    session is long gone when this executes) — the documented Celery-less
    trade-off of the TechStack.
  * The Detector is cached per process, keyed by model id: weights are
    downloaded from MinIO and loaded once, then reused (SM4 promotion of a
    new model naturally invalidates the cache key).
  * uq_analysis_inspection: one analysis row per inspection — re-analysis
    (from ERREUR) replaces the previous summary.
  * Any exception flips the inspection to ERREUR with full logging; the 202
    contract means errors surface through polling, never through the request.
"""

import tempfile
import time
import uuid
from pathlib import Path

import anyio
import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.detection.detector import Detection, Detector
from app.ai.detection.model_registry import ModelRegistryService
from app.ai.engines.pci_engine import DetectionInput, compute_pci
from app.core.config import Settings
from app.db.models.enums import InspectionStatus
from app.db.models.inspection import AnalysisResult, DamageDetection, Inspection, PciScore
from app.db.models.road import DamageType, RoadImage
from app.db.session import get_session_factory
from app.services.storage_service import StorageService

log = structlog.get_logger("app.workers.analysis")

_detector_cache: dict[uuid.UUID, Detector] = {}
_cache_lock = anyio.Lock()


async def _get_detector(
    session: AsyncSession, settings: Settings, storage: StorageService
) -> Detector:
    registry = ModelRegistryService(session, settings, storage)
    model = await registry.get_active()
    if model is None:
        raise RuntimeError("No active AI model — promote one via POST /api/models/{id}/promote")
    async with _cache_lock:
        if model.id not in _detector_cache:
            weights, mapping = await registry.load_artifacts(model)
            _detector_cache[model.id] = await Detector.from_weights(weights, mapping, model.id)
    return _detector_cache[model.id]


async def run_analysis(
    inspection_id: uuid.UUID, settings: Settings, storage: StorageService
) -> None:
    """Background entry point — own session, full pipeline, never raises."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            await _run(session, inspection_id, settings, storage)
        except Exception:
            log.exception("analysis_failed", inspection_id=str(inspection_id))
            await session.rollback()
            inspection = await session.get(Inspection, inspection_id)
            if inspection is not None:
                inspection.status = InspectionStatus.ERREUR
                await session.commit()


async def _run(
    session: AsyncSession,
    inspection_id: uuid.UUID,
    settings: Settings,
    storage: StorageService,
) -> None:
    started = time.monotonic()
    inspection = await session.get(Inspection, inspection_id)
    if inspection is None:
        raise RuntimeError(f"Inspection {inspection_id} vanished")

    images = list(
        (
            await session.execute(select(RoadImage).where(RoadImage.inspection_id == inspection_id))
        ).scalars()
    )
    if not images:
        raise RuntimeError("No images to analyse")

    detector = await _get_detector(session, settings, storage)

    # damage_types lookup: code -> (id, pci_weight)
    dt_rows = (await session.execute(select(DamageType))).scalars().all()
    damage_types = {dt.code: dt for dt in dt_rows}

    # Re-analysis (from ERREUR): clear previous outputs for idempotence
    image_ids = [img.id for img in images]
    await session.execute(
        delete(DamageDetection).where(DamageDetection.road_image_id.in_(image_ids))
    )
    await session.execute(delete(PciScore).where(PciScore.inspection_id == inspection_id))
    await session.execute(
        delete(AnalysisResult).where(AnalysisResult.inspection_id == inspection_id)
    )

    all_detections: list[tuple[RoadImage, Detection]] = []
    tmp_dir = Path(tempfile.mkdtemp(prefix="rv_analysis_"))
    for image in images:
        bucket, _, object_name = image.storage_path.partition("/")
        data = await storage.get_object(bucket, object_name)
        local = tmp_dir / f"{image.id}{Path(image.filename).suffix or '.jpg'}"
        local.write_bytes(data)
        for det in await detector.detect(local):
            if det.damage_code not in damage_types:
                log.warning("unknown_damage_code", code=det.damage_code, image_id=str(image.id))
                continue
            all_detections.append((image, det))
            session.add(
                DamageDetection(
                    road_image_id=image.id,
                    damage_type_id=damage_types[det.damage_code].id,
                    model_id=detector.model_id,
                    bbox_x=det.bbox_x,
                    bbox_y=det.bbox_y,
                    bbox_width=det.bbox_width,
                    bbox_height=det.bbox_height,
                    confidence_score=det.confidence,
                    severity_score=det.severity,
                )
            )
    await session.flush()

    # --- PCI (deterministic engine) ------------------------------------------
    pci_inputs = [
        DetectionInput(
            damage_code=det.damage_code,
            pci_weight=float(damage_types[det.damage_code].pci_weight),
            severity=det.severity,
            rel_area=det.bbox_width * det.bbox_height,
            image_id=str(image.id),
        )
        for image, det in all_detections
    ]
    pci = compute_pci(pci_inputs, total_images=len(images))
    session.add(
        PciScore(
            inspection_id=inspection_id,
            score=pci.score,
            severity_level=pci.severity_level,
            priority_level=pci.priority_level,
        )
    )

    # --- Summary (analysis_results) --------------------------------------------
    dominant = (
        max(pci.deductions, key=lambda d: d.deduction).damage_code if pci.deductions else None
    )
    confidences = [det.confidence for _, det in all_detections]
    session.add(
        AnalysisResult(
            inspection_id=inspection_id,
            total_detections=len(all_detections),
            dominant_damage_type=dominant,
            overall_severity=pci.severity_level,
            recommendation_confidence=(
                round(sum(confidences) / len(confidences), 4) if confidences else None
            ),
            processing_time_ms=int((time.monotonic() - started) * 1000),
        )
    )

    inspection.status = InspectionStatus.TERMINEE  # SM1: EN_COURS -> TERMINEE
    await session.commit()
    log.info(
        "analysis_completed",
        inspection_id=str(inspection_id),
        detections=len(all_detections),
        pci=str(pci.score),
        priority=pci.priority_level.value,
        elapsed_ms=int((time.monotonic() - started) * 1000),
    )
