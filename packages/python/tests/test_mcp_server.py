"""
Integration tests for the MCP server adapter. These go through
mcp.call_tool() — the real mechanism a harness uses — rather than calling
the underlying Python functions directly, so a schema mismatch or
serialization bug would actually get caught here.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import jsonschema
import pytest

from ai_product_pulse.adapters.inbound.mcp_server import mcp


def _call(name: str, arguments: dict):
    return asyncio.run(mcp.call_tool(name, arguments))


def _result_dict(result) -> dict:
    """FastMCP's call_tool can return either a raw dict (structured
    content) or a sequence of ContentBlocks depending on SDK version and
    tool return type. Handle both rather than assume one."""
    if isinstance(result, dict):
        return result
    if isinstance(result, tuple):
        # (content_blocks, structured_content) in newer SDK versions
        _, structured = result
        if isinstance(structured, dict):
            return structured
        result = result[0]
    # Sequence[ContentBlock]: find the text block and parse its JSON.
    for block in result:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError(f"Could not extract a JSON result from: {result!r}")


TRIAGE_ARGS = {
    "subject_name": "AI Search Assistant",
    "layers": [
        {
            "layer_id": "model_performance",
            "score": 4,
            "evidence_summary": "Tracked weekly.",
            "indicators": [
                {"indicator_id": "task_success_rate", "tracked": True, "value": 91.2, "unit": "percentage"}
            ],
        },
        {
            "layer_id": "product_behaviour",
            "score": 2,
            "evidence_summary": "Observed once, not systematic.",
            "indicators": [
                {"indicator_id": "override_rate", "tracked": True, "value": 46.0}
            ],
        },
        {
            "layer_id": "business_outcome",
            "score": 1,
            "evidence_summary": "No metric defined.",
            "indicators": [
                {"indicator_id": "attributed_business_impact", "tracked": False}
            ],
        },
    ],
}


def test_server_registers_all_five_tools():
    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert names == {
        "triage",
        "aggregate_product_pulse",
        "regression_diff",
        "explain",
        "calibrate",
    }


def test_triage_tool_schema_requires_subject_name_and_layers():
    tools = asyncio.run(mcp.list_tools())
    triage_tool = next(t for t in tools if t.name == "triage")
    required = set(triage_tool.inputSchema.get("required", []))
    assert {"subject_name", "layers"}.issubset(required)


def test_triage_tool_call_produces_a_valid_feature_report():
    result = _call("triage", TRIAGE_ARGS)
    report = _result_dict(result)

    assert report["unit_of_assessment"] == "feature"
    assert report["subject_name"] == "AI Search Assistant"
    verdict_ids = {v["verdict_id"] for v in report["verdicts"]}
    assert "business_outcome_orphaned" in verdict_ids
    assert "trust_failure_signal" in verdict_ids

    schema = json.loads(Path("report.schema.json").read_text())
    jsonschema.validate(report, schema)


def test_triage_tool_call_surfaces_validation_errors():
    bad_args = {**TRIAGE_ARGS, "layers": TRIAGE_ARGS["layers"][:2]}  # missing business_outcome
    with pytest.raises(Exception):  # noqa: PT011 — SDK-specific error type, message content is what matters
        _call("triage", bad_args)


def test_aggregate_tool_call_rolls_up_two_triage_results():
    feature_a = _result_dict(_call("triage", TRIAGE_ARGS))
    balanced_args = {
        "subject_name": "AI Summarizer",
        "layers": [
            {"layer_id": "model_performance", "score": 3, "evidence_summary": "x", "indicators": []},
            {"layer_id": "product_behaviour", "score": 3, "evidence_summary": "x", "indicators": []},
            {"layer_id": "business_outcome", "score": 3, "evidence_summary": "x", "indicators": []},
        ],
    }
    feature_b = _result_dict(_call("triage", balanced_args))

    product_result = _call(
        "aggregate_product_pulse",
        {"subject_name": "Core AI Suite", "features": [feature_a, feature_b]},
    )
    product = _result_dict(product_result)

    assert product["unit_of_assessment"] == "product"
    assert product["product_maturity_level"] == 1  # min(1, 3) from feature_a/business_outcome
    assert len(product["features"]) == 2

    schema = json.loads(Path("report.schema.json").read_text())
    jsonschema.validate(product, schema)


def test_regression_diff_tool_call_compares_two_triage_results():
    orphaned = _result_dict(_call("triage", TRIAGE_ARGS))
    # Explicit, unambiguous timestamps on both ends — leaving `orphaned`
    # at its real default (today's actual date) was a real bug here:
    # "today" is later than a hardcoded near-term date for `fixed`.
    orphaned["generated_at"] = "2026-01-01T00:00:00Z"

    fixed_args = {
        **TRIAGE_ARGS,
        "layers": [
            TRIAGE_ARGS["layers"][0],
            TRIAGE_ARGS["layers"][1],
            {"layer_id": "business_outcome", "score": 3, "evidence_summary": "Fixed.", "indicators": []},
        ],
    }
    fixed = _result_dict(_call("triage", fixed_args))
    fixed["generated_at"] = "2026-06-01T00:00:00Z"

    diff_result = _call("regression_diff", {"previous": orphaned, "current": fixed})
    diff = _result_dict(diff_result)

    assert diff["summary"] == "improved"
    assert any(v["verdict_id"] == "business_outcome_orphaned" for v in diff["verdicts_resolved"])


def test_explain_tool_call_renders_a_real_triage_result():
    report = _result_dict(_call("triage", TRIAGE_ARGS))
    explanation_result = _call("explain", {"report": report})
    explanation = _result_dict(explanation_result)

    assert "AI Search Assistant" in explanation["narrative"]
    assert explanation["overall_score_formula"]
    assert len(explanation["verdict_guidance"]) >= 1
    orphaned_guidance = next(
        g for g in explanation["verdict_guidance"] if g["verdict_id"] == "business_outcome_orphaned"
    )
    assert len(orphaned_guidance["investigative_questions"]) > 0


def test_calibrate_tool_call_runs_the_real_shipped_illustrative_file():
    golden_set_path = Path(__file__).resolve().parents[3] / "shared" / "golden-set" / "example-cases.json"
    cases = json.loads(golden_set_path.read_text())["cases"]

    result = _call("calibrate", {"cases": cases})
    calibration = _result_dict(result)

    assert calibration["total_cases"] == 4
    assert calibration["pass_rate"] == 1.0


def test_calibrate_tool_call_surfaces_a_failing_case():
    cases = [
        {
            "case_id": "deliberately-wrong",
            "description": "test",
            "layers": [
                {"layer_id": "model_performance", "score": 4, "evidence_summary": "x", "indicators": []},
                {"layer_id": "product_behaviour", "score": 4, "evidence_summary": "x", "indicators": []},
                {"layer_id": "business_outcome", "score": 1, "evidence_summary": "x", "indicators": []},
            ],
            "expected_verdict_ids": ["balanced"],  # actually fires business_outcome_orphaned
        }
    ]
    result = _call("calibrate", {"cases": cases})
    calibration = _result_dict(result)

    assert calibration["pass_rate"] == 0.0
    assert calibration["case_results"][0]["passed"] is False
