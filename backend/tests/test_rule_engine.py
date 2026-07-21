"""Week 4 Step 1 — RuleEngine unit tests + recommendation integration tests.

Unit part: hand-built rules, every expected decision reasoned in comments.
Integration part: real DB with the seeded rule base (03_seed_rules.sql),
full chain analysis_results + pci_scores -> API -> maintenance_recommendations.
"""

import uuid
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from app.ai.engines.rule_engine import (
    AnalysisContext,
    RuleFormatError,
    evaluate,
)
from app.db.models.enums import MaintenanceStrategy
from app.db.session import get_session_factory, init_engine
from app.main import create_app
from sqlalchemy import text

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}


def rule(code, priority, condition, action, active=True):
    return SimpleNamespace(
        code=code,
        name=code,
        priority=priority,
        condition=condition,
        action=action,
        is_active=active,
    )


def ctx(pci, dominant="POTHOLE", detections=5):
    from app.ai.engines.pci_engine import classify_priority, classify_severity

    return AnalysisContext(
        pci=pci,
        severity_level=classify_severity(pci),
        priority_level=classify_priority(pci),
        dominant_damage_type=dominant,
        total_detections=detections,
    )


# ---------------- Unit: matching semantics ----------------


def test_first_match_by_priority_wins() -> None:
    """Two matching rules: priority 10 beats priority 20."""
    rules = [
        rule("B_SECOND", 20, '{"pci_max": 50}', '{"strategy": "RESURFACAGE"}'),
        rule("A_FIRST", 10, '{"pci_max": 50}', '{"strategy": "RECONSTRUCTION"}'),
    ]
    decision = evaluate(rules, ctx(35.0))
    assert decision.strategy == MaintenanceStrategy.RECONSTRUCTION
    assert decision.rule_code == "A_FIRST"


def test_pci_bounds_are_half_open() -> None:
    """pci_min <= PCI < pci_max: 55.0 matches [55,70) but 70.0 does not."""
    r = [rule("R", 10, '{"pci_min": 55, "pci_max": 70}', '{"strategy": "COLMATAGE"}')]
    assert evaluate(r, ctx(55.0)).rule_code == "R"
    assert evaluate(r, ctx(69.99)).rule_code == "R"
    assert evaluate(r, ctx(70.0)).rule_code == "FALLBACK"


def test_dominant_type_filter() -> None:
    r = [rule("R", 10, '{"dominant_type_in": ["RUTTING"]}', '{"strategy": "RESURFACAGE"}')]
    assert evaluate(r, ctx(60, dominant="RUTTING")).rule_code == "R"
    assert evaluate(r, ctx(60, dominant="POTHOLE")).rule_code == "FALLBACK"
    assert evaluate(r, ctx(60, dominant=None)).rule_code == "FALLBACK"


def test_inactive_rules_are_skipped_and_fallback_is_surveillance() -> None:
    r = [rule("R", 10, "{}", '{"strategy": "RECONSTRUCTION"}', active=False)]
    decision = evaluate(r, ctx(20.0))
    assert decision.rule_code == "FALLBACK"
    assert decision.strategy == MaintenanceStrategy.SURVEILLANCE
    assert "20.00" in decision.justification  # context rendered into the text


def test_action_fields_and_justification_rendering() -> None:
    r = [
        rule(
            "R",
            10,
            '{"pci_max": 55}',
            '{"strategy": "REHABILITATION", "estimated_days": 45, "deadline_days": 60,'
            ' "cost_min_mad": 400000, "cost_max_mad": 1200000,'
            ' "justification": "PCI {pci}, dominante {dominant}, {detections} det."}',
        )
    ]
    d = evaluate(r, ctx(48.5, dominant="ALLIGATOR_CRACK", detections=12))
    assert d.estimated_days == 45 and d.deadline_days == 60
    assert d.cost_min_mad == Decimal("400000")
    assert d.justification == "PCI 48.50, dominante ALLIGATOR_CRACK, 12 det."


def test_malformed_rule_fails_loudly() -> None:
    with pytest.raises(RuleFormatError):
        evaluate([rule("BAD", 10, "not json", "{}")], ctx(50))
    with pytest.raises(RuleFormatError):
        evaluate([rule("BAD", 10, "{}", '{"strategy": "INVALIDE"}')], ctx(50))


# ---------------- Unit: the seeded rule base, hand-checked ----------------


async def _seeded_rules():
    init_engine()
    from app.db.models.maintenance import Rule
    from sqlalchemy import select

    async with get_session_factory()() as s:
        return list((await s.execute(select(Rule).where(Rule.is_active.is_(True)))).scalars().all())


