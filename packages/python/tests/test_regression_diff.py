from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from ai_product_pulse.domain.loader import load_framework
from ai_product_pulse.usecases.regression_diff import regression_diff
from ai_product_pulse.usecases.triage import LayerInput, triage

FW = load_framework()
T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
T1 = datetime(2026, 4, 1, tzinfo=timezone.utc)


def _feature(name: str, mp: int, pb: int, bo: int, at: datetime, pb_indicators=None):
    layers = [
        LayerInput(layer_id="model_performance", score=mp, evidence_summary="x"),
        LayerInput(layer_id="product_behaviour", score=pb, evidence_summary="x", indicators=pb_indicators or []),
        LayerInput(layer_id="business_outcome", score=bo, evidence_summary="x"),
    ]
    report = triage(name, layers, fw=FW)
    return report.model_copy(update={"generated_at": at})


# ── classification ───────────────────────────────────────────────────────


def test_improved_when_a_verdict_resolves_with_none_introduced():
    previous = _feature("Search", 4, 4, 1, T0)  # business_outcome_orphaned
    current = _feature("Search", 4, 4, 3, T1)  # fixed, now balanced too
    diff = regression_diff(previous, current)
    assert diff.summary == "improved"
    assert {v.verdict_id for v in diff.verdicts_resolved} == {"business_outcome_orphaned"}
    # "balanced" is newly introduced here too, but it's severity "none" —
    # good news, not a second kind of change that should make this "mixed".
    assert {v.verdict_id for v in diff.verdicts_introduced} == {"balanced"}


def test_regressed_when_a_verdict_is_introduced_with_none_resolved():
    previous = _feature("Search", 4, 4, 3, T0)  # balanced
    current = _feature("Search", 4, 4, 1, T1)  # now orphaned
    diff = regression_diff(previous, current)
    assert diff.summary == "regressed"
    assert {v.verdict_id for v in diff.verdicts_introduced} >= {"business_outcome_orphaned"}
    # "balanced" resolving away is real, reportable output — it's just
    # correctly excluded from the classification math, since losing a
    # severity-"none" verdict isn't what makes this a regression.
    assert {v.verdict_id for v in diff.verdicts_resolved} == {"balanced"}


def test_mixed_when_one_resolves_and_another_is_introduced():
    previous = _feature("Search", 1, 4, 4, T0)  # blind_spot: model_performance
    current = _feature("Search", 4, 1, 4, T1)  # blind_spot: product_behaviour instead
    diff = regression_diff(previous, current)
    assert diff.summary == "mixed"
    assert len(diff.verdicts_resolved) == 1
    assert len(diff.verdicts_introduced) == 1


def test_unchanged_when_nothing_moves():
    previous = _feature("Search", 3, 3, 3, T0)
    current = _feature("Search", 3, 3, 3, T1)
    diff = regression_diff(previous, current)
    assert diff.summary == "unchanged"
    assert diff.overall_score_delta == 0
    assert diff.maturity_level_delta == 0


def test_balanced_newly_firing_does_not_get_classified_as_mixed():
    """Regression test for a real bug found while writing this file:
    business_outcome_orphaned resolving into a newly-firing 'balanced'
    was classified as 'mixed' — treating a positive, severity-'none'
    verdict appearing as equivalent to a warning appearing. Confirms the
    fix: 'balanced' newly firing supports 'improved', it doesn't cancel
    it out into 'mixed'."""
    previous = _feature("Search", 4, 4, 1, T0)  # business_outcome_orphaned only
    current = _feature("Search", 4, 4, 3, T1)  # resolved, and now balanced fires too
    diff = regression_diff(previous, current)
    assert diff.summary == "improved"
    assert any(v.verdict_id == "balanced" for v in diff.verdicts_introduced)


def test_improved_on_score_movement_even_without_verdict_set_change():
    # both balanced (no verdicts either way), but scores genuinely rose
    previous = _feature("Search", 3, 3, 3, T0)
    current = _feature("Search", 4, 4, 4, T1)
    diff = regression_diff(previous, current)
    assert diff.summary == "improved"
    assert diff.verdicts_resolved == [] and diff.verdicts_introduced == []
    assert diff.overall_score_delta > 0


# ── the verdict-identity edge case this test file exists to prove ──────


def test_blind_spot_on_different_layers_is_resolved_and_introduced_not_persisting():
    """The exact scenario that would break a naive verdict_id-only diff:
    blind_spot fires for model_performance in `previous` and for
    product_behaviour in `current` — same verdict_id, different layer.
    These must not be treated as one verdict "persisting"."""
    previous = _feature("Search", 1, 4, 4, T0)
    current = _feature("Search", 4, 1, 4, T1)
    diff = regression_diff(previous, current)

    assert diff.verdicts_resolved[0].layer_id == "model_performance"
    assert diff.verdicts_introduced[0].layer_id == "product_behaviour"
    assert diff.verdicts_persisting == []


# ── layer-level diff detail ──────────────────────────────────────────────


def test_layer_changes_report_correct_deltas_and_maturity_labels():
    previous = _feature("Search", 2, 3, 1, T0)
    current = _feature("Search", 4, 3, 1, T1)
    diff = regression_diff(previous, current)
    mp_change = next(c for c in diff.layer_changes if c.layer_id == "model_performance")
    assert mp_change.previous_score == 2 and mp_change.current_score == 4
    assert mp_change.delta == 2
    assert mp_change.previous_maturity_label == "Ad Hoc"
    assert mp_change.current_maturity_label == "Operationalized"

    pb_change = next(c for c in diff.layer_changes if c.layer_id == "product_behaviour")
    assert pb_change.delta == 0


# ── guardrails ───────────────────────────────────────────────────────────


def test_rejects_different_subject_names():
    previous = _feature("Search", 3, 3, 3, T0)
    current = _feature("Summarizer", 3, 3, 3, T1)
    with pytest.raises(ValueError, match="same feature over time"):
        regression_diff(previous, current)


def test_rejects_mismatched_framework_versions():
    previous = _feature("Search", 3, 3, 3, T0)
    current = _feature("Search", 3, 3, 3, T1).model_copy(update={"framework_version": "0.0.9-fake"})
    with pytest.raises(ValueError, match="same framework_version"):
        regression_diff(previous, current)


def test_rejects_current_earlier_than_previous():
    previous = _feature("Search", 3, 3, 3, T1)  # later timestamp
    current = _feature("Search", 4, 4, 4, T0)  # earlier timestamp, passed as "current"
    with pytest.raises(ValueError, match="argument order"):
        regression_diff(previous, current)


def test_trust_failure_signal_can_resolve_via_indicator_evidence():
    previous = _feature(
        "Search", 4, 2, 3, T0,
        pb_indicators=[__import__("ai_product_pulse").domain.IndicatorEvidence(
            indicator_id="override_rate", tracked=True, value=46.0
        )],
    )
    current = _feature(
        "Search", 4, 2, 3, T1,
        pb_indicators=[__import__("ai_product_pulse").domain.IndicatorEvidence(
            indicator_id="override_rate", tracked=True, value=15.0
        )],
    )
    diff = regression_diff(previous, current)
    assert any(v.verdict_id == "trust_failure_signal" for v in diff.verdicts_resolved)
