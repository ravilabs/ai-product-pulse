from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_product_pulse.adapters.inbound.cli import main

TRIAGE_INPUT = {
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
            "indicators": [{"indicator_id": "override_rate", "tracked": True, "value": 46.0}],
        },
        {
            "layer_id": "business_outcome",
            "score": 1,
            "evidence_summary": "No metric defined.",
            "indicators": [{"indicator_id": "attributed_business_impact", "tracked": False}],
        },
    ],
}


def test_triage_file_to_file(tmp_path):
    input_path = tmp_path / "evidence.json"
    output_path = tmp_path / "report.json"
    input_path.write_text(json.dumps(TRIAGE_INPUT))

    exit_code = main(["triage", "--input", str(input_path), "--output", str(output_path)])

    assert exit_code == 0
    report = json.loads(output_path.read_text())
    assert report["subject_name"] == "AI Search Assistant"
    verdict_ids = {v["verdict_id"] for v in report["verdicts"]}
    assert "business_outcome_orphaned" in verdict_ids
    assert "trust_failure_signal" in verdict_ids
    assert report["generated_by_harness"] == "cli"


def test_triage_stdin_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO(json.dumps(TRIAGE_INPUT)))

    exit_code = main(["triage"])

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["subject_name"] == "AI Search Assistant"


def test_triage_missing_layer_fails_cleanly(tmp_path, capsys):
    broken = {**TRIAGE_INPUT, "layers": TRIAGE_INPUT["layers"][:2]}  # drop business_outcome
    input_path = tmp_path / "evidence.json"
    input_path.write_text(json.dumps(broken))

    exit_code = main(["triage", "--input", str(input_path)])

    assert exit_code == 1
    assert "triage failed" in capsys.readouterr().err


def test_aggregate_rolls_up_two_triage_outputs(tmp_path):
    # Chain the CLI's own triage output into its own aggregate input —
    # proves the two subcommands actually interoperate, not just that
    # each independently produces plausible-looking JSON.
    input_a = tmp_path / "a.json"
    report_a = tmp_path / "report_a.json"
    input_a.write_text(json.dumps(TRIAGE_INPUT))
    assert main(["triage", "--input", str(input_a), "--output", str(report_a)]) == 0

    balanced_input = {
        "subject_name": "AI Summarizer",
        "layers": [
            {"layer_id": "model_performance", "score": 3, "evidence_summary": "x", "indicators": []},
            {"layer_id": "product_behaviour", "score": 3, "evidence_summary": "x", "indicators": []},
            {"layer_id": "business_outcome", "score": 3, "evidence_summary": "x", "indicators": []},
        ],
    }
    input_b = tmp_path / "b.json"
    report_b = tmp_path / "report_b.json"
    input_b.write_text(json.dumps(balanced_input))
    assert main(["triage", "--input", str(input_b), "--output", str(report_b)]) == 0

    features_input = tmp_path / "features.json"
    features_input.write_text(json.dumps({
        "subject_name": "Core AI Suite",
        "features": [json.loads(report_a.read_text()), json.loads(report_b.read_text())],
    }))
    product_output = tmp_path / "product.json"

    exit_code = main(["aggregate", "--input", str(features_input), "--output", str(product_output)])

    assert exit_code == 0
    product = json.loads(product_output.read_text())
    assert product["unit_of_assessment"] == "product"
    assert product["product_maturity_level"] == 1
    assert len(product["features"]) == 2


def test_aggregate_single_feature_fails_cleanly(tmp_path, capsys):
    input_a = tmp_path / "a.json"
    report_a = tmp_path / "report_a.json"
    input_a.write_text(json.dumps(TRIAGE_INPUT))
    main(["triage", "--input", str(input_a), "--output", str(report_a)])

    features_input = tmp_path / "features.json"
    features_input.write_text(json.dumps({
        "subject_name": "Suite",
        "features": [json.loads(report_a.read_text())],
    }))

    exit_code = main(["aggregate", "--input", str(features_input)])

    assert exit_code == 1
    assert "aggregate failed" in capsys.readouterr().err


def test_no_command_exits_nonzero():
    with pytest.raises(SystemExit):
        main([])


def test_diff_compares_two_chained_triage_outputs(tmp_path):
    orphaned_input = tmp_path / "orphaned.json"
    orphaned_report = tmp_path / "orphaned_report.json"
    orphaned_input.write_text(json.dumps(TRIAGE_INPUT))
    assert main(["triage", "--input", str(orphaned_input), "--output", str(orphaned_report)]) == 0

    fixed_input_data = {
        **TRIAGE_INPUT,
        "layers": [
            TRIAGE_INPUT["layers"][0],
            TRIAGE_INPUT["layers"][1],
            {"layer_id": "business_outcome", "score": 3, "evidence_summary": "Fixed.", "indicators": []},
        ],
    }
    fixed_input = tmp_path / "fixed.json"
    fixed_report = tmp_path / "fixed_report.json"
    fixed_input.write_text(json.dumps(fixed_input_data))
    assert main(["triage", "--input", str(fixed_input), "--output", str(fixed_report)]) == 0

    # Force an unambiguous chronological gap on both ends — leaving
    # `previous` at its real default (today's actual date) was the bug
    # here originally: "today" is later than the hardcoded "2026-06-01"
    # used for `current`, so the validator correctly rejected it.
    orphaned_data = json.loads(orphaned_report.read_text())
    orphaned_data["generated_at"] = "2026-01-01T00:00:00Z"
    orphaned_report.write_text(json.dumps(orphaned_data))

    fixed_data = json.loads(fixed_report.read_text())
    fixed_data["generated_at"] = "2026-06-01T00:00:00Z"
    fixed_report.write_text(json.dumps(fixed_data))

    diff_output = tmp_path / "diff.json"
    exit_code = main([
        "diff", "--previous", str(orphaned_report), "--current", str(fixed_report),
        "--output", str(diff_output),
    ])

    assert exit_code == 0
    diff = json.loads(diff_output.read_text())
    assert diff["summary"] == "improved"
    assert any(v["verdict_id"] == "business_outcome_orphaned" for v in diff["verdicts_resolved"])


