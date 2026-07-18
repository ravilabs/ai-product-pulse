"""
Domain entities for AI Product Pulse.

Two families of model live here, deliberately kept in one file because
they're two views of the same rubric:

  1. Static framework concepts (Indicator, Layer, VerdictRule, Framework, ...)
     — the typed runtime form of framework.json. Nothing in usecases/ should
     ever re-read framework.json directly; everything goes through Framework.

  2. Runtime report concepts (IndicatorEvidence, LayerResult, FeatureReport,
     ProductReport, ...) — what a triage run actually produces.

report.schema.json is generated FROM FeatureReport / ProductReport below
(see scripts/sync_report_schema.py). Do not hand-author report.schema.json —
same discipline as framework.yaml being generated from framework.json.

This file has no file I/O. Loading framework.json into a Framework object
is loader.py's job, kept separate on purpose — domain stays a pure,
dependency-free layer per the hexagonal architecture split (domain / ports
/ adapters) agreed for this repo.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field, model_validator

Severity = Literal["none", "low", "medium", "high", "critical"]
LayerId = Literal["model_performance", "product_behaviour", "business_outcome"]
Direction = Literal["higher_is_better", "lower_is_better", "context_dependent"]


# ─────────────────────────────────────────────────────────────────────────
# Static framework concepts — the typed form of framework.json
# ─────────────────────────────────────────────────────────────────────────


class RiskThreshold(BaseModel):
    operator: Literal["gte", "lte", "gt", "lt", "eq"]
    value: float
    signal: str
    note: str | None = None


class Indicator(BaseModel):
    id: str
    name: str
    description: str
    unit: str
    direction: Direction
    applicable_if: str | None = None
    risk_threshold: RiskThreshold | None = None


class Layer(BaseModel):
    id: LayerId
    name: str
    order: int
    question: str
    indicators: list[Indicator]

    def indicator(self, indicator_id: str) -> Indicator:
        for i in self.indicators:
            if i.id == indicator_id:
                return i
        raise KeyError(f"No indicator '{indicator_id}' on layer '{self.id}'")


class MaturityRung(BaseModel):
    level: int = Field(ge=1, le=5)
    label: str
    description: str


class VerdictTrigger(BaseModel):
    """Trigger shape varies by trigger_type (per_layer vs. global vs.
    indicator-aware). Deliberately permissive here — interpreting the
    trigger is the rule evaluator's job (usecases/triage.py), not the
    domain model's. This model just guarantees it round-trips as data."""

    model_config = {"extra": "allow"}


class CrossReference(BaseModel):
    framework: str
    author: str
    node_referenced: str
    relationship: str


class VerdictRule(BaseModel):
    id: str
    name: str
    priority: int
    severity: Severity
    trigger_type: str
    trigger: VerdictTrigger
    trigger_description: str
    description: str
    label_template: str | None = None
    cross_reference: CrossReference | None = None
    investigative_questions: list[str] = Field(default_factory=list)


class VanityMetricProbe(BaseModel):
    id: str
    pattern: str
    why_it_fails: str
    redirect_to: list[str]


class OverallScoreConfig(BaseModel):
    formula: str
    weights: dict[str, float]
    weights_extensibility: str
    range: tuple[int, int]
    purpose: str

    @model_validator(mode="after")
    def weights_sum_to_one(self) -> "OverallScoreConfig":
        total = sum(self.weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"overall_score.weights must sum to 1.0, got {total}")
        return self


class MaturityLevelConfig(BaseModel):
    formula: str
    range: tuple[int, int]
    purpose: str


class ScoringConfig(BaseModel):
    layer_score_scale: str
    layer_score_method: str
    layer_score_note: str
    overall_score: OverallScoreConfig
    maturity_level: MaturityLevelConfig


class AggregationConfig(BaseModel):
    applies_when: str
    product_maturity_level: dict[str, str]
    product_overall_score: dict[str, str]
    verdict_rollup: dict[str, str]


class UnitOfAssessment(BaseModel):
    scopes: list[Literal["feature", "product"]]
    feature: str
    product: str
    industry_scope: str


class Framework(BaseModel):
    """The typed runtime form of framework.json."""

    framework_id: str
    framework_name: str
    based_on_framework: str
    version: str
    schema_version: str
    author: str
    org: str
    license: str
    description: str
    implementation_notes: str
    unit_of_assessment: UnitOfAssessment
    layers: list[Layer]
    maturity_ladder: list[MaturityRung]
    scoring: ScoringConfig
    aggregation: AggregationConfig
    verdicts: list[VerdictRule]
    vanity_metric_probes: list[VanityMetricProbe]
    cross_references: list[CrossReference]

    @model_validator(mode="after")
    def layer_ids_match_weight_keys(self) -> "Framework":
        layer_ids = {layer.id for layer in self.layers}
        weight_ids = set(self.scoring.overall_score.weights.keys())
        if layer_ids != weight_ids:
            raise ValueError(
                f"scoring.overall_score.weights keys {weight_ids} "
                f"don't match layer ids {layer_ids}"
            )
        return self

    def layer(self, layer_id: str) -> Layer:
        for layer in self.layers:
            if layer.id == layer_id:
                return layer
        raise KeyError(f"No layer '{layer_id}'")

    def maturity_label(self, level: int) -> str:
        for rung in self.maturity_ladder:
            if rung.level == level:
                return rung.label
        raise KeyError(f"No maturity level {level}")

    def verdict(self, verdict_id: str) -> VerdictRule:
        for v in self.verdicts:
            if v.id == verdict_id:
                return v
        raise KeyError(f"No verdict '{verdict_id}'")


