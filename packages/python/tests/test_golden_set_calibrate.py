from __future__ import annotations

from pathlib import Path

import pytest

from ai_product_pulse.domain.loader import load_framework
from ai_product_pulse.usecases.golden_set_calibrate import (
    GoldenSetCase,
    golden_set_calibrate,
    load_golden_set_cases,
)
from ai_product_pulse.usecases.triage import LayerInput

FW = load_framework()
REPO_ROOT = Path(__file__).resolve().parents[3]
EXAMPLE_GOLDEN_SET = REPO_ROOT / "shared" / "golden-set" / "example-cases.json"


def test_loads_the_real_shipped_illustrative_file():
    assert EXAMPLE_GOLDEN_SET.exists(), "shared/golden-set/example-cases.json is missing"
    cases = load_golden_set_cases(EXAMPLE_GOLDEN_SET)
    assert len(cases) == 4
    assert all(c.case_id.startswith("illustrative-") for c in cases)


def test_the_shipped_illustrative_cases_all_pass_against_the_current_framework():
    """This is the real point of shipping example-cases.json: it has to
    stay in sync with framework.json's actual verdict logic, or the one
    piece of proof that the harness works stops proving anything. If
    this test fails after a framework.json change, the fix is to update
    the illustrative file's expectations, not to weaken this test."""
    cases = load_golden_set_cases(EXAMPLE_GOLDEN_SET)
    result = golden_set_calibrate(cases, fw=FW)
    failures = [r for r in result.case_results if not r.passed]
    assert not failures, f"illustrative cases out of sync with framework.json: {failures}"
    assert result.pass_rate == 1.0


def _case(case_id: str, mp: int, pb: int, bo: int, expected_verdicts: list[str], expected_maturity: int | None = None) -> GoldenSetCase:
    return GoldenSetCase(
        case_id=case_id,
        description="test case",
        layers=[
            LayerInput(layer_id="model_performance", score=mp, evidence_summary="x"),
            LayerInput(layer_id="product_behaviour", score=pb, evidence_summary="x"),
            LayerInput(layer_id="business_outcome", score=bo, evidence_summary="x"),
        ],
        expected_verdict_ids=expected_verdicts,
        expected_maturity_level=expected_maturity,
    )


def test_a_case_with_correct_expectations_passes():
    case = _case("c1", 3, 3, 3, ["balanced"], 3)
    result = golden_set_calibrate([case], fw=FW)
    assert result.pass_rate == 1.0
    assert result.case_results[0].passed is True


def test_a_case_with_wrong_expected_verdicts_fails_with_diagnostic_detail():
    # actually fires business_outcome_orphaned, but we assert "balanced"
    case = _case("c2", 4, 4, 1, ["balanced"])
    result = golden_set_calibrate([case], fw=FW)
    assert result.pass_rate == 0.0
    failing = result.case_results[0]
    assert failing.passed is False
    # "balanced" was expected but didn't fire — missing.
    assert "balanced" in failing.missing_verdicts
    # "business_outcome_orphaned" fired but wasn't expected — unexpected.
    assert "business_outcome_orphaned" in failing.unexpected_verdicts


def test_a_case_with_wrong_expected_maturity_level_fails():
    case = _case("c3", 4, 4, 1, ["business_outcome_orphaned"], expected_maturity=3)
    result = golden_set_calibrate([case], fw=FW)
    failing = result.case_results[0]
    assert failing.passed is False
    assert failing.maturity_level_matches is False
    assert failing.actual_maturity_level == 1


def test_missing_expected_maturity_level_is_not_checked():
    # actual maturity_level is 1, but no expectation was given — this
    # must not count against the case.
    case = _case("c4", 4, 4, 1, ["business_outcome_orphaned"])  # no expected_maturity_level
    result = golden_set_calibrate([case], fw=FW)
    passing = result.case_results[0]
    assert passing.maturity_level_matches is None
    assert passing.passed is True


def test_pass_rate_reflects_mixed_results():
    cases = [
        _case("pass1", 3, 3, 3, ["balanced"]),
        _case("pass2", 3, 3, 3, ["balanced"]),
        _case("fail1", 3, 3, 3, ["business_outcome_orphaned"]),  # wrong
    ]
    result = golden_set_calibrate(cases, fw=FW)
    assert result.total_cases == 3
    assert result.passed_cases == 2
    assert result.pass_rate == pytest.approx(0.667, abs=0.001)


def test_rejects_empty_case_list():
    with pytest.raises(ValueError, match="at least one case"):
        golden_set_calibrate([], fw=FW)