def test_diff_rejects_out_of_order_reports_cleanly(tmp_path, capsys):
    later_input = tmp_path / "later.json"
    later_report = tmp_path / "later_report.json"
    later_input.write_text(json.dumps(TRIAGE_INPUT))
    main(["triage", "--input", str(later_input), "--output", str(later_report)])
    later_data = json.loads(later_report.read_text())
    later_data["generated_at"] = "2026-06-01T00:00:00Z"
    later_report.write_text(json.dumps(later_data))

    earlier_input = tmp_path / "earlier.json"
    earlier_report = tmp_path / "earlier_report.json"
    earlier_input.write_text(json.dumps(TRIAGE_INPUT))
    main(["triage", "--input", str(earlier_input), "--output", str(earlier_report)])
    earlier_data = json.loads(earlier_report.read_text())
    earlier_data["generated_at"] = "2026-01-01T00:00:00Z"
    earlier_report.write_text(json.dumps(earlier_data))

    # Passing the later report as --previous and the earlier as --current is backwards.
    exit_code = main(["diff", "--previous", str(later_report), "--current", str(earlier_report)])

    assert exit_code == 1
    assert "diff failed" in capsys.readouterr().err


def test_explain_renders_a_chained_triage_output(tmp_path):
    evidence_input = tmp_path / "evidence.json"
    report_output = tmp_path / "report.json"
    evidence_input.write_text(json.dumps(TRIAGE_INPUT))
    assert main(["triage", "--input", str(evidence_input), "--output", str(report_output)]) == 0

    explanation_output = tmp_path / "explanation.json"
    exit_code = main(["explain", "--input", str(report_output), "--output", str(explanation_output)])

    assert exit_code == 0
    explanation = json.loads(explanation_output.read_text())
    assert "AI Search Assistant" in explanation["narrative"]
    assert explanation["overall_score_formula"]
    assert len(explanation["verdict_guidance"]) >= 1


def test_explain_fails_cleanly_on_malformed_input(tmp_path, capsys):
    bad_input = tmp_path / "not_a_report.json"
    bad_input.write_text(json.dumps({"this": "is not a FeatureReport"}))

    exit_code = main(["explain", "--input", str(bad_input)])

    assert exit_code == 1
    assert "explain failed" in capsys.readouterr().err


def test_calibrate_runs_against_the_real_shipped_illustrative_file(capsys):
    golden_set_path = (
        Path(__file__).resolve().parents[3] / "shared" / "golden-set" / "example-cases.json"
    )
    assert golden_set_path.exists()

    exit_code = main(["calibrate", "--input", str(golden_set_path)])

    assert exit_code == 0
    result = json.loads(capsys.readouterr().out)
    assert result["total_cases"] == 4
    assert result["pass_rate"] == 1.0


def test_calibrate_reports_correct_pass_rate(tmp_path, capsys):
    golden_set = {
        "cases": [
            {
                "case_id": "pass-case",
                "description": "test",
                "layers": [
                    {"layer_id": "model_performance", "score": 3, "evidence_summary": "x", "indicators": []},
                    {"layer_id": "product_behaviour", "score": 3, "evidence_summary": "x", "indicators": []},
                    {"layer_id": "business_outcome", "score": 3, "evidence_summary": "x", "indicators": []},
                ],
                "expected_verdict_ids": ["balanced"],
            },
            {
                "case_id": "fail-case",
                "description": "test — deliberately wrong expectation",
                "layers": [
                    {"layer_id": "model_performance", "score": 4, "evidence_summary": "x", "indicators": []},
                    {"layer_id": "product_behaviour", "score": 4, "evidence_summary": "x", "indicators": []},
                    {"layer_id": "business_outcome", "score": 1, "evidence_summary": "x", "indicators": []},
                ],
                "expected_verdict_ids": ["balanced"],
            },
        ]
    }
    golden_set_path = tmp_path / "golden-set.json"
    golden_set_path.write_text(json.dumps(golden_set))
    output_path = tmp_path / "results.json"

    exit_code = main(["calibrate", "--input", str(golden_set_path), "--output", str(output_path)])

    assert exit_code == 0
    result = json.loads(output_path.read_text())
    assert result["total_cases"] == 2
    assert result["passed_cases"] == 1
    assert result["pass_rate"] == 0.5


def test_calibrate_fails_cleanly_on_empty_case_list(tmp_path, capsys):
    golden_set_path = tmp_path / "golden-set.json"
    golden_set_path.write_text(json.dumps({"cases": []}))

    exit_code = main(["calibrate", "--input", str(golden_set_path)])

    assert exit_code == 1
    assert "calibrate failed" in capsys.readouterr().err
