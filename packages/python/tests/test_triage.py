"""
Scenario tests for the triage use case and the verdict rule engine
underneath it. Every verdict rule gets at least one test that proves it
fires under the right conditions, and the blind_spot/business_outcome
exclusion gets an explicit regression test — that's the bug this file
exists to make sure never comes back silently.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_product_pulse.domain.entities import IndicatorEvidence
from ai_product_pulse.domain.loader import load_framework
from ai_product_pulse.usecases.triage import LayerInput, triage

FW = load_framework()


def _layers(mp: int, pb: int, bo: int, pb_indicators=None) -> list[LayerInput]:
    """Shorthand for building the three required layers at given scores,
    optionally attaching indicator evidence to product_behaviour (the
    only layer whose indicators matter to any verdict trigger)."""
    return [
        LayerInput(layer_id="model_performance", score=mp, evidence_summary="x"),
        LayerInput(
            layer_id="product_behaviour", score=pb, evidence_summary="x",
            indicators=pb_indicators or [],
        ),
        LayerInput(layer_id="business_outcome", score=bo, evidence_summary="x"),
    ]


def _verdict_ids(report) -> set[str]:
    return {v.verdict_id for v in report.verdicts}


# ── balanced ─────────────────────────────────────────────────────────────


def test_balanced_fires_when_all_layers_at_least_instrumented():
    report = triage("Feature", _layers(3, 3, 3), fw=FW)
    assert "balanced" in _verdict_ids(report)


def test_balanced_does_not_fire_when_one_layer_below_three():
    report = triage("Feature", _layers(3, 3, 2), fw=FW)
    assert "balanced" not in _verdict_ids(report)


# ── business_outcome_orphaned ───────────────────────────────────────────


def test_business_outcome_orphaned_fires_on_bo_equals_one():
    report = triage("Feature", _layers(4, 4, 1), fw=FW)
    assert "business_outcome_orphaned" in _verdict_ids(report)


def test_business_outcome_orphaned_fires_regardless_of_other_layers():
    # Even with every other layer blind too — still fires. It's a flat
    # "== 1", not conditioned on the other layers looking good.
    report = triage("Feature", _layers(1, 1, 1), fw=FW)
    assert "business_outcome_orphaned" in _verdict_ids(report)


# ── the blind_spot / business_outcome exclusion (regression test) ─────


def test_blind_spot_does_not_duplicate_business_outcome_orphaned():
    """This is the exact bug found while writing the rule engine: blind_spot's
    trigger originally had no exclusion, so business_outcome==1 fired BOTH
    business_outcome_orphaned and 'Blind Spot: Business Outcome' — two
    verdicts stating the same fact. Confirms the fix holds."""
    report = triage("Feature", _layers(4, 4, 1), fw=FW)
    ids = _verdict_ids(report)
    assert "business_outcome_orphaned" in ids
    assert not any(
        v.verdict_id == "blind_spot" and v.layer_id == "business_outcome"
        for v in report.verdicts
    )


def test_blind_spot_still_fires_for_model_performance():
    report = triage("Feature", _layers(1, 4, 4), fw=FW)
    matches = [v for v in report.verdicts if v.verdict_id == "blind_spot"]
    assert len(matches) == 1
    assert matches[0].layer_id == "model_performance"
    assert "Model Performance" in matches[0].message  # label_template rendered


def test_blind_spot_still_fires_for_product_behaviour():
    report = triage("Feature", _layers(4, 1, 4), fw=FW)
    matches = [v for v in report.verdicts if v.verdict_id == "blind_spot"]
    assert len(matches) == 1
    assert matches[0].layer_id == "product_behaviour"


def test_blind_spot_can_fire_twice_for_two_untracked_layers():
    # model_performance and product_behaviour both blind, business_outcome
    # healthy enough (>=3) to be the "other layer" that satisfies the trigger.
    report = triage("Feature", _layers(1, 1, 3), fw=FW)
    blind_spots = {v.layer_id for v in report.verdicts if v.verdict_id == "blind_spot"}
    assert blind_spots == {"model_performance", "product_behaviour"}


def test_blind_spot_does_not_fire_if_no_other_layer_clears_the_bar():
    # All three layers at 1 — no layer has an "other layer >= 3" to
    # justify calling it a chosen gap rather than a startup with nothing
    # instrumented yet.
    report = triage("Feature", _layers(1, 1, 1), fw=FW)
    assert not any(v.verdict_id == "blind_spot" for v in report.verdicts)


# ── trust_failure_signal ────────────────────────────────────────────────


def test_trust_failure_signal_fires_on_high_performance_high_override():
    report = triage(
        "Feature",
        _layers(4, 2, 3, pb_indicators=[
            IndicatorEvidence(indicator_id="override_rate", tracked=True, value=46.0)
        ]),
        fw=FW,
    )
    assert "trust_failure_signal" in _verdict_ids(report)
    # and the risk_threshold_exceeded flag should have been computed
    # deterministically, not left as whatever the caller passed (nothing, here)
    pb_layer = next(l for l in report.layers if l.layer_id == "product_behaviour")
    override_evidence = next(i for i in pb_layer.indicators if i.indicator_id == "override_rate")
    assert override_evidence.risk_threshold_exceeded is True


def test_trust_failure_signal_does_not_fire_below_risk_threshold():
    report = triage(
        "Feature",
        _layers(4, 2, 3, pb_indicators=[
            IndicatorEvidence(indicator_id="override_rate", tracked=True, value=25.0)
        ]),
        fw=FW,
    )
    assert "trust_failure_signal" not in _verdict_ids(report)


def test_trust_failure_signal_does_not_fire_without_evidence():
    # model_performance is high, but no override_rate evidence was given at all.
    report = triage("Feature", _layers(4, 3, 3), fw=FW)
    assert "trust_failure_signal" not in _verdict_ids(report)


# ── vanity_metric_risk ──────────────────────────────────────────────────


def test_vanity_metric_risk_fires_on_shallow_outcome_next_to_strong_layer():
    report = triage("Feature", _layers(5, 2, 2), fw=FW)
    assert "vanity_metric_risk" in _verdict_ids(report)


def test_vanity_metric_risk_does_not_fire_without_a_strong_neighboring_layer():
    report = triage("Feature", _layers(3, 3, 2), fw=FW)
    assert "vanity_metric_risk" not in _verdict_ids(report)


def test_vanity_metric_risk_is_distinct_from_orphaned():
    # bo=1 -> orphaned, never vanity_metric_risk (which requires bo==2 exactly)
    report = triage("Feature", _layers(5, 5, 1), fw=FW)
    ids = _verdict_ids(report)
    assert "business_outcome_orphaned" in ids
    assert "vanity_metric_risk" not in ids


# ── validation ───────────────────────────────────────────────────────────


def test_missing_layer_is_rejected():
    with pytest.raises(ValueError, match="requires exactly the three"):
        triage(
            "Feature",
            [
                LayerInput(layer_id="model_performance", score=3, evidence_summary="x"),
                LayerInput(layer_id="product_behaviour", score=3, evidence_summary="x"),
            ],
            fw=FW,
        )


def test_duplicate_layer_is_rejected():
    with pytest.raises(ValueError, match="duplicate layer_id"):
        triage(
            "Feature",
            _layers(3, 3, 3) + [LayerInput(layer_id="model_performance", score=4, evidence_summary="x")],
            fw=FW,
        )


def test_unknown_indicator_id_is_rejected():
    with pytest.raises(ValueError, match="not defined on layer"):
        triage(
            "Feature",
            _layers(3, 3, 3, pb_indicators=[
                IndicatorEvidence(indicator_id="totally_made_up_indicator", tracked=True)
            ]),
            fw=FW,
        )


def test_unknown_vanity_metric_probe_id_is_rejected():
    with pytest.raises(ValueError, match="Unknown vanity_metric_probe"):
        triage("Feature", _layers(3, 3, 3), vanity_metric_flags=["not_a_real_probe"], fw=FW)


def test_valid_vanity_metric_flag_passes_through():
    report = triage(
        "Feature", _layers(3, 3, 3),
        vanity_metric_flags=["internal_eval_as_business_outcome"], fw=FW,
    )
    assert report.vanity_metric_flags == ["internal_eval_as_business_outcome"]


def test_out_of_range_layer_score_rejected_by_pydantic():
    with pytest.raises(ValidationError):
        LayerInput(layer_id="model_performance", score=7, evidence_summary="x")


# ── overall_score / maturity_level arithmetic ───────────────────────────


def test_overall_score_is_weighted_mean_with_equal_weights():
    # equal weights (0.334/0.333/0.333) on scores 4,2,1 -> ~2.335, rounds to 2.33 or 2.34
    report = triage("Feature", _layers(4, 2, 1), fw=FW)
    assert 2.33 <= report.overall_score <= 2.34


def test_maturity_level_is_the_minimum_not_the_average():
    report = triage("Feature", _layers(5, 5, 1), fw=FW)
    assert report.maturity_level == 1  # not ~3.7 or any average
