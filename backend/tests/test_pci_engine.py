"""PCIEngine unit tests — every expected value below is COMPUTED BY HAND and
shown step by step in comments. This suite is the auditability proof of the
deterministic core (no DB, no mocks, pure arithmetic).
"""

from decimal import Decimal

import pytest
from app.ai.engines.pci_engine import (
    DetectionInput,
    classify_priority,
    classify_severity,
    compute_pci,
)
from app.db.models.enums import PriorityLevel, SeverityLevel

# CDC weights used throughout
POTHOLE_W = 0.35
ALLIGATOR_W = 0.30
STRIPING_W = 0.05


def det(code, w, sev, area, img="img1"):
    return DetectionInput(
        damage_code=code, pci_weight=w, severity=sev, rel_area=area, image_id=img
    )


def test_no_detections_is_perfect_road() -> None:
    result = compute_pci([], total_images=5)
    assert result.score == Decimal("100.00")
    assert result.severity_level == SeverityLevel.FAIBLE
    assert result.priority_level == PriorityLevel.P4_EXCELLENT
    assert result.deductions == []


def test_single_pothole_hand_computed() -> None:
    """1 image, 1 pothole: sev 0.8, area 5% of frame.

    density   = 0.05 (only image)
    severity  = 0.8  (single detection)
    deduction = 0.35 * 0.8 * 0.05 * 100 = 1.4
    PCI       = 100 - 1.4 = 98.60
    """
    result = compute_pci([det("POTHOLE", POTHOLE_W, 0.8, 0.05)], total_images=1)
    assert result.score == Decimal("98.60")
    assert result.priority_level == PriorityLevel.P4_EXCELLENT
    assert result.deductions[0].deduction == pytest.approx(1.4)


def test_two_types_hand_computed() -> None:
    """1 image. Pothole: sev 0.9, area 0.30. Alligator: sev 0.7, area 0.40.

    pothole   : 0.35 * 0.9 * 0.30 * 100 = 9.45
    alligator : 0.30 * 0.7 * 0.40 * 100 = 8.40
    PCI = 100 - 9.45 - 8.40 = 82.15  -> FAIBLE / P3_SURVEILLANCE
    """
    result = compute_pci(
        [
            det("POTHOLE", POTHOLE_W, 0.9, 0.30),
            det("ALLIGATOR_CRACK", ALLIGATOR_W, 0.7, 0.40),
        ],
        total_images=1,
    )
    assert result.score == Decimal("82.15")
    assert result.severity_level == SeverityLevel.FAIBLE
    assert result.priority_level == PriorityLevel.P3_SURVEILLANCE
    # breakdown reconciles exactly with the score
    assert sum(d.deduction for d in result.deductions) == pytest.approx(17.85)


def test_density_diluted_over_many_images() -> None:
    """Same pothole (sev 0.9, area 0.30) but the survey has 10 images.

    density   = 0.30 / 10 = 0.03
    deduction = 0.35 * 0.9 * 0.03 * 100 = 0.945
    PCI       = 100 - 0.945 = 99.06 (round half up on 99.055)
    A single localised defect must not tank a long section.
    """
    result = compute_pci([det("POTHOLE", POTHOLE_W, 0.9, 0.30)], total_images=10)
    assert result.score == Decimal("99.06")


def test_area_weighted_severity_hand_computed() -> None:
    """Two potholes, same image: (sev 1.0, area 0.10) and (sev 0.5, area 0.30).

    mean_severity = (1.0*0.10 + 0.5*0.30) / (0.10+0.30) = 0.25/0.40 = 0.625
    density       = 0.10 + 0.30 = 0.40
    deduction     = 0.35 * 0.625 * 0.40 * 100 = 8.75
    PCI           = 91.25
    """
    result = compute_pci(
        [det("POTHOLE", POTHOLE_W, 1.0, 0.10), det("POTHOLE", POTHOLE_W, 0.5, 0.30)],
        total_images=1,
    )
    assert result.score == Decimal("91.25")
    assert result.deductions[0].mean_severity == pytest.approx(0.625)
    assert result.deductions[0].density == pytest.approx(0.40)


def test_score_is_clamped_at_zero() -> None:
    """Pathological road: many maximal defects — PCI floors at 0, never negative."""
    dets = [
        det(code, w, 1.0, 1.0, img=f"img{i}")
        for i, (code, w) in enumerate(
            [("POTHOLE", 0.35), ("ALLIGATOR_CRACK", 0.30), ("RUTTING", 0.28),
             ("RAVELLING", 0.25)] * 3
        )
    ]
    result = compute_pci(dets, total_images=1)
    assert result.score == Decimal("0.00")
    assert result.severity_level == SeverityLevel.CRITIQUE
    assert result.priority_level == PriorityLevel.P0_CRITIQUE


def test_per_image_density_caps_at_one() -> None:
    """Overlapping boxes summing past the frame: per-image density caps at 1.

    Two striping detections areas 0.7 + 0.6 -> capped 1.0 on that image.
    deduction = 0.05 * severity * 1.0 * 100 with severity = (0.4*0.7+0.6*0.6)/1.3
              = 0.64/1.3 = 0.492307...
    deduction = 0.05 * 0.492307 * 1.0 * 100 = 2.4615...
    PCI = 97.54
    """
    result = compute_pci(
        [det("STRIPING", STRIPING_W, 0.4, 0.7), det("STRIPING", STRIPING_W, 0.6, 0.6)],
        total_images=1,
    )
    assert result.deductions[0].density == pytest.approx(1.0)
    assert result.score == Decimal("97.54")


def test_classification_thresholds_exact_boundaries() -> None:
    assert classify_priority(85) == PriorityLevel.P4_EXCELLENT
    assert classify_priority(84.99) == PriorityLevel.P3_SURVEILLANCE
    assert classify_priority(70) == PriorityLevel.P3_SURVEILLANCE
    assert classify_priority(55) == PriorityLevel.P2_PLANIFIE
    assert classify_priority(40) == PriorityLevel.P1_URGENT
    assert classify_priority(39.99) == PriorityLevel.P0_CRITIQUE
    assert classify_severity(70) == SeverityLevel.FAIBLE
    assert classify_severity(69.99) == SeverityLevel.MODERE
    assert classify_severity(54.99) == SeverityLevel.GRAVE
    assert classify_severity(39.99) == SeverityLevel.CRITIQUE


def test_invalid_inputs_are_rejected() -> None:
    with pytest.raises(ValueError):
        compute_pci([], total_images=0)
    with pytest.raises(ValueError):
        compute_pci([det("POTHOLE", POTHOLE_W, 1.5, 0.1)], total_images=1)