# ─────────────────────────────────────────────────────────────────────────
# Runtime report concepts — what a triage run produces
# ─────────────────────────────────────────────────────────────────────────


def _new_report_id() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


class IndicatorEvidence(BaseModel):
    indicator_id: str
    tracked: bool
    value: float | None = None
    unit: str | None = None
    evidence_note: str | None = None
    risk_threshold_exceeded: bool | None = None


class LayerResult(BaseModel):
    layer_id: LayerId
    score: int = Field(ge=1, le=5)
    maturity_label: str
    indicators: list[IndicatorEvidence]
    evidence_summary: str


class VerdictResult(BaseModel):
    verdict_id: str
    name: str
    severity: Severity
    message: str
    layer_id: str | None = None
    """Deliberately str, not the narrower LayerId Literal used elsewhere.
    This is populated by scoring_engine.py's generic rule evaluator,
    which doesn't hardcode the specific 3 layer names — LayerInput and
    LayerResult are where the Literal narrowing does real work, at the
    actual input boundary."""
    feature_name: str | None = None
    """Set only when this VerdictResult appears inside a ProductReport's
    verdict_rollup — identifies which feature triggered it. None in a
    standalone FeatureReport, where the subject is already unambiguous."""


class FeatureReport(BaseModel):
    report_id: str = Field(default_factory=_new_report_id)
    framework_id: Literal["ai-product-pulse"] = "ai-product-pulse"
    framework_version: str
    unit_of_assessment: Literal["feature"] = "feature"
    subject_name: str
    subject_description: str | None = None
    generated_at: datetime = Field(default_factory=_now)
    generated_by_harness: str | None = None
    layers: list[LayerResult]
    overall_score: float = Field(ge=1, le=5)
    maturity_level: int = Field(ge=1, le=5)
    verdicts: list[VerdictResult]
    vanity_metric_flags: list[str] = Field(default_factory=list)
    recommendations: str | None = None


class ProductReport(BaseModel):
    report_id: str = Field(default_factory=_new_report_id)
    framework_id: Literal["ai-product-pulse"] = "ai-product-pulse"
    framework_version: str
    unit_of_assessment: Literal["product"] = "product"
    subject_name: str
    subject_description: str | None = None
    generated_at: datetime = Field(default_factory=_now)
    generated_by_harness: str | None = None
    features: list[FeatureReport]
    product_overall_score: float = Field(ge=1, le=5)
    product_maturity_level: int = Field(ge=1, le=5)
    verdict_rollup: list[VerdictResult]


class LayerChange(BaseModel):
    layer_id: LayerId
    previous_score: int = Field(ge=1, le=5)
    current_score: int = Field(ge=1, le=5)
    delta: int
    previous_maturity_label: str
    current_maturity_label: str


class VerdictChange(BaseModel):
    verdict_id: str
    name: str
    severity: Severity
    layer_id: str | None = None


RegressionSummary = Literal["improved", "regressed", "mixed", "unchanged"]


class RegressionDiffResult(BaseModel):
    subject_name: str
    framework_version: str
    previous_generated_at: datetime
    current_generated_at: datetime
    layer_changes: list[LayerChange]
    overall_score_delta: float
    maturity_level_delta: int
    verdicts_resolved: list[VerdictChange]
    """Fired in the previous report, gone in the current one — fixed."""
    verdicts_introduced: list[VerdictChange]
    """Fired in the current report, absent from the previous one — new."""
    verdicts_persisting: list[VerdictChange]
    """Fired in both — still open."""
    summary: RegressionSummary


class LayerScoreBreakdown(BaseModel):
    layer_id: LayerId
    layer_name: str
    score: int = Field(ge=1, le=5)
    weight: float
    weighted_contribution: float
    maturity_label: str


class VerdictGuidance(BaseModel):
    verdict_id: str
    name: str
    severity: Severity
    layer_id: str | None = None
    message: str
    investigative_questions: list[str]


class ExplanationResult(BaseModel):
    """Deterministic prose rendering of a FeatureReport — the arithmetic
    behind overall_score, why maturity_level is capped where it is, and
    per-verdict investigative questions pulled from framework.json. Not
    new judgment or new computation: everything here is already present
    in the report or in framework.json, rendered legibly for a human who
    wants prose instead of JSON."""

    subject_name: str
    narrative: str
    overall_score_breakdown: list[LayerScoreBreakdown]
    overall_score_formula: str
    maturity_level_explanation: str
    verdict_guidance: list[VerdictGuidance]


class GoldenSetCaseResult(BaseModel):
    case_id: str
    description: str
    passed: bool
    actual_verdict_ids: list[str]
    expected_verdict_ids: list[str]
    missing_verdicts: list[str]
    """Expected to fire, didn't."""
    unexpected_verdicts: list[str]
    """Fired, wasn't expected."""
    actual_maturity_level: int
    expected_maturity_level: int | None
    maturity_level_matches: bool | None


class GoldenSetCalibrationResult(BaseModel):
    total_cases: int
    passed_cases: int
    pass_rate: float
    case_results: list[GoldenSetCaseResult]


Report = Annotated[
    Union[FeatureReport, ProductReport],
    Field(discriminator="unit_of_assessment"),
]