async def test_seeded_base_decisions_hand_checked() -> None:
    """The 9 seeded rules produce the expected strategy per scenario:
    PCI 30 -> RECONSTRUCTION (R010) ; PCI 48 + POTHOLE -> REHABILITATION (R020) ;
    PCI 48 + RAVELLING -> RESURFACAGE (R021) ; PCI 60 + RUTTING -> RESURFACAGE (R030) ;
    PCI 60 + LONGITUDINAL_CRACK -> COLMATAGE (R031) ; PCI 60 + POTHOLE -> COLMATAGE (R032) ;
    PCI 75 + EDGE_CRACKING -> COLMATAGE préventif (R040) ; PCI 75 + POTHOLE -> SURVEILLANCE (R041) ;
    PCI 97.83 (démo réelle) -> SURVEILLANCE (R050)."""
    rules = await _seeded_rules()
    assert len(rules) >= 9
    cases = [
        (ctx(30, "POTHOLE"), MaintenanceStrategy.RECONSTRUCTION, "R010_CRITIQUE_RECONSTRUCTION"),
        (
            ctx(48, "POTHOLE"),
            MaintenanceStrategy.REHABILITATION,
            "R020_GRAVE_STRUCTUREL_REHABILITATION",
        ),
        (ctx(48, "RAVELLING"), MaintenanceStrategy.RESURFACAGE, "R021_GRAVE_DEFAUT_RESURFACAGE"),
        (ctx(60, "RUTTING"), MaintenanceStrategy.RESURFACAGE, "R030_MODERE_SURFACE_RESURFACAGE"),
        (
            ctx(60, "LONGITUDINAL_CRACK"),
            MaintenanceStrategy.COLMATAGE,
            "R031_MODERE_FISSURES_COLMATAGE",
        ),
        (ctx(60, "POTHOLE"), MaintenanceStrategy.COLMATAGE, "R032_MODERE_DEFAUT_COLMATAGE"),
        (
            ctx(75, "EDGE_CRACKING"),
            MaintenanceStrategy.COLMATAGE,
            "R040_BON_FISSURES_COLMATAGE_PREVENTIF",
        ),
        (ctx(75, "POTHOLE"), MaintenanceStrategy.SURVEILLANCE, "R041_BON_SURVEILLANCE"),
        (
            ctx(97.83, "EDGE_CRACKING"),
            MaintenanceStrategy.SURVEILLANCE,
            "R050_EXCELLENT_SURVEILLANCE",
        ),
    ]
    for context, strategy, code in cases:
        d = evaluate(rules, context)
        assert (d.strategy, d.rule_code) == (strategy, code), (
            f"PCI {context.pci}/{context.dominant_damage_type}: got {d.rule_code}"
        )


# ---------------- Integration: full chain through the API ----------------


@pytest.fixture
async def client() -> httpx.AsyncClient:
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _auth(client) -> dict:
    resp = await client.post("/api/auth/login", json=ADMIN)
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _fixture_analysis(pci: float, dominant: str, detections: int) -> uuid.UUID:
    """Real rows: section -> inspection(TERMINEE) -> analysis_result + pci_score."""
    init_engine()
    ids = {k: uuid.uuid4() for k in ("section", "inspection", "analysis")}
    from app.ai.engines.pci_engine import classify_priority, classify_severity

    async with get_session_factory()() as s:
        admin_id = (
            await s.execute(text("SELECT id FROM users WHERE username='admin'"))
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO road_sections (id, section_code, road_name, road_type) "
                "VALUES (:id, :c, 'RN règle', 'NATIONALE')"
            ),
            {"id": ids["section"], "c": f"RUL-{ids['section'].hex[:8]}"},
        )
        await s.execute(
            text(
                "INSERT INTO inspections (id, road_section_id, created_by, status) "
                "VALUES (:id, :s, :u, 'TERMINEE')"
            ),
            {"id": ids["inspection"], "s": ids["section"], "u": admin_id},
        )
        await s.execute(
            text(
                "INSERT INTO analysis_results (id, inspection_id, total_detections, "
                "dominant_damage_type, recommendation_confidence) "
                "VALUES (:id, :i, :n, :d, 0.66)"
            ),
            {"id": ids["analysis"], "i": ids["inspection"], "n": detections, "d": dominant},
        )
        await s.execute(
            text(
                "INSERT INTO pci_scores (inspection_id, score, severity_level, priority_level) "
                "VALUES (:i, :score, :sev, :prio)"
            ),
            {
                "i": ids["inspection"],
                "score": pci,
                "sev": classify_severity(pci).value,
                "prio": classify_priority(pci).value,
            },
        )
        await s.commit()
    return ids["analysis"]


async def test_generate_recommendation_grave_pothole(client) -> None:
    """PCI 48 + POTHOLE -> REHABILITATION via R020, EN_ATTENTE (HITL rule #1)."""
    headers = await _auth(client)
    analysis_id = await _fixture_analysis(48.0, "POTHOLE", 12)

    resp = await client.post(f"/api/analysis-results/{analysis_id}/recommendation", headers=headers)
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    assert rec["strategy"] == "REHABILITATION"
    assert rec["status"] == "EN_ATTENTE"  # never born validated
    assert "48.00" in rec["justification"]  # rule code now lives in xai_explanations.rules_applied
    assert rec["estimated_days"] == 45
    assert rec["deadline"] is not None
    assert float(rec["confidence"]) == pytest.approx(0.66)

    dup = await client.post(f"/api/analysis-results/{analysis_id}/recommendation", headers=headers)
    assert dup.status_code == 409  # uq_rec_analysis

    detail = await client.get(f"/api/recommendations/{rec['id']}", headers=headers)
    assert detail.status_code == 200
    assert detail.json()["status"] == "EN_ATTENTE"

    listing = await client.get("/api/recommendations", headers=headers)
    assert listing.status_code == 200
    assert listing.json()["total"] >= 1  # FIFO inbox; ours may be beyond page 1


async def test_generate_for_unknown_analysis_is_404(client) -> None:
    headers = await _auth(client)
    resp = await client.post(
        f"/api/analysis-results/{uuid.uuid4()}/recommendation", headers=headers
    )
    assert resp.status_code == 404
