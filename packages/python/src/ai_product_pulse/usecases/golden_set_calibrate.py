"""
golden_set_calibrate — runs a set of known cases through triage() and
compares actual verdicts/maturity_level against expected ones.

This is the mechanism, built now specifically so it's ready the moment
real (anonymized) cases exist — building it after the fact would just
delay having it. What ships in shared/golden-set/ alongside this file
is illustrative, synthetic data, clearly labeled as such everywhere it
appears (the file itself, its README, and every test that uses it).
It proves the harness works. It is not calibration evidence, and
nothing in this codebase should ever cite it as if it were — see
CONTRIBUTING.md's Golden-set section for the actual bar real cases
need to meet.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from ..domain.entities import Framework, GoldenSetCalibrationResult, GoldenSetCaseResult
from ..domain.loader import framework as default_framework
from .triage import LayerInput, triage


class GoldenSetCase(BaseModel):
    """A single known case: input evidence plus the verdicts/maturity
    level a correct triage() run should produce for it. Lives here, not
    in domain/entities.py, for the same reason LayerInput does — it's
    this use case's input contract, not a shape the domain itself
    defines."""

    case_id: str
    description: str
    layers: list[LayerInput]
    expected_verdict_ids: list[str] = Field(default_factory=list)
    expected_maturity_level: int | None = Field(default=None, ge=1, le=5)


def load_golden_set_cases(path: str | Path) -> list[GoldenSetCase]:
    """Loads a golden-set file: {"cases": [<GoldenSetCase>, ...]}."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [GoldenSetCase.model_validate(case) for case in raw["cases"]]


def _calibrate_one(case: GoldenSetCase, fw: Framework) -> GoldenSetCaseResult:
    report = triage(subject_name=case.case_id, layers=case.layers, fw=fw)

    actual_ids = {v.verdict_id for v in report.verdicts}
    expected_ids = set(case.expected_verdict_ids)
    missing = sorted(expected_ids - actual_ids)
    unexpected = sorted(actual_ids - expected_ids)

    maturity_matches = (
        report.maturity_level == case.expected_maturity_level
        if case.expected_maturity_level is not None
        else None
    )
    passed = not missing and not unexpected and maturity_matches is not False

    return GoldenSetCaseResult(
        case_id=case.case_id,
        description=case.description,
        passed=passed,
        actual_verdict_ids=sorted(actual_ids),
        expected_verdict_ids=sorted(expected_ids),
        missing_verdicts=missing,
        unexpected_verdicts=unexpected,
        actual_maturity_level=report.maturity_level,
        expected_maturity_level=case.expected_maturity_level,
        maturity_level_matches=maturity_matches,
    )


def golden_set_calibrate(
    cases: list[GoldenSetCase], fw: Framework | None = None
) -> GoldenSetCalibrationResult:
    """Runs every case through triage() and reports pass/fail per case
    plus an overall pass rate. A case passes if actual verdicts exactly
    match expected ones (no missing, none unexpected) and, if an
    expected_maturity_level was given, it matches too."""
    if not cases:
        raise ValueError("golden_set_calibrate() requires at least one case")

    fw = fw or default_framework()
    case_results = [_calibrate_one(case, fw) for case in cases]
    passed_count = sum(1 for r in case_results if r.passed)

    return GoldenSetCalibrationResult(
        total_cases=len(cases),
        passed_cases=passed_count,
        pass_rate=round(passed_count / len(cases), 3),
        case_results=case_results,
    )
