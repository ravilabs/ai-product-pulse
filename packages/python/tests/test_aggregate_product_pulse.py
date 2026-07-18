from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ai_product_pulse.domain.loader import load_framework
from ai_product_pulse.usecases.aggregate_product_pulse import aggregate_product_pulse
from ai_product_pulse.usecases.triage import LayerInput, triage

FW = load_framework()


def _feature(name: str, mp: int, pb: int, bo: int):
    layers = [
        LayerInput(layer_id="model_performance", score=mp, evidence_summary="x"),
        LayerInput(layer_id="product_behaviour", score=pb, evidence_summary="x"),
        LayerInput(layer_id="business_outcome", score=bo, evidence_summary="x"),
    ]
    return triage(name, layers, fw=FW)


def test_product_maturity_level_is_minimum_across_features_not_average():
    # One strong feature (min layer score 4), one weak feature (min layer score 1).
    # A mean would land around 2.5-3; the weakest-link rule must give 1.
    strong = _feature("Search", 5, 4, 4)
    weak = _feature("Tagging", 1, 3, 3)
    product = aggregate_product_pulse("Core AI Suite", [strong, weak], fw=FW)
    assert product.product_maturity_level == 1


def test_product_overall_score_is_flat_mean_across_features():
    a = _feature("A", 5, 5, 5)  # overall_score = 5.0
    b = _feature("B", 1, 1, 1)  # overall_score = 1.0
    product = aggregate_product_pulse("Suite", [a, b], fw=FW)
    assert product.product_overall_score == pytest.approx(3.0, abs=0.01)


def test_verdict_rollup_preserves_every_verdict_attributed_to_its_feature():
    orphaned_feature = _feature("Orphaned Feature", 4, 4, 1)  # -> business_outcome_orphaned
    balanced_feature = _feature("Balanced Feature", 3, 3, 3)  # -> balanced
    product = aggregate_product_pulse("Suite", [orphaned_feature, balanced_feature], fw=FW)

    expected_total = len(orphaned_feature.verdicts) + len(balanced_feature.verdicts)
    assert len(product.verdict_rollup) == expected_total

    orphaned_entries = [v for v in product.verdict_rollup if v.verdict_id == "business_outcome_orphaned"]
    assert len(orphaned_entries) == 1
    assert orphaned_entries[0].feature_name == "Orphaned Feature"

    balanced_entries = [v for v in product.verdict_rollup if v.verdict_id == "balanced"]
    assert len(balanced_entries) == 1
    assert balanced_entries[0].feature_name == "Balanced Feature"


def test_verdict_rollup_does_not_hide_one_bad_feature_behind_good_ones():
    # Three balanced features, one orphaned. A blended/averaged verdict
    # summary could plausibly call this product "mostly fine" — the
    # rollup must not let that happen; the orphaned flag has to survive.
    good = [_feature(f"Good {i}", 4, 4, 4) for i in range(3)]
    bad = _feature("Bad", 4, 4, 1)
    product = aggregate_product_pulse("Suite", good + [bad], fw=FW)
    assert any(
        v.verdict_id == "business_outcome_orphaned" and v.feature_name == "Bad"
        for v in product.verdict_rollup
    )


def test_requires_at_least_two_features():
    single = _feature("Only Feature", 3, 3, 3)
    with pytest.raises(ValueError, match="at least two"):
        aggregate_product_pulse("Suite", [single], fw=FW)


def test_rejects_mismatched_framework_versions():
    a = _feature("A", 3, 3, 3)
    b = _feature("B", 3, 3, 3).model_copy(update={"framework_version": "0.0.9-fake"})
    with pytest.raises(ValueError, match="same framework_version"):
        aggregate_product_pulse("Suite", [a, b], fw=FW)


def test_rejects_duplicate_feature_names():
    a = _feature("Same Name", 3, 3, 3)
    b = _feature("Same Name", 4, 4, 4)
    with pytest.raises(ValueError, match="unique"):
        aggregate_product_pulse("Suite", [a, b], fw=FW)


def test_product_report_validates_against_generated_schema():
    a = _feature("A", 4, 4, 1)
    b = _feature("B", 3, 3, 3)
    product = aggregate_product_pulse("Suite", [a, b], fw=FW)

    schema = json.loads(Path("report.schema.json").read_text())
    jsonschema.validate(json.loads(product.model_dump_json()), schema)
