"""LangGraph recommendation pipeline (SD05, TechStack §6).

A small, auditable agent graph — not a black box. Four nodes, linear:

    rule_node      deterministic RuleEngine -> strategy (the DECISION)
        |
    retrieve_node  RAG query built from the analysis -> normative passages
        |
    narrate_node   Gemini writes the justification, CITING the passages
        |          (business rule #6: >= 1 normative reference, or we fail closed)
    assemble_node  build the XAI record (rules, refs, breakdown, agents)

Key guarantees:
  * The LLM never decides the strategy — the RuleEngine does. Gemini only
    narrates and grounds. If it invents a strategy, we keep the rule's.
  * Fail-closed on rule #6: if retrieval returns nothing citable, the graph
    still produces a recommendation but flags missing_normative_refs so the
    HITL reviewer sees the gap — we never fabricate a reference.
  * Every provider (LLM, RAG) is injected: the whole graph runs in tests
    with deterministic fakes, no API key, no network.
"""

import json
from dataclasses import dataclass, field
from typing import Any, TypedDict

import structlog
from langgraph.graph import END, StateGraph

from app.ai.engines.rule_engine import AnalysisContext, RuleDecision, evaluate

log = structlog.get_logger("app.ai.agents.pipeline")

NARRATE_SYSTEM = (
    "Tu es un ingénieur routier senior de la Direction Générale des Routes du Maroc. "
    "On te fournit une décision de maintenance DÉJÀ PRISE par un moteur de règles "
    "déterministe, ainsi que des extraits de documents normatifs. Ta seule tâche est "
    "de rédiger une justification technique en français qui explique la décision et "
    "s'APPUIE EXPLICITEMENT sur les extraits fournis. Tu ne dois JAMAIS changer la "
    "stratégie décidée. Tu dois citer au moins une référence par son titre et sa page. "
    "Réponds UNIQUEMENT en JSON: "
    '{"justification": "...", "cited_refs": [{"title": "...", "page": "..."}]}'
)


class GraphState(TypedDict, total=False):
    ctx: AnalysisContext
    rules: list
    decision: RuleDecision
    passages: list[dict]
    justification: str
    cited_refs: list[dict]
    missing_normative_refs: bool


@dataclass
class PipelineResult:
    decision: RuleDecision
    justification: str
    normative_refs: list[dict]
    passages: list[dict]
    missing_normative_refs: bool
    agents_involved: list[str] = field(default_factory=list)


def build_graph(*, rag_search, llm_generate):
    """Compile the agent graph. `rag_search(query)->list[dict]` and
    `llm_generate(system, prompt)->str` are injected (async callables)."""

    async def rule_node(state: GraphState) -> GraphState:
        decision = evaluate(state["rules"], state["ctx"])
        log.info("agent_rule", strategy=decision.strategy.value, rule=decision.rule_code)
        return {"decision": decision}

    async def retrieve_node(state: GraphState) -> GraphState:
        ctx, decision = state["ctx"], state["decision"]
        query = (
            f"stratégie {decision.strategy.value} pour {ctx.dominant_damage_type or 'dégradation'} "
            f"chaussée PCI {ctx.pci:.0f} entretien routier norme"
        )
        passages = await rag_search(query)
        log.info("agent_retrieve", passages=len(passages))
        return {"passages": passages}

    async def narrate_node(state: GraphState) -> GraphState:
        ctx, decision, passages = state["ctx"], state["decision"], state["passages"]
        if not passages:
            # Fail-closed on rule #6: no fabricated reference.
            return {
                "justification": decision.justification,
                "cited_refs": [],
                "missing_normative_refs": True,
            }
        refs_block = "\n\n".join(
            f"[{i + 1}] {p['title']} (p.{p['page_start']}-{p['page_end']}) : {p['text'][:800]}"
            for i, p in enumerate(passages)
        )
        prompt = (
            f"CONTEXTE DE L'INSPECTION :\n"
            f"- Score PCI : {ctx.pci:.2f}/100 (sévérité {ctx.severity_level.value}, "
            f"priorité {ctx.priority_level.value})\n"
            f"- Type de dégradation dominant : {ctx.dominant_damage_type or 'aucun'}\n"
            f"- Nombre de détections : {ctx.total_detections}\n\n"
            f"DÉCISION DU MOTEUR DE RÈGLES (à justifier, NON à modifier) :\n"
            f"- Stratégie : {decision.strategy.value}\n"
            f"- Règle appliquée : {decision.rule_code} — {decision.rule_name}\n\n"
            f"EXTRAITS NORMATIFS DISPONIBLES :\n{refs_block}\n\n"
            f"Rédige la justification en citant au moins un extrait ci-dessus."
        )
        raw = await llm_generate(system=NARRATE_SYSTEM, prompt=prompt)
        try:
            parsed = json.loads(raw)
            justification = parsed.get("justification", "").strip()
            cited = parsed.get("cited_refs", [])
        except (json.JSONDecodeError, AttributeError):
            # LLM returned non-JSON: fall back to the rule justification but
            # keep the retrieved passages as references (still grounded).
            justification = decision.justification
            cited = [
                {"title": p["title"], "page": f"{p['page_start']}-{p['page_end']}"}
                for p in passages[:2]
            ]
        if not justification:
            justification = decision.justification
        return {
            "justification": justification,
            "cited_refs": cited,
            "missing_normative_refs": False,
        }

    graph = StateGraph(GraphState)
    graph.add_node("rule", rule_node)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("narrate", narrate_node)
    graph.set_entry_point("rule")
    graph.add_edge("rule", "retrieve")
    graph.add_edge("retrieve", "narrate")
    graph.add_edge("narrate", END)
    return graph.compile()


async def run_pipeline(
    *, ctx: AnalysisContext, rules: list, rag_search, llm_generate
) -> PipelineResult:
    graph = build_graph(rag_search=rag_search, llm_generate=llm_generate)
    final: dict[str, Any] = await graph.ainvoke({"ctx": ctx, "rules": rules})

    passages = final.get("passages", [])
    normative_refs = final.get("cited_refs") or [
        {"title": p["title"], "page": f"{p['page_start']}-{p['page_end']}"} for p in passages[:3]
    ]
    return PipelineResult(
        decision=final["decision"],
        justification=final["justification"],
        normative_refs=normative_refs,
        passages=passages,
        missing_normative_refs=final.get("missing_normative_refs", False),
        agents_involved=["RuleEngine", "KnowledgeRetrievalAgent", "TechnicalNarrator"],
    )
