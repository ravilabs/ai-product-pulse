"""
Deterministic scoring and verdict evaluation. No file I/O, no LLM calls —
this is the part of AI Product Pulse that stays true to "zero LLM calls
in the tool layer." Layer scores (1-5) arrive already assigned by the
calling agent's judgment against the maturity_ladder; everything in this
file is arithmetic and rule matching over those scores plus whatever
indicator evidence came with them.

A note on the "formula" strings inside framework.json (e.g. "min(layer_scores)",
"weighted_mean(layer_scores, weights)"): those are documentation, read by
a human, not a mini-language this file parses or evals. Evaluating an
arbitrary string from a data file would be a code-execution risk for no
real benefit here — the actual formula lives in Python below, and the
string in framework.json exists so a reader doesn't have to open this
file to know what the number means.
"""
from __future__ import annotations

from typing import Any, Callable

from .entities import Framework, IndicatorEvidence, VerdictResult

_OPERATORS = {
    "gte": lambda value, threshold: value >= threshold,
    "lte": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "lt": lambda value, threshold: value < threshold,
    "eq": lambda value, threshold: value == threshold,
}


def apply_risk_thresholds(
    fw: Framework, indicator_evidence: dict[str, IndicatorEvidence]
) -> None:
    """Fills in risk_threshold_exceeded for every indicator that has both
    a tracked numeric value and a risk_threshold defined in framework.json.
    Mutates the evidence objects in place and overwrites any value the
    caller may have set — this is pure arithmetic, so it's computed here
    rather than trusted from agent input, where it could be gotten wrong
    inconsistently across harnesses."""
    all_indicators = {ind.id: ind for layer in fw.layers for ind in layer.indicators}
    for indicator_id, evidence in indicator_evidence.items():
        indicator_def = all_indicators.get(indicator_id)
        if indicator_def is None or indicator_def.risk_threshold is None:
            continue
        if evidence.value is None:
            evidence.risk_threshold_exceeded = None
            continue
        rt = indicator_def.risk_threshold
        evidence.risk_threshold_exceeded = _OPERATORS[rt.operator](evidence.value, rt.value)


def compute_overall_score(fw: Framework, layer_scores: dict[str, int]) -> float:
    """weighted_mean(layer_scores, weights) — see scoring.overall_score
    in framework.json.

    Computed in integer milliunits (weight * 1000, rounded) through the
    final rounding step, not naive float summation followed by round().
    This is not defensive style — it fixes a real, confirmed
    cross-language parity bug: CPython 3.12's built-in sum() uses
    compensated (Neumaier) summation for floats, which is more
    numerically precise than a naive accumulator loop. For most inputs
    this makes no visible difference, but for layer_scores=(4, 2, 1)
    against this framework's weights, the true weighted sum lands
    exactly on 2.335 — a binary-float knife's edge where Python's sum()
    and a naive TypeScript `total += x` loop landed on opposite sides,
    producing 2.33 in Python and 2.34 in TypeScript for identical input.
    Integer arithmetic up to the single final IEEE-754 division (which
    is deterministic and cross-platform identical by spec) removes the
    ambiguity instead of hoping summation order never matters. Rounds
    half up (away from zero) explicitly, rather than relying on
    whatever a language's binary-float round() happens to do at a tie."""
    weights = fw.scoring.overall_score.weights
    total_milliunits = sum(
        round(layer_scores[layer_id] * weight * 1000) for layer_id, weight in weights.items()
    )
    remainder = total_milliunits % 10
    rounded_milliunits = total_milliunits - remainder + (10 if remainder >= 5 else 0)
    return rounded_milliunits / 1000


def compute_maturity_level(layer_scores: dict[str, int]) -> int:
    """min(layer_scores) — see scoring.maturity_level in framework.json.
    Deliberately the minimum, not the mean: the Triangle is only as
    strong as its weakest vertex."""
    return min(layer_scores.values())


# ── verdict trigger handlers ────────────────────────────────────────────
# One function per trigger_type in framework.json. "Global" handlers
# return a bool (fires once, or not at all). "Per-layer" handlers return
# the list of layer_ids that matched, since that trigger_type is
# evaluated once per layer, not once per report.


def _all_layers_gte(layer_scores: dict[str, int], trigger: dict[str, Any], **_: Any) -> bool:
    return all(score >= trigger["value"] for score in layer_scores.values())


def _layer_equals(layer_scores: dict[str, int], trigger: dict[str, Any], **_: Any) -> bool:
    return bool(layer_scores[trigger["layer"]] == trigger["value"])


