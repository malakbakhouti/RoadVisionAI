"""Week 4 Step 3 — LangGraph recommendation pipeline tests.

Real LangGraph graph execution; deterministic fakes for RAG and Gemini so the
orchestration, grounding, and fail-closed behaviour are tested exactly without
an API key or network. Integration test drives the whole thing through the API
against the real DB (rules seeded), writing maintenance_recommendations +
xai_explanations.
"""

import json
import uuid

import httpx
import pytest
from app.ai.agents.recommendation_pipeline import run_pipeline
from app.ai.engines.rule_engine import AnalysisContext
from app.db.models.enums import MaintenanceStrategy
from app.db.session import get_session_factory, init_engine
from app.main import create_app
from sqlalchemy import text

ADMIN = {"email": "admin@dgr.gov.ma", "password": "Admin@2026!"}


def _ctx(pci, dominant="LONGITUDINAL_CRACK", detections=4):
    from app.ai.engines.pci_engine import classify_priority, classify_severity

    return AnalysisContext(
        pci=pci,
        severity_level=classify_severity(pci),
        priority_level=classify_priority(pci),
        dominant_damage_type=dominant,
        total_detections=detections,
    )


async def _seeded_rules():
    init_engine()
    from app.db.models.maintenance import Rule
    from sqlalchemy import select

    async with get_session_factory()() as s:
        return list((await s.execute(select(Rule).where(Rule.is_active.is_(True)))).scalars().all())


FAKE_PASSAGES = [
    {
        "text": "Le colmatage des fissures longitudinales doit intervenir sous 120 jours "
        "pour prevenir les infiltrations (norme DGR).",
        "similarity": 0.82,
        "document_id": str(uuid.uuid4()),
        "title": "Norme entretien DGR",
        "doc_type": "NORME_DGR",
        "page_start": 12,
        "page_end": 13,
    }
]


async def fake_rag(query: str) -> list:
    return FAKE_PASSAGES


async def fake_rag_empty(query: str) -> list:
    return []


async def fake_llm(*, system: str, prompt: str) -> str:
    # A well-behaved Gemini: cites the provided passage, keeps the strategy.
    return json.dumps(
        {
            "justification": "La strategie de colmatage est justifiee : conformement a la "
            "Norme entretien DGR (p.12-13), les fissures longitudinales doivent etre "
            "colmatees sous 120 jours pour prevenir les infiltrations d'eau.",
            "cited_refs": [{"title": "Norme entretien DGR", "page": "12-13"}],
        }
    )


async def fake_llm_garbage(*, system: str, prompt: str) -> str:
    return "Ceci n'est pas du JSON valide."


# ---------------- Pipeline unit tests ----------------


async def test_pipeline_grounds_justification_in_passages() -> None:
    """Nominal: rule decides COLMATAGE, RAG returns a passage, Gemini cites it."""
    rules = await _seeded_rules()
    result = await run_pipeline(
        ctx=_ctx(60.0, "LONGITUDINAL_CRACK"),
        rules=rules,
        rag_search=fake_rag,
        llm_generate=fake_llm,
    )
    assert result.decision.strategy == MaintenanceStrategy.COLMATAGE
    assert "Norme entretien DGR" in result.justification
    assert len(result.normative_refs) >= 1
    assert result.normative_refs[0]["title"] == "Norme entretien DGR"
    assert result.missing_normative_refs is False
    assert "KnowledgeRetrievalAgent" in result.agents_involved


async def test_pipeline_fails_closed_without_passages() -> None:
    """Rule #6: no RAG hit -> rule justification kept, gap flagged, no fabricated ref."""
    rules = await _seeded_rules()
    result = await run_pipeline(
        ctx=_ctx(60.0, "LONGITUDINAL_CRACK"),
        rules=rules,
        rag_search=fake_rag_empty,
        llm_generate=fake_llm,
    )
    assert result.decision.strategy == MaintenanceStrategy.COLMATAGE
    assert result.missing_normative_refs is True
    assert result.normative_refs == []
    assert result.justification  # still has the rule justification


async def test_pipeline_survives_malformed_llm_output() -> None:
    """Gemini returns non-JSON: fall back to rule justification, keep passages as refs."""
    rules = await _seeded_rules()
    result = await run_pipeline(
        ctx=_ctx(60.0, "LONGITUDINAL_CRACK"),
        rules=rules,
        rag_search=fake_rag,
        llm_generate=fake_llm_garbage,
    )
    assert result.decision.strategy == MaintenanceStrategy.COLMATAGE
    assert len(result.normative_refs) >= 1  # passages salvaged as references
    assert result.missing_normative_refs is False


async def test_pipeline_never_lets_llm_change_strategy() -> None:
    """Even if the LLM 'suggests' another strategy, the rule's decision stands."""
    rules = await _seeded_rules()

    async def subversive_llm(*, system, prompt):
        return json.dumps(
            {"justification": "Je recommande une RECONSTRUCTION totale.", "cited_refs": []}
        )

    result = await run_pipeline(
        ctx=_ctx(97.83, "EDGE_CRACKING"),  # -> SURVEILLANCE per R050
        rules=rules,
        rag_search=fake_rag,
        llm_generate=subversive_llm,
    )
    assert result.decision.strategy == MaintenanceStrategy.SURVEILLANCE  # rule wins


# ---------------- Integration through the API ----------------


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
    init_engine()
    from app.ai.engines.pci_engine import classify_priority, classify_severity

    ids = {k: uuid.uuid4() for k in ("section", "inspection", "analysis")}
    async with get_session_factory()() as s:
        admin_id = (
            await s.execute(text("SELECT id FROM users WHERE username='admin'"))
        ).scalar_one()
        await s.execute(
            text(
                "INSERT INTO road_sections (id, section_code, road_name, road_type) "
                "VALUES (:id, :c, 'RN pipeline', 'NATIONALE')"
            ),
            {"id": ids["section"], "c": f"PIPE-{ids['section'].hex[:8]}"},
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
                "VALUES (:id, :i, :n, :d, 0.657)"
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


async def test_generate_writes_recommendation_and_xai(client) -> None:  # noqa: D103
    """End-to-end via API (no Gemini key -> graceful fallback), then verify the
    XAI record exists with rules + priority breakdown."""
    headers = await _auth(client)
    analysis_id = await _fixture_analysis(97.83, "EDGE_CRACKING", 4)

    resp = await client.post(f"/api/analysis-results/{analysis_id}/recommendation", headers=headers)
    assert resp.status_code == 201, resp.text
    rec = resp.json()
    assert rec["strategy"] == "SURVEILLANCE"  # R050, deterministic
    assert rec["status"] == "EN_ATTENTE"

    # XAI row written with the rule + breakdown
    init_engine()
    async with get_session_factory()() as s:
        xai = (
            await s.execute(
                text(
                    "SELECT rules_applied, priority_breakdown, agents_involved "
                    "FROM xai_explanations ORDER BY generated_at DESC LIMIT 1"
                )
            )
        ).one()
        rules_applied, breakdown, agents = xai
        assert any(r["code"].startswith("R050") for r in rules_applied)
        assert float(breakdown["pci"]) == pytest.approx(97.83)
        assert "RuleEngine" in agents
