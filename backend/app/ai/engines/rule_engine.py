"""RuleEngine — deterministic maintenance-strategy selection (Week 4, SD05).

Same reliability philosophy as the PCIEngine: pure evaluation, no I/O, no LLM.
The rules live in the `rules` table; this module defines their format and the
matching semantics. Gemini (Step 3) will NARRATE the decision and ground it in
normative references — it will never make the decision.

Rule DSL (stored in rules.condition / rules.action as JSON text)
----------------------------------------------------------------
condition — all present fields must hold (AND semantics), absent = wildcard:
    {"pci_min": 40, "pci_max": 55,            # pci_min <= PCI < pci_max
     "severity_in": ["GRAVE", "CRITIQUE"],
     "priority_in": ["P1_URGENT"],
     "dominant_type_in": ["POTHOLE", "ALLIGATOR_CRACK"],
     "min_detections": 1}

action:
    {"strategy": "REHABILITATION",
     "estimated_days": 21, "deadline_days": 60,
     "cost_min_mad": 250000, "cost_max_mad": 600000,
     "justification": "PCI de {pci} avec dominance {dominant} : ..."}

Matching: active rules are evaluated in (priority ASC, code ASC) order; the
FIRST match wins. A built-in SURVEILLANCE fallback guarantees a decision even
with an empty rules table (documented safe default).
"""

import json
from dataclasses import dataclass
from decimal import Decimal

import structlog

from app.db.models.enums import MaintenanceStrategy, PriorityLevel, SeverityLevel

log = structlog.get_logger("app.ai.rule_engine")


@dataclass(frozen=True)
class AnalysisContext:
    """Facts the rules are evaluated against (from pci_scores + analysis_results)."""

    pci: float
    severity_level: SeverityLevel
    priority_level: PriorityLevel
    dominant_damage_type: str | None
    total_detections: int


@dataclass(frozen=True)
class RuleDecision:
    strategy: MaintenanceStrategy
    rule_code: str
    rule_name: str
    justification: str
    estimated_days: int | None = None
    deadline_days: int | None = None
    cost_min_mad: Decimal | None = None
    cost_max_mad: Decimal | None = None


FALLBACK = RuleDecision(
    strategy=MaintenanceStrategy.SURVEILLANCE,
    rule_code="FALLBACK",
    rule_name="Surveillance par défaut",
    justification=(
        "Aucune règle active ne correspond au contexte (PCI {pci}, type dominant "
        "{dominant}) : mise sous surveillance par défaut — décision conservatrice "
        "documentée, à réviser par l'ingénieur."
    ),
)


class RuleFormatError(ValueError):
    """A rule's condition/action JSON is malformed — surfaced, never swallowed."""


def _parse(raw: str, rule_code: str, kind: str) -> dict:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuleFormatError(f"Rule {rule_code}: invalid {kind} JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise RuleFormatError(f"Rule {rule_code}: {kind} must be a JSON object")
    return parsed


def _matches(cond: dict, ctx: AnalysisContext, rule_code: str) -> bool:
    if "pci_min" in cond and not ctx.pci >= float(cond["pci_min"]):
        return False
    if "pci_max" in cond and not ctx.pci < float(cond["pci_max"]):
        return False
    if "severity_in" in cond and ctx.severity_level.value not in cond["severity_in"]:
        return False
    if "priority_in" in cond and ctx.priority_level.value not in cond["priority_in"]:
        return False
    if "dominant_type_in" in cond:
        if ctx.dominant_damage_type is None:
            return False
        if ctx.dominant_damage_type not in cond["dominant_type_in"]:
            return False
    return not (
        "min_detections" in cond
        and ctx.total_detections < int(cond["min_detections"])
    )


def _render(template: str, ctx: AnalysisContext) -> str:
    return template.format(
        pci=f"{ctx.pci:.2f}",
        dominant=ctx.dominant_damage_type or "aucun",
        severity=ctx.severity_level.value,
        priority=ctx.priority_level.value,
        detections=ctx.total_detections,
    )


def evaluate(rules: list, ctx: AnalysisContext) -> RuleDecision:
    """First-match evaluation over active rules sorted by (priority, code).

    `rules` are ORM Rule rows (or any objects with .code/.name/.condition/
    .action/.priority/.is_active). Malformed rules raise RuleFormatError —
    a broken rule base must fail loudly, not silently skip safety rules.
    """
    ordered = sorted((r for r in rules if r.is_active), key=lambda r: (r.priority, r.code))
    for rule in ordered:
        cond = _parse(rule.condition, rule.code, "condition")
        if not _matches(cond, ctx, rule.code):
            continue
        action = _parse(rule.action, rule.code, "action")
        try:
            strategy = MaintenanceStrategy(action["strategy"])
        except (KeyError, ValueError) as exc:
            raise RuleFormatError(f"Rule {rule.code}: action.strategy missing or invalid") from exc
        decision = RuleDecision(
            strategy=strategy,
            rule_code=rule.code,
            rule_name=rule.name,
            justification=_render(
                action.get("justification", "Règle {code} appliquée.").replace("{code}", rule.code),
                ctx,
            ),
            estimated_days=action.get("estimated_days"),
            deadline_days=action.get("deadline_days"),
            cost_min_mad=(
                Decimal(str(action["cost_min_mad"])) if "cost_min_mad" in action else None
            ),
            cost_max_mad=(
                Decimal(str(action["cost_max_mad"])) if "cost_max_mad" in action else None
            ),
        )
        log.info("rule_matched", rule=rule.code, strategy=strategy.value, pci=ctx.pci)
        return decision

    log.warning("no_rule_matched_fallback", pci=ctx.pci, dominant=ctx.dominant_damage_type)
    return RuleDecision(
        strategy=FALLBACK.strategy,
        rule_code=FALLBACK.rule_code,
        rule_name=FALLBACK.rule_name,
        justification=_render(FALLBACK.justification, ctx),
    )
