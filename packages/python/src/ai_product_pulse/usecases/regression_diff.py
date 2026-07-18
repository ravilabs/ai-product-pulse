"""
regression_diff — compares two FeatureReport instances for the same
feature, taken at different points in time, and answers the question
this repo didn't have an answer for until now: did the team fix what
was flagged last time?

Like aggregate_product_pulse.py, this stays inline rather than growing
a separate domain/ engine file — the comparison logic here is a handful
of set operations and score subtractions, not a rule-dispatch system
like scoring_engine.py's verdict evaluation.
"""
from __future__ import annotations

from ..domain.entities import (
    FeatureReport,
    LayerChange,
    RegressionDiffResult,
    RegressionSummary,
    VerdictChange,
)


def _reject_mismatched_subject(previous: FeatureReport, current: FeatureReport) -> None:
    if previous.subject_name != current.subject_name:
        raise ValueError(
            f"regression_diff() compares the same feature over time — "
            f"got subject_name '{previous.subject_name}' vs '{current.subject_name}'. "
            "Comparing different features isn't a regression diff; that's what "
            "aggregate_product_pulse() is for."
        )


def _reject_mismatched_framework_version(previous: FeatureReport, current: FeatureReport) -> None:
    if previous.framework_version != current.framework_version:
        raise ValueError(
            "Both reports must share the same framework_version to diff — got "
            f"'{previous.framework_version}' vs '{current.framework_version}'. "
            "Re-run triage() for the outdated report against the current framework.json first."
        )


def _reject_out_of_order_timestamps(previous: FeatureReport, current: FeatureReport) -> None:
    if current.generated_at < previous.generated_at:
        raise ValueError(
            f"'current' ({current.generated_at.isoformat()}) is earlier than "
            f"'previous' ({previous.generated_at.isoformat()}) — check the argument order, "
            "regression_diff(previous, current) expects them chronologically."
        )


def _diff_layers(previous: FeatureReport, current: FeatureReport) -> list[LayerChange]:
    current_by_id = {layer.layer_id: layer for layer in current.layers}
    changes = []
    for prev_layer in previous.layers:
        cur_layer = current_by_id[prev_layer.layer_id]
        changes.append(
            LayerChange(
                layer_id=prev_layer.layer_id,
                previous_score=prev_layer.score,
                current_score=cur_layer.score,
                delta=cur_layer.score - prev_layer.score,
                previous_maturity_label=prev_layer.maturity_label,
                current_maturity_label=cur_layer.maturity_label,
            )
        )
    return changes


def _verdict_identity(verdict: VerdictChange) -> tuple[str, str | None]:
    """Two verdicts are "the same" for diffing purposes if they share a
    verdict_id AND a layer_id — Blind Spot: Model Performance resolving
    while Blind Spot: Product Behaviour is newly introduced are two
    different things, not one verdict "persisting"."""
    return (verdict.verdict_id, verdict.layer_id)


def _diff_verdicts(
    previous: FeatureReport, current: FeatureReport
) -> tuple[list[VerdictChange], list[VerdictChange], list[VerdictChange]]:
    previous_changes = [
        VerdictChange(verdict_id=v.verdict_id, name=v.name, severity=v.severity, layer_id=v.layer_id)
        for v in previous.verdicts
    ]
    current_changes = [
        VerdictChange(verdict_id=v.verdict_id, name=v.name, severity=v.severity, layer_id=v.layer_id)
        for v in current.verdicts
    ]

    previous_by_identity = {_verdict_identity(v): v for v in previous_changes}
    current_by_identity = {_verdict_identity(v): v for v in current_changes}

    resolved_ids = previous_by_identity.keys() - current_by_identity.keys()
    introduced_ids = current_by_identity.keys() - previous_by_identity.keys()
    persisting_ids = previous_by_identity.keys() & current_by_identity.keys()

    resolved = [previous_by_identity[i] for i in resolved_ids]
    introduced = [current_by_identity[i] for i in introduced_ids]
    persisting = [current_by_identity[i] for i in persisting_ids]
    return resolved, introduced, persisting


def _classify(
    overall_score_delta: float,
    maturity_level_delta: int,
    resolved: list[VerdictChange],
    introduced: list[VerdictChange],
) -> RegressionSummary:
    """Only verdicts with real severity count as "bad news" appearing or
    disappearing. 'balanced' (severity 'none') newly firing is good news,
    not a second, symmetric kind of change — treating it the same as a
    newly-introduced warning was a real bug caught by this file's own
    tests: business_outcome_orphaned resolving into balanced classified
    as "mixed" instead of "improved" until this filter was added."""
    negative_resolved = [v for v in resolved if v.severity != "none"]
    negative_introduced = [v for v in introduced if v.severity != "none"]

    if negative_introduced and not negative_resolved:
        return "regressed"
    if negative_resolved and not negative_introduced:
        return "improved"
    if negative_resolved and negative_introduced:
        return "mixed"
    # no negative-severity verdict changes — fall back to the underlying scores
    if maturity_level_delta > 0 or overall_score_delta > 0:
        return "improved"
    if maturity_level_delta < 0 or overall_score_delta < 0:
        return "regressed"
    return "unchanged"


def regression_diff(previous: FeatureReport, current: FeatureReport) -> RegressionDiffResult:
    """Compares two FeatureReports for the same feature, ordered in time.

    previous and current must share subject_name and framework_version —
    this compares one feature's trajectory, not two different features,
    and it doesn't compare across scoring epochs that might not mean the
    same thing. current must not be timestamped earlier than previous.
    """
    _reject_mismatched_subject(previous, current)
    _reject_mismatched_framework_version(previous, current)
    _reject_out_of_order_timestamps(previous, current)

    layer_changes = _diff_layers(previous, current)
    overall_score_delta = round(current.overall_score - previous.overall_score, 2)
    maturity_level_delta = current.maturity_level - previous.maturity_level
    resolved, introduced, persisting = _diff_verdicts(previous, current)

    return RegressionDiffResult(
        subject_name=current.subject_name,
        framework_version=current.framework_version,
        previous_generated_at=previous.generated_at,
        current_generated_at=current.generated_at,
        layer_changes=layer_changes,
        overall_score_delta=overall_score_delta,
        maturity_level_delta=maturity_level_delta,
        verdicts_resolved=resolved,
        verdicts_introduced=introduced,
        verdicts_persisting=persisting,
        summary=_classify(overall_score_delta, maturity_level_delta, resolved, introduced),
    )
