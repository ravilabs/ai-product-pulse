"""
Tests for the domain layer: does framework.json actually load into valid
typed objects, do the safety validators actually fire when they should,
and does the generated report.schema.json actually accept good reports
and reject bad ones.

This is deliberately not just a "does it import" smoke test — every test
here either asserts something succeeds that must succeed, or asserts
something fails that must fail. A validator nobody has proven capable of
failing isn't proven to be checking anything.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from ai_product_pulse.domain.entities import (
    FeatureReport,
    IndicatorEvidence,
    LayerResult,
    ProductReport,
    VerdictResult,
)
from ai_product_pulse.domain.loader import load_framework

REPO_ROOT = Path(__file__).resolve().parents[3]
REPORT_SCHEMA_PATH = REPO_ROOT / "report.schema.json"
PACKAGED_FRAMEWORK_JSON = REPO_ROOT / "packages" / "python" / "src" / "ai_product_pulse" / "framework.json"


# ── framework.json loading ──────────────────────────────────────────────


def test_packaged_framework_json_matches_repo_root_source():
    """This is the drift guard for scripts/sync_package_data.py — if
    someone edits the repo-root framework.json and forgets to rerun the
    sync script, this fails instead of the packaged copy silently going
    stale. Real install correctness depends on these two ever staying
    byte-identical."""
    repo_root_source = (REPO_ROOT / "framework.json").read_bytes()
    packaged_copy = PACKAGED_FRAMEWORK_JSON.read_bytes()
    assert repo_root_source == packaged_copy, (
        "packages/python/src/ai_product_pulse/framework.json is out of sync "
        "with the repo-root framework.json — run scripts/sync_package_data.py"
    )


def test_load_framework_with_no_args_reads_the_packaged_copy():
    """The no-arg default must resolve via importlib.resources to
    whatever's actually packaged/installed — not a filesystem path
    computed by counting parent directories, which breaks under a real
    (non-editable) install. See loader.py's docstring for why."""
    fw = load_framework()  # no path -> importlib.resources
    assert fw.framework_id == "ai-product-pulse"


def test_real_framework_json_loads_and_validates():
    fw = load_framework()
    assert fw.framework_id == "ai-product-pulse"
    assert {l.id for l in fw.layers} == {
        "model_performance",
        "product_behaviour",
        "business_outcome",
    }
    assert len(fw.verdicts) == 5
    assert len(fw.maturity_ladder) == 5


def test_maturity_label_lookup():
    fw = load_framework()
    assert fw.maturity_label(1) == "No Tracking"
    assert fw.maturity_label(5) == "Closed-Loop"
    with pytest.raises(KeyError):
        fw.maturity_label(6)


def test_indicator_risk_threshold_present_on_override_rate():
    fw = load_framework()
    override_rate = fw.layer("product_behaviour").indicator("override_rate")
    assert override_rate.risk_threshold is not None
    assert override_rate.risk_threshold.value == 40


# ── negative cases: validators must actually be able to fail ───────────


def _load_raw_framework() -> dict:
    return json.loads((REPO_ROOT / "framework.json").read_text(encoding="utf-8"))


def test_weights_not_summing_to_one_is_rejected():
    from ai_product_pulse.domain.entities import Framework

    raw = copy.deepcopy(_load_raw_framework())
    raw["scoring"]["overall_score"]["weights"]["business_outcome"] = 0.9  # now sums to ~1.57
    with pytest.raises(ValidationError, match="must sum to 1.0"):
        Framework.model_validate(raw)


def test_layer_weight_key_mismatch_is_rejected():
    from ai_product_pulse.domain.entities import Framework

    raw = copy.deepcopy(_load_raw_framework())
    weights = raw["scoring"]["overall_score"]["weights"]
    weights["a_typo_layer_name"] = weights.pop("business_outcome")
    with pytest.raises(ValidationError, match="don't match layer ids"):
        Framework.model_validate(raw)


# ── report shapes + generated schema ────────────────────────────────────


@pytest.fixture
def sample_feature_report() -> FeatureReport:
    return FeatureReport(
        framework_version="0.1.0",
        subject_name="AI Search Assistant",
        generated_by_harness="claude-code",
        layers=[
            LayerResult(
                layer_id="model_performance",
                score=4,
                maturity_label="Operationalized",
                indicators=[
                    IndicatorEvidence(
                        indicator_id="task_success_rate", tracked=True, value=91.2, unit="percentage"
                    )
                ],
                evidence_summary="Tracked weekly, reviewed in sprint retro.",
            ),
            LayerResult(
                layer_id="product_behaviour",
                score=2,
                maturity_label="Ad Hoc",
                indicators=[
                    IndicatorEvidence(
                        indicator_id="override_rate", tracked=True, value=46.0, risk_threshold_exceeded=True
                    )
                ],
                evidence_summary="Observed once in a support ticket review, not logged systematically.",
            ),
            LayerResult(
                layer_id="business_outcome",
                score=1,
                maturity_label="No Tracking",
                indicators=[IndicatorEvidence(indicator_id="attributed_business_impact", tracked=False)],
                evidence_summary="No defined business metric for this feature.",
            ),
        ],
        overall_score=2.33,
        maturity_level=1,
        verdicts=[
            VerdictResult(
                verdict_id="business_outcome_orphaned",
                name="Business-Outcome Orphaned",
                severity="critical",
                layer_id="business_outcome",
                message="No business metric defined for this feature.",
            ),
            VerdictResult(
                verdict_id="trust_failure_signal",
                name="Trust Failure Signal",
                severity="high",
                message="Model Performance scores 4 while override_rate (46%) exceeds the 40% risk threshold.",
            ),
        ],
    )


@pytest.fixture
def report_schema() -> dict:
    assert REPORT_SCHEMA_PATH.exists(), "run scripts/sync_report_schema.py first"
    return json.loads(REPORT_SCHEMA_PATH.read_text(encoding="utf-8"))


def test_sample_feature_report_validates_against_generated_schema(sample_feature_report, report_schema):
    report_dict = json.loads(sample_feature_report.model_dump_json())
    jsonschema.validate(report_dict, report_schema)  # raises on failure


def test_product_report_validates_against_same_schema(sample_feature_report, report_schema):
    product = ProductReport(
        framework_version="0.1.0",
        subject_name="Core AI Suite",
        features=[sample_feature_report],
        product_overall_score=2.33,
        product_maturity_level=1,
        verdict_rollup=[
            VerdictResult(
                verdict_id="business_outcome_orphaned",
                name="Business-Outcome Orphaned",
                severity="critical",
                feature_name="AI Search Assistant",
                message="No business metric defined for this feature.",
            )
        ],
    )
    jsonschema.validate(json.loads(product.model_dump_json()), report_schema)


def test_out_of_range_score_is_rejected_by_schema(sample_feature_report, report_schema):
    broken = json.loads(sample_feature_report.model_dump_json())
    broken["layers"][0]["score"] = 9  # max is 5
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, report_schema)


def test_missing_required_field_is_rejected_by_schema(sample_feature_report, report_schema):
    broken = json.loads(sample_feature_report.model_dump_json())
    del broken["overall_score"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(broken, report_schema)


def test_out_of_range_score_is_rejected_by_pydantic_directly():
    """Belt and suspenders: Pydantic should catch this before a report
    ever reaches the schema check, since the schema check is really for
    external/TS consumers, not for the Python package's own code path."""
    with pytest.raises(ValidationError):
        LayerResult(
            layer_id="model_performance",
            score=9,
            maturity_label="Operationalized",
            indicators=[],
            evidence_summary="x",
        )
