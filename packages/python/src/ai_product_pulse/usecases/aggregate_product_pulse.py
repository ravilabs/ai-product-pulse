"""
aggregate_product_pulse — rolls up two or more feature-level FeatureReports
into one ProductReport. This is the "product" half of unit_of_assessment
in framework.json: same layers, same indicators, same verdicts as a single
feature, just combined per the rules in framework.json's aggregation
section.

Like triage.py, this file is orchestration only. There's no separate
"scoring_engine" logic needed here beyond min() and mean() — simple
enough to stay inline rather than invent an abstraction for two one-line
formulas.
"""
from __future__ import annotations

from ..domain.entities import FeatureReport, Framework, ProductReport, VerdictResult
from ..domain.loader import framework as default_framework


def _reject_fewer_than_two_features(features: list[FeatureReport]) -> None:
    if len(features) < 2:
        raise ValueError(
            "aggregate_product_pulse() requires at least two FeatureReports "
            f"(got {len(features)}). A single feature doesn't need product-level "
            "rollup — use its FeatureReport directly. See framework.json's "
            "aggregation.applies_when."
        )


def _reject_mismatched_framework_versions(features: list[FeatureReport]) -> None:
    versions = {f.framework_version for f in features}
    if len(versions) > 1:
        raise ValueError(
            f"All features must share the same framework_version to aggregate; got {sorted(versions)}. "
            "Re-run triage() for the outdated features against the current framework.json first."
        )


def _reject_duplicate_subject_names(features: list[FeatureReport]) -> None:
    names = [f.subject_name for f in features]
    if len(names) != len(set(names)):
        duplicates = sorted({n for n in names if names.count(n) > 1})
        raise ValueError(
            f"Feature subject_name values must be unique within a product rollup — "
            f"duplicated: {duplicates}. Verdict attribution in the rollup depends on the name being unambiguous."
        )


def aggregate_product_pulse(
    subject_name: str,
    features: list[FeatureReport],
    subject_description: str | None = None,
    generated_by_harness: str | None = None,
    fw: Framework | None = None,
) -> ProductReport:
    """Assembles one product-level AI Product Pulse report from two or
    more feature-level reports the caller already produced via triage().

    Deliberately takes already-built FeatureReport objects rather than
    re-running triage() itself — this function does no scoring of its own,
    only combination. Keeps the MCP/CLI adapters stateless: the calling
    agent holds the individual feature reports and passes all of them in
    at once, so the server never needs to remember anything between calls.
    """
    fw = fw or default_framework()

    _reject_fewer_than_two_features(features)
    _reject_mismatched_framework_versions(features)
    _reject_duplicate_subject_names(features)

    # product_maturity_level: min(feature_maturity_levels) — same weakest-
    # link principle as layer-level maturity_level. See framework.json's
    # aggregation.product_maturity_level.rationale.
    product_maturity_level = min(f.maturity_level for f in features)

    # product_overall_score: mean(feature_overall_scores), flat and equal —
    # confirmed decision, see aggregation.product_overall_score in framework.json.
    product_overall_score = round(sum(f.overall_score for f in features) / len(features), 2)

    # verdict_rollup: every verdict from every feature, attributed, never
    # blended away. See aggregation.verdict_rollup.rule.
    verdict_rollup: list[VerdictResult] = [
        verdict.model_copy(update={"feature_name": feature.subject_name})
        for feature in features
        for verdict in feature.verdicts
    ]

    return ProductReport(
        framework_version=fw.version,
        subject_name=subject_name,
        subject_description=subject_description,
        generated_by_harness=generated_by_harness,
        features=features,
        product_overall_score=product_overall_score,
        product_maturity_level=product_maturity_level,
        verdict_rollup=verdict_rollup,
    )
