"""
explain — deterministic prose rendering of a FeatureReport: the
arithmetic behind overall_score, why maturity_level is capped where it
is, and per-verdict investigative questions pulled from framework.json.

This is not a new judgment call, and it doesn't attempt causal
diagnosis ("why is business_outcome untracked, specifically, for this
team") — that needs context only the evidence-gathering conversation
has, already captured in each layer's evidence_summary. What this does
is render data that already exists (the report, framework.json's
weights and investigative_questions) into something a human can read
without parsing JSON. Scope was deliberately narrowed to this from an
earlier "explain + diagnose_gap" idea for exactly that reason — seeing
this file is what makes narrowing it correctly checkable.
"""
from __future__ import annotations

from ..domain.entities import (
    ExplanationResult,
    FeatureReport,
    Framework,
    LayerScoreBreakdown,
    VerdictGuidance,
)
from ..domain.loader import framework as default_framework


def _build_narrative(report: FeatureReport, fw: Framework) -> str:
    parts = [
        f"{report.subject_name} scores {report.overall_score} overall, at maturity level "
        f"{report.maturity_level} ({fw.maturity_label(report.maturity_level)})."
    ]

    negative_verdicts = [v for v in report.verdicts if v.severity != "none"]
    positive_verdicts = [v for v in report.verdicts if v.severity == "none"]

    if negative_verdicts:
        names = ", ".join(v.name for v in negative_verdicts)
        plural = "s" if len(negative_verdicts) != 1 else ""
        parts.append(f"{len(negative_verdicts)} verdict{plural} flagged: {names}.")
        critical = [v for v in negative_verdicts if v.severity == "critical"]
        if critical:
            critical_plural = "s are" if len(critical) != 1 else " is"
            parts.append(
                f"{len(critical)} of those{critical_plural} at critical severity — "
                "worth addressing before anything else on this list."
            )
    elif positive_verdicts:
        parts.append("Every layer is at least Instrumented, with no flagged gaps.")
    else:
        parts.append(
            "No verdicts fired, but the layers aren't uniformly at Instrumented or "
            "higher either — this sits in a middle ground worth a second look."
        )

    return " ".join(parts)


def _build_score_breakdown(
    report: FeatureReport, fw: Framework
) -> tuple[list[LayerScoreBreakdown], str]:
    weights = fw.scoring.overall_score.weights
    breakdown = []
    formula_terms = []
    for layer_result in report.layers:
        weight = weights[layer_result.layer_id]
        layer_def = fw.layer(layer_result.layer_id)
        contribution = round(layer_result.score * weight, 3)
        breakdown.append(
            LayerScoreBreakdown(
                layer_id=layer_result.layer_id,
                layer_name=layer_def.name,
                score=layer_result.score,
                weight=weight,
                weighted_contribution=contribution,
                maturity_label=layer_result.maturity_label,
            )
        )
        formula_terms.append(f"({layer_result.score} \u00d7 {weight})")

    formula = " + ".join(formula_terms) + f" = {report.overall_score}"
    return breakdown, formula


def _build_maturity_explanation(report: FeatureReport, fw: Framework) -> str:
    capping_layers = [layer for layer in report.layers if layer.score == report.maturity_level]
    maturity_label = fw.maturity_label(report.maturity_level)

    if len(capping_layers) == len(report.layers):
        return (
            f"All three layers sit at {report.maturity_level} ({maturity_label}) — "
            "nothing is being averaged away here, they're genuinely even."
        )

    layer_names = ", ".join(fw.layer(layer.layer_id).name for layer in capping_layers)
    return (
        f"Capped at {report.maturity_level} ({maturity_label}) by {layer_names} — "
        "the Triangle takes the minimum across layers, not the average, so a "
        "strong score elsewhere doesn't offset this."
    )


def _build_verdict_guidance(report: FeatureReport, fw: Framework) -> list[VerdictGuidance]:
    guidance = []
    for verdict_result in report.verdicts:
        rule = fw.verdict(verdict_result.verdict_id)
        layer_name = fw.layer(verdict_result.layer_id).name if verdict_result.layer_id else None
        questions = [
            q.format(layer_name=layer_name) if layer_name and "{layer_name}" in q else q
            for q in rule.investigative_questions
        ]
        guidance.append(
            VerdictGuidance(
                verdict_id=verdict_result.verdict_id,
                name=verdict_result.name,
                severity=verdict_result.severity,
                layer_id=verdict_result.layer_id,
                message=verdict_result.message,
                investigative_questions=questions,
            )
        )
    return guidance


def explain(report: FeatureReport, fw: Framework | None = None) -> ExplanationResult:
    """Renders a FeatureReport as prose. Deterministic — same report in,
    same explanation out, every time."""
    fw = fw or default_framework()
    breakdown, formula = _build_score_breakdown(report, fw)

    return ExplanationResult(
        subject_name=report.subject_name,
        narrative=_build_narrative(report, fw),
        overall_score_breakdown=breakdown,
        overall_score_formula=formula,
        maturity_level_explanation=_build_maturity_explanation(report, fw),
        verdict_guidance=_build_verdict_guidance(report, fw),
    )
