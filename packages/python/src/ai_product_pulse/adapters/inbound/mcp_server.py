"""
MCP server adapter for AI Product Pulse.

This file's only job is translation: MCP tool call in, use-case function
call, JSON-serializable result out. No scoring logic, no validation
beyond what the use cases already do — if you're debugging why a verdict
did or didn't fire, look in domain/scoring_engine.py, not here.

Run directly for stdio transport (what Claude Code / Cursor expect):
    python -m ai_product_pulse.adapters.inbound.mcp_server
"""
from __future__ import annotations

import json
from typing import Annotated, Any, cast

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from ...domain.entities import (
    ExplanationResult,
    FeatureReport,
    GoldenSetCalibrationResult,
    ProductReport,
    RegressionDiffResult,
)
from ...usecases.aggregate_product_pulse import aggregate_product_pulse as _aggregate_product_pulse
from ...usecases.explain import explain as _explain
from ...usecases.golden_set_calibrate import GoldenSetCase, golden_set_calibrate as _golden_set_calibrate
from ...usecases.regression_diff import regression_diff as _regression_diff
from ...usecases.triage import LayerInput, triage as _triage

mcp = FastMCP(
    "ai-product-pulse",
    instructions=(
        "Triage AI product features against the AI Product Pulse framework "
        "(Model Performance / Product Behaviour / Business Outcome). Score "
        "each layer 1-5 against the maturity_ladder in framework.json based "
        "on evidence the user provides, then call triage. For a product "
        "with multiple AI features, call triage once per feature, then "
        "pass all the resulting reports into aggregate_product_pulse. To "
        "check whether a feature improved since a prior triage, call "
        "regression_diff with both reports. To render a report as prose "
        "instead of JSON — for sharing with a stakeholder — call explain. "
        "To check the scoring logic against a set of known cases, call "
        "calibrate."
    ),
)


def _to_jsonable(
    model: FeatureReport | ProductReport | RegressionDiffResult | ExplanationResult | GoldenSetCalibrationResult,
) -> dict[str, Any]:
    """Pydantic model -> plain dict via its own JSON serialization, so
    datetimes and other non-trivial types come out the way the schema
    expects rather than however Python's default dict conversion would
    render them."""
    return cast(dict[str, Any], json.loads(model.model_dump_json()))


@mcp.tool()
def triage(
    subject_name: Annotated[str, Field(description="Name of the AI feature being scored, e.g. 'AI Search Assistant'.")],
    layers: Annotated[list[LayerInput], Field(description="Exactly three entries, one each for model_performance, product_behaviour, and business_outcome.")],
    subject_description: Annotated[str | None, Field(description="Optional free-text context about the feature.")] = None,
    generated_by_harness: Annotated[str | None, Field(description="Which harness produced this report, e.g. 'claude-code'. Used for harness-invariance comparisons.")] = None,
    vanity_metric_flags: Annotated[list[str] | None, Field(description="IDs of any vanity_metric_probes from framework.json that matched the evidence — see framework.json's vanity_metric_probes list for valid IDs.")] = None,
    recommendations: Annotated[str | None, Field(description="Optional free-text next-step recommendations, not part of the deterministic scoring.")] = None,
) -> dict[str, Any]:
    """Score one AI feature against the AI Product Pulse framework.

    Requires exactly three LayerInput entries — model_performance,
    product_behaviour, business_outcome — each with a 1-5 score you assign
    by reading the maturity_ladder in framework.json and matching it
    against whatever evidence the user gave you. Everything past that
    score (maturity labels, overall_score, maturity_level, which verdicts
    fire) is computed deterministically, not re-judged by you.
    """
    report: FeatureReport = _triage(
        subject_name=subject_name,
        layers=layers,
        subject_description=subject_description,
        generated_by_harness=generated_by_harness,
        vanity_metric_flags=vanity_metric_flags,
        recommendations=recommendations,
    )
    return _to_jsonable(report)


@mcp.tool()
def aggregate_product_pulse(
    subject_name: Annotated[str, Field(description="Name of the product these features belong to, e.g. 'Core AI Suite'.")],
    features: Annotated[list[FeatureReport], Field(description="Two or more FeatureReport objects, each previously returned by triage(). Must share the same framework_version and have unique subject_name values.")],
    subject_description: Annotated[str | None, Field(description="Optional free-text context about the product.")] = None,
    generated_by_harness: Annotated[str | None, Field(description="Which harness produced this rollup, e.g. 'claude-code'.")] = None,
) -> dict[str, Any]:
    """Roll up two or more feature-level triage() results into one
    product-level pulse.

    Pass in the full FeatureReport objects triage() returned — this tool
    holds no state between calls, so it needs all of them at once. Verdicts
    are never blended: every verdict from every feature survives in the
    rollup, attributed to the feature that triggered it.
    """
    report = _aggregate_product_pulse(
        subject_name=subject_name,
        features=features,
        subject_description=subject_description,
        generated_by_harness=generated_by_harness,
    )
    return _to_jsonable(report)


@mcp.tool()
def regression_diff(
    previous: Annotated[FeatureReport, Field(description="The earlier FeatureReport, previously returned by triage().")],
    current: Annotated[FeatureReport, Field(description="The later FeatureReport for the same feature, previously returned by triage(). Must be chronologically after previous.")],
) -> dict[str, Any]:
    """Compares two triage() reports for the same feature over time —
    answers whether a previously flagged gap actually got fixed.

    Both reports must share subject_name and framework_version. Returns
    which verdicts resolved, which are newly introduced, which persist,
    the per-layer score deltas, and an overall improved/regressed/mixed/
    unchanged classification.
    """
    diff = _regression_diff(previous=previous, current=current)
    return _to_jsonable(diff)


@mcp.tool()
def explain(
    report: Annotated[FeatureReport, Field(description="A FeatureReport previously returned by triage().")],
) -> dict[str, Any]:
    """Renders a triage report as prose: the arithmetic behind
    overall_score, why maturity_level is capped where it is, and
    per-verdict investigative questions to guide follow-up.

    Deterministic — a rendering of data that already exists in the
    report and in framework.json, not a new judgment call or new
    computation. Useful when the audience is a human who wants a
    readable summary rather than the raw JSON report.
    """
    explanation = _explain(report)
    return _to_jsonable(explanation)


@mcp.tool()
def calibrate(
    cases: Annotated[
        list[GoldenSetCase],
        Field(description="Known cases with expected verdicts/maturity_level. See shared/golden-set/README.md for the format."),
    ],
) -> dict[str, Any]:
    """Runs each case through triage() and reports pass/fail per case
    plus an overall pass rate — checks the scoring logic against known
    answers, rather than trusting it by inspection.

    Important: a high pass rate here only means the code agrees with
    the expectations it was given. It's calibration evidence only if
    those expectations came from real, independently-verified cases —
    see shared/golden-set/README.md before treating any number this
    returns as validation.
    """
    result = _golden_set_calibrate(cases)
    return _to_jsonable(result)


def main() -> None:
    """Entry point for the `ai-product-pulse-mcp` console script. Runs the
    stdio transport — what Claude Code and Cursor expect when they launch
    an MCP server as a subprocess."""
    mcp.run()


if __name__ == "__main__":
    main()
