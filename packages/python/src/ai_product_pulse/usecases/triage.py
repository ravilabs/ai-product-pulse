"""
triage — the primary use case. Takes what the calling agent already
assessed (a 1-5 score per layer, judged against the maturity_ladder, plus
whatever indicator evidence it found) and returns a validated FeatureReport.

Everything in this file is orchestration and validation. The actual
scoring math and verdict matching live in domain/scoring_engine.py, kept
separate on purpose — this file is the seam a future MCP tool or CLI
command binds to (an "adapter" in the ports/adapters sense), while
scoring_engine.py stays independent of how it's called.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from ..domain.entities import (
    FeatureReport,
    Framework,
    IndicatorEvidence,
    LayerId,
    LayerResult,
)
from ..domain.loader import framework as default_framework
from ..domain.scoring_engine import (
    apply_risk_thresholds,
    compute_maturity_level,
    compute_overall_score,
    evaluate_verdicts,
)


class LayerInput(BaseModel):
    """What the calling agent provides for one layer, after reviewing
    whatever evidence the user gave it. score is the agent's judgment
    against framework.json's maturity_ladder — this is the one place in
    the whole pipeline that isn't deterministic, by design."""

    layer_id: LayerId
    score: int = Field(ge=1, le=5)
    evidence_summary: str
    indicators: list[IndicatorEvidence] = Field(default_factory=list)


def _reject_wrong_layer_set(fw: Framework, layers: list[LayerInput]) -> None:
    expected = {layer.id for layer in fw.layers}
    provided = [li.layer_id for li in layers]

    if len(provided) != len(set(provided)):
        raise ValueError(f"triage() received a duplicate layer_id: {provided}")

    if set(provided) != expected:
        missing = expected - set(provided)
        unexpected = set(provided) - expected
        raise ValueError(
            "triage() requires exactly the three Triangle layers "
            f"{sorted(expected)}. Missing: {sorted(missing) or 'none'}. "
            f"Unexpected: {sorted(unexpected) or 'none'}."
        )


def _reject_unknown_indicator_ids(fw: Framework, layers: list[LayerInput]) -> None:
    for li in layers:
        valid_indicator_ids = {ind.id for ind in fw.layer(li.layer_id).indicators}
        for evidence in li.indicators:
            if evidence.indicator_id not in valid_indicator_ids:
                raise ValueError(
                    f"Indicator '{evidence.indicator_id}' is not defined on layer "
                    f"'{li.layer_id}'. Valid indicators there: {sorted(valid_indicator_ids)}"
                )


def _validate_layers(fw: Framework, layers: list[LayerInput]) -> None:
    _reject_wrong_layer_set(fw, layers)
    _reject_unknown_indicator_ids(fw, layers)


def _validate_vanity_flags(fw: Framework, flags: list[str]) -> None:
    valid_ids = {probe.id for probe in fw.vanity_metric_probes}
    unknown = [f for f in flags if f not in valid_ids]
    if unknown:
        raise ValueError(
            f"Unknown vanity_metric_probe id(s): {unknown}. Valid probes: {sorted(valid_ids)}"
        )


def triage(
    subject_name: str,
    layers: list[LayerInput],
    subject_description: str | None = None,
    generated_by_harness: str | None = None,
    vanity_metric_flags: list[str] | None = None,
    recommendations: str | None = None,
    fw: Framework | None = None,
) -> FeatureReport:
    """Assembles one feature-level AI Product Pulse report.

    The caller (an MCP tool, a CLI command, a test) is responsible for
    everything upstream of this function — reading the user's evidence
    and turning it into LayerInput objects. That's the agent-judgment
    half of the pipeline. Everything from here down is deterministic.
    """
    fw = fw or default_framework()
    vanity_metric_flags = vanity_metric_flags or []

    _validate_layers(fw, layers)
    _validate_vanity_flags(fw, vanity_metric_flags)

    layer_scores: dict[str, int] = {li.layer_id: li.score for li in layers}
    indicator_evidence: dict[str, IndicatorEvidence] = {
        evidence.indicator_id: evidence for li in layers for evidence in li.indicators
    }

    apply_risk_thresholds(fw, indicator_evidence)

    layer_results = [
        LayerResult(
            layer_id=li.layer_id,
            score=li.score,
            maturity_label=fw.maturity_label(li.score),
            indicators=li.indicators,
            evidence_summary=li.evidence_summary,
        )
        for li in layers
    ]

    return FeatureReport(
        framework_version=fw.version,
        subject_name=subject_name,
        subject_description=subject_description,
        generated_by_harness=generated_by_harness,
        layers=layer_results,
        overall_score=compute_overall_score(fw, layer_scores),
        maturity_level=compute_maturity_level(layer_scores),
        verdicts=evaluate_verdicts(fw, layer_scores, indicator_evidence),
        vanity_metric_flags=vanity_metric_flags,
        recommendations=recommendations,
    )
