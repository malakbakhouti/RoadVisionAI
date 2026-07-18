"""Detector — YOLOv11 inference over road images (SD03 step 1, TechStack §4).

In-process inference: the active model is downloaded from MinIO once, cached
on disk, and loaded a single time per process. Inference runs in a worker
thread (the model call is CPU-bound and synchronous) so the event loop is
never blocked.

Output contract: normalised detections (bbox in 0-1 xywh) mapped to
damage_types codes, each carrying confidence and a provisional severity —
exactly what damage_detections rows require (all CHECK constraints
satisfiable by construction).
"""

import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import anyio
import structlog

from app.ai.detection.class_mapping import resolve_code

log = structlog.get_logger("app.ai.detector")

CONFIDENCE_THRESHOLD = 0.5  # CDC: YOLO confidence threshold


@dataclass(frozen=True)
class Detection:
    """One detection, normalised and mapped, ready for damage_detections."""

    damage_code: str
    confidence: float  # [0, 1]
    severity: float  # [0, 1] — provisional heuristic, refined by RuleEngine later
    bbox_x: float  # top-left, normalised [0, 1]
    bbox_y: float
    bbox_width: float  # normalised (0, 1]
    bbox_height: float


def _provisional_severity(confidence: float, rel_area: float) -> float:
    """Detection-time severity heuristic (documented, deliberately simple).

    Rationale: severity grows with the damaged fraction of the frame,
    weighted by detection confidence. 60% area / 40% confidence; the area
    term saturates at 10% of the frame (a pothole covering 10%+ of a road
    photo is already maximal). The RuleEngine (Week 4) will refine severity
    with domain rules; this value keeps damage_detections.severity_score
    meaningful from day one.
    """
    area_term = min(1.0, rel_area * 10)
    return round(min(1.0, 0.4 * confidence + 0.6 * area_term), 4)


class Detector:
    """Wraps a loaded Ultralytics model + its class mapping."""

    def __init__(self, model, class_mapping: dict[str, str], model_id: uuid.UUID) -> None:
        self._model = model
        self._mapping = class_mapping
        self.model_id = model_id

    @classmethod
    async def from_weights(
        cls, weights: bytes, class_mapping: dict[str, str], model_id: uuid.UUID
    ) -> "Detector":
        """Load a YOLO model from raw weight bytes (worker thread)."""

        def _load():
            from ultralytics import YOLO  # heavy import kept out of module load

            tmp_dir = Path(tempfile.gettempdir()) / "roadvisionai_models"
            tmp_dir.mkdir(exist_ok=True)
            weights_file = tmp_dir / f"{model_id}.pt"
            if not weights_file.exists():
                weights_file.write_bytes(weights)
            return YOLO(str(weights_file))

        model = await anyio.to_thread.run_sync(_load)
        log.info("model_loaded", model_id=str(model_id), classes=len(model.names))
        return cls(model, class_mapping, model_id)

    async def detect(self, image_path: str | Path) -> list[Detection]:
        """Run inference on one image file, return mapped detections."""

        def _predict():
            return self._model.predict(str(image_path), conf=CONFIDENCE_THRESHOLD, verbose=False)[0]

        result = await anyio.to_thread.run_sync(_predict)
        detections: list[Detection] = []
        for box in result.boxes:
            class_name = self._model.names[int(box.cls)]
            conf = float(box.conf)
            # xywhn: normalised centre-x, centre-y, width, height
            xc, yc, w, h = (float(v) for v in box.xywhn[0])
            x, y = max(0.0, xc - w / 2), max(0.0, yc - h / 2)
            w, h = max(1e-4, min(w, 1.0)), max(1e-4, min(h, 1.0))
            detections.append(
                Detection(
                    damage_code=resolve_code(class_name, self._mapping),
                    confidence=round(conf, 4),
                    severity=_provisional_severity(conf, w * h),
                    bbox_x=round(x, 4),
                    bbox_y=round(y, 4),
                    bbox_width=round(w, 4),
                    bbox_height=round(h, 4),
                )
            )
        log.info("inference_done", image=str(image_path), detections=len(detections))
        return detections
