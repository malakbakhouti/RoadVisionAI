"""PCIEngine — Pavement Condition Index per ASTM D6433 (CDC v5.0 formula).

DETERMINISTIC BY DESIGN: pure functions, no I/O, no LLM. This is the project's
core reliability argument — numeric results are reproducible and auditable,
the LLM (Week 4) only narrates them.

CDC formula
-----------
    PCI = 100 − Σ_types ( pci_weight × severity × density × 100 )

For each damage type present in the inspection:
  * pci_weight — the CDC weight from damage_types (POTHOLE 0.35 … STRIPING 0.05)
  * severity   — area-weighted mean severity of that type's detections [0, 1]
  * density    — damaged surface fraction: mean over the inspection's images
                 of the per-image damaged-area ratio for that type [0, 1]
The result is clamped to [0, 100].

Classification thresholds (CDC, aligned with ASTM D6433 condition ratings)
--------------------------------------------------------------------------
    PCI ≥ 85   -> FAIBLE    / P4_EXCELLENT
    70 ≤ PCI < 85 -> FAIBLE    / P3_SURVEILLANCE
    55 ≤ PCI < 70 -> MODERE    / P2_PLANIFIE
    40 ≤ PCI < 55 -> GRAVE     / P1_URGENT
    PCI < 40   -> CRITIQUE  / P0_CRITIQUE
"""

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from app.db.models.enums import PriorityLevel, SeverityLevel


@dataclass(frozen=True)
class DetectionInput:
    """One detection, as needed by the engine (decoupled from ORM/Detector)."""

    damage_code: str
    pci_weight: float  # from damage_types.pci_weight
    severity: float  # [0, 1]
    rel_area: float  # bbox area / image area, [0, 1]
    image_id: str  # groups detections per image for density


@dataclass(frozen=True)
class TypeDeduction:
    """Per-type breakdown — feeds xai_explanations.priority_breakdown."""

    damage_code: str
    pci_weight: float
    mean_severity: float
    density: float
    deduction: float  # points removed from 100


@dataclass(frozen=True)
class PciResult:
    score: Decimal  # [0, 100], 2 decimals — pci_scores.score is NUMERIC(5,2)
    severity_level: SeverityLevel
    priority_level: PriorityLevel
    deductions: list[TypeDeduction] = field(default_factory=list)


def _round2(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def classify_severity(pci: float) -> SeverityLevel:
    if pci >= 70:
        return SeverityLevel.FAIBLE
    if pci >= 55:
        return SeverityLevel.MODERE
    if pci >= 40:
        return SeverityLevel.GRAVE
    return SeverityLevel.CRITIQUE


def classify_priority(pci: float) -> PriorityLevel:
    if pci >= 85:
        return PriorityLevel.P4_EXCELLENT
    if pci >= 70:
        return PriorityLevel.P3_SURVEILLANCE
    if pci >= 55:
        return PriorityLevel.P2_PLANIFIE
    if pci >= 40:
        return PriorityLevel.P1_URGENT
    return PriorityLevel.P0_CRITIQUE


def compute_pci(detections: list[DetectionInput], total_images: int) -> PciResult:
    """Compute the inspection-level PCI from all its detections.

    total_images: number of analysed images in the inspection (density is a
    per-image mean, so images with zero damage of a type still dilute it —
    a single pothole across a 100-image survey must not tank the section).
    """
    if total_images < 1:
        raise ValueError("total_images must be >= 1")

    if not detections:
        return PciResult(
            score=Decimal("100.00"),
            severity_level=SeverityLevel.FAIBLE,
            priority_level=PriorityLevel.P4_EXCELLENT,
        )

    # Group by damage type
    by_type: dict[str, list[DetectionInput]] = {}
    for det in detections:
        if not (0 <= det.severity <= 1 and 0 <= det.rel_area <= 1):
            raise ValueError(f"severity/rel_area out of [0,1] for {det.damage_code}")
        by_type.setdefault(det.damage_code, []).append(det)

    deductions: list[TypeDeduction] = []
    total_deduction = 0.0
    for code, dets in sorted(by_type.items()):
        # density: per-image damaged-area ratio for this type, averaged over
        # ALL analysed images (absence counts as zero), capped at 1 per image
        per_image: dict[str, float] = {}
        for det in dets:
            per_image[det.image_id] = min(1.0, per_image.get(det.image_id, 0.0) + det.rel_area)
        density = sum(per_image.values()) / total_images

        # severity: area-weighted mean (a large severe pothole outweighs a speck)
        weight_sum = sum(d.rel_area for d in dets)
        if weight_sum > 0:
            mean_severity = sum(d.severity * d.rel_area for d in dets) / weight_sum
        else:  # degenerate zero-area boxes: plain mean
            mean_severity = sum(d.severity for d in dets) / len(dets)

        pci_weight = dets[0].pci_weight
        deduction = pci_weight * mean_severity * density * 100
        total_deduction += deduction
        deductions.append(
            TypeDeduction(
                damage_code=code,
                pci_weight=round(pci_weight, 4),
                mean_severity=round(mean_severity, 4),
                density=round(density, 4),
                deduction=round(deduction, 4),
            )
        )

    score = max(0.0, min(100.0, 100.0 - total_deduction))
    return PciResult(
        score=_round2(score),
        severity_level=classify_severity(score),
        priority_level=classify_priority(score),
        deductions=deductions,
    )