def _layer_gte_and_indicator_risk_threshold(
    layer_scores: dict[str, int],
    indicator_evidence: dict[str, IndicatorEvidence],
    trigger: dict[str, Any],
    **_: Any,
) -> bool:
    if layer_scores[trigger["layer"]] < trigger["layer_min_value"]:
        return False
    evidence = indicator_evidence.get(trigger["indicator"])
    return bool(evidence and evidence.risk_threshold_exceeded)


def _layer_equals_and_other_gte(layer_scores: dict[str, int], trigger: dict[str, Any], **_: Any) -> bool:
    if layer_scores[trigger["layer"]] != trigger["value"]:
        return False
    others = [s for lid, s in layer_scores.items() if lid != trigger["layer"]]
    threshold = trigger["other_layers_min_value"]
    mode = trigger.get("other_layers_mode", "any")
    if mode == "any":
        return any(s >= threshold for s in others)
    if mode == "all":
        return all(s >= threshold for s in others)
    raise ValueError(f"Unknown other_layers_mode: '{mode}'")


def _per_layer_equals_with_other_gte(
    layer_scores: dict[str, int], trigger: dict[str, Any], **_: Any
) -> list[str]:
    excluded = set(trigger.get("excluded_layers", []))
    this_value = trigger["this_layer_value"]
    other_min = trigger["other_layer_min_value"]
    matches: list[str] = []
    for layer_id, score in layer_scores.items():
        if layer_id in excluded or score != this_value:
            continue
        others = [s for other_id, s in layer_scores.items() if other_id != layer_id]
        if any(s >= other_min for s in others):
            matches.append(layer_id)
    return matches


_GLOBAL_HANDLERS: dict[str, Callable[..., bool]] = {
    "all_layers_gte": _all_layers_gte,
    "layer_equals": _layer_equals,
    "layer_gte_and_indicator_risk_threshold": _layer_gte_and_indicator_risk_threshold,
    "layer_equals_and_other_gte": _layer_equals_and_other_gte,
}
_PER_LAYER_HANDLERS: dict[str, Callable[..., list[str]]] = {
    "per_layer_equals_with_other_gte": _per_layer_equals_with_other_gte,
}


def evaluate_verdicts(
    fw: Framework,
    layer_scores: dict[str, int],
    indicator_evidence: dict[str, IndicatorEvidence],
) -> list[VerdictResult]:
    """Evaluates every verdict rule in framework.json against the given
    scores and evidence, in priority order. Verdicts are not mutually
    exclusive by default — e.g. 'balanced' and 'trust_failure_signal' can
    both fire, because a feature can clear the coarse bar of every layer
    being instrumented while still showing an emerging trust problem, and
    the report should surface that rather than let the coarse pass hide
    it. blind_spot is the one deliberate exception: it explicitly excludes
    business_outcome via trigger.excluded_layers, so that layer's value-1
    case is only ever reported once, as business_outcome_orphaned."""
    layer_names: dict[str, str] = {layer.id: layer.name for layer in fw.layers}
    results: list[VerdictResult] = []

    for rule in sorted(fw.verdicts, key=lambda r: r.priority):
        trigger: dict[str, Any] = rule.trigger.model_dump()

        if rule.trigger_type in _PER_LAYER_HANDLERS:
            per_layer_handler = _PER_LAYER_HANDLERS[rule.trigger_type]
            matched_layer_ids = per_layer_handler(
                layer_scores=layer_scores, indicator_evidence=indicator_evidence, trigger=trigger
            )
            for layer_id in matched_layer_ids:
                message = (
                    rule.label_template.format(layer_name=layer_names[layer_id])
                    if rule.label_template
                    else rule.description
                )
                results.append(
                    VerdictResult(
                        verdict_id=rule.id, name=rule.name, severity=rule.severity,
                        layer_id=layer_id, message=message,
                    )
                )
        elif rule.trigger_type in _GLOBAL_HANDLERS:
            global_handler = _GLOBAL_HANDLERS[rule.trigger_type]
            fired = global_handler(
                layer_scores=layer_scores, indicator_evidence=indicator_evidence, trigger=trigger
            )
            if fired:
                results.append(
                    VerdictResult(
                        verdict_id=rule.id, name=rule.name, severity=rule.severity,
                        message=rule.description,
                    )
                )
        else:
            raise ValueError(
                f"No handler registered for trigger_type '{rule.trigger_type}' (verdict '{rule.id}'). "
                f"Known: {sorted({*_GLOBAL_HANDLERS, *_PER_LAYER_HANDLERS})}"
            )

    return results
