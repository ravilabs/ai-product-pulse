from __future__ import annotations

from ai_product_pulse.domain.loader import load_framework
from ai_product_pulse.usecases.explain import explain
from ai_product_pulse.usecases.triage import LayerInput, triage

FW = load_framework()


def _feature(mp: int, pb: int, bo: int, pb_indicators=None):
    layers = [
        LayerInput(layer_id="model_performance", score=mp, evidence_summary="x"),
        LayerInput(layer_id="product_behaviour", score=pb, evidence_summary="x", indicators=pb_indicators or []),
        LayerInput(layer_id="business_outcome", score=bo, evidence_summary="x"),
    ]
    return triage("Feature", layers, fw=FW)


def test_narrative_mentions_overall_score_and_maturity_level():
    report = _feature(3, 3, 3)
    result = explain(report, fw=FW)
    assert str(report.overall_score) in result.narrative
    assert str(report.maturity_level) in result.narrative


def test_narrative_reports_balanced_case_cleanly():
    report = _feature(3, 3, 3)
    result = explain(report, fw=FW)
    assert "no flagged gaps" in result.narrative.lower()


def test_narrative_counts_critical_verdicts_separately():
    report = _feature(4, 4, 1)  # business_outcome_orphaned, critical
    result = explain(report, fw=FW)
    assert "critical severity" in result.narrative


def test_score_breakdown_arithmetic_is_correct():
    report = _feature(4, 2, 1)
    result = explain(report, fw=FW)
    weights = {b.layer_id: b.weight for b in result.overall_score_breakdown}
    for b in result.overall_score_breakdown:
        assert abs(b.weighted_contribution - round(b.score * weights[b.layer_id], 3)) < 1e-9
    assert str(report.overall_score) in result.overall_score_formula


def test_maturity_explanation_names_the_capping_layer():
    report = _feature(5, 5, 1)  # business_outcome caps maturity_level at 1
    result = explain(report, fw=FW)
    assert "Business Outcome" in result.maturity_level_explanation
    assert "minimum" in result.maturity_level_explanation.lower()


def test_maturity_explanation_handles_all_layers_equal():
    report = _feature(3, 3, 3)
    result = explain(report, fw=FW)
    assert "genuinely even" in result.maturity_level_explanation


def test_verdict_guidance_includes_investigative_questions():
    report = _feature(4, 4, 1)  # business_outcome_orphaned
    result = explain(report, fw=FW)
    orphaned_guidance = next(g for g in result.verdict_guidance if g.verdict_id == "business_outcome_orphaned")
    assert len(orphaned_guidance.investigative_questions) > 0
    assert all("{layer_name}" not in q for q in orphaned_guidance.investigative_questions)


def test_verdict_guidance_renders_layer_name_template_for_blind_spot():
    report = _feature(1, 4, 4)  # blind_spot: model_performance
    result = explain(report, fw=FW)
    blind_spot_guidance = next(g for g in result.verdict_guidance if g.verdict_id == "blind_spot")
    assert blind_spot_guidance.layer_id == "model_performance"
    # the {layer_name} placeholder must be rendered, not left literal
    assert all("{layer_name}" not in q for q in blind_spot_guidance.investigative_questions)
    assert any("Model Performance" in q for q in blind_spot_guidance.investigative_questions)


def test_explain_is_deterministic():
    report = _feature(4, 2, 1, pb_indicators=[
        {"indicator_id": "override_rate", "tracked": True, "value": 46.0}
    ])
    result_a = explain(report, fw=FW)
    result_b = explain(report, fw=FW)
    assert result_a.narrative == result_b.narrative
    assert result_a.overall_score_formula == result_b.overall_score_formula
