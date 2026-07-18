"""
CLI adapter for AI Product Pulse. Mirrors the MCP server's five tools
exactly — triage, aggregate, diff, explain, and calibrate — because a
harness with no MCP support should get identical behavior through the
command line. All adapters call the same use-case functions
underneath; none of them contains logic the others don't also go
through.

Usage:
    ai-product-pulse triage --input evidence.json [--output report.json]
    ai-product-pulse aggregate --input features.json [--output report.json]
    ai-product-pulse diff --previous prev.json --current cur.json [--output diff.json]
    ai-product-pulse explain --input report.json [--output explanation.json]
    ai-product-pulse calibrate --input golden-set.json [--output results.json]

evidence.json shape: {"subject_name": ..., "layers": [...], ...} —
same fields as the MCP triage tool's arguments.

features.json shape: {"subject_name": ..., "features": [<FeatureReport>, ...]} —
each entry in "features" is a full FeatureReport, typically produced by a
prior `triage` CLI call.

prev.json / cur.json: each a single FeatureReport, both typically
produced by prior `triage` CLI calls for the same feature.

report.json (for explain): a single FeatureReport, typically produced
by a prior `triage` CLI call.

golden-set.json (for calibrate): {"cases": [<GoldenSetCase>, ...]} — see
shared/golden-set/README.md for the format and, importantly, what does
and doesn't count as real calibration evidence.

No external CLI framework dependency (argparse only) — this keeps
`uvx`/`pipx` installs light and matches the zero-install philosophy the
rest of this repo is built around.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from ...domain.entities import FeatureReport
from ...usecases.aggregate_product_pulse import aggregate_product_pulse
from ...usecases.explain import explain
from ...usecases.golden_set_calibrate import GoldenSetCase, golden_set_calibrate
from ...usecases.regression_diff import regression_diff
from ...usecases.triage import LayerInput, triage


def _read_input(path: str | None) -> dict[str, Any]:
    raw = Path(path).read_text(encoding="utf-8") if path else sys.stdin.read()
    return cast(dict[str, Any], json.loads(raw))


def _write_output(payload: dict[str, Any], path: str | None) -> None:
    text = json.dumps(payload, indent=2)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


def _run_triage(args: argparse.Namespace) -> int:
    data = _read_input(args.input)
    try:
        layers = [LayerInput.model_validate(layer) for layer in data["layers"]]
        report = triage(
            subject_name=data["subject_name"],
            layers=layers,
            subject_description=data.get("subject_description"),
            generated_by_harness=data.get("generated_by_harness") or "cli",
            vanity_metric_flags=data.get("vanity_metric_flags"),
            recommendations=data.get("recommendations"),
        )
    except (ValidationError, ValueError, KeyError) as exc:
        print(f"triage failed: {exc}", file=sys.stderr)
        return 1
    _write_output(json.loads(report.model_dump_json()), args.output)
    return 0


def _run_aggregate(args: argparse.Namespace) -> int:
    data = _read_input(args.input)
    try:
        features = [FeatureReport.model_validate(f) for f in data["features"]]
        report = aggregate_product_pulse(
            subject_name=data["subject_name"],
            features=features,
            subject_description=data.get("subject_description"),
            generated_by_harness=data.get("generated_by_harness") or "cli",
        )
    except (ValidationError, ValueError, KeyError) as exc:
        print(f"aggregate failed: {exc}", file=sys.stderr)
        return 1
    _write_output(json.loads(report.model_dump_json()), args.output)
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    try:
        previous = FeatureReport.model_validate(_read_input(args.previous))
        current = FeatureReport.model_validate(_read_input(args.current))
        diff = regression_diff(previous=previous, current=current)
    except (ValidationError, ValueError, KeyError) as exc:
        print(f"diff failed: {exc}", file=sys.stderr)
        return 1
    _write_output(json.loads(diff.model_dump_json()), args.output)
    return 0


def _run_explain(args: argparse.Namespace) -> int:
    try:
        report = FeatureReport.model_validate(_read_input(args.input))
        explanation = explain(report)
    except (ValidationError, ValueError, KeyError) as exc:
        print(f"explain failed: {exc}", file=sys.stderr)
        return 1
    _write_output(json.loads(explanation.model_dump_json()), args.output)
    return 0


def _run_calibrate(args: argparse.Namespace) -> int:
    try:
        data = _read_input(args.input)
        cases = [GoldenSetCase.model_validate(c) for c in data["cases"]]
        result = golden_set_calibrate(cases)
    except (ValidationError, ValueError, KeyError) as exc:
        print(f"calibrate failed: {exc}", file=sys.stderr)
        return 1
    _write_output(json.loads(result.model_dump_json()), args.output)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-product-pulse")
    subparsers = parser.add_subparsers(dest="command", required=True)

    triage_parser = subparsers.add_parser("triage", help="Score one AI feature.")
    triage_parser.add_argument("--input", "-i", help="Path to evidence JSON. Reads stdin if omitted.")
    triage_parser.add_argument("--output", "-o", help="Path to write the report JSON. Prints to stdout if omitted.")
    triage_parser.set_defaults(func=_run_triage)

    aggregate_parser = subparsers.add_parser(
        "aggregate", help="Roll up two or more feature reports into a product-level pulse."
    )
    aggregate_parser.add_argument("--input", "-i", help="Path to features JSON. Reads stdin if omitted.")
    aggregate_parser.add_argument("--output", "-o", help="Path to write the report JSON. Prints to stdout if omitted.")
    aggregate_parser.set_defaults(func=_run_aggregate)

    diff_parser = subparsers.add_parser(
        "diff", help="Compare two triage reports for the same feature over time."
    )
    diff_parser.add_argument("--previous", required=True, help="Path to the earlier FeatureReport JSON.")
    diff_parser.add_argument("--current", required=True, help="Path to the later FeatureReport JSON.")
    diff_parser.add_argument("--output", "-o", help="Path to write the diff JSON. Prints to stdout if omitted.")
    diff_parser.set_defaults(func=_run_diff)

    explain_parser = subparsers.add_parser(
        "explain", help="Render a triage report as prose — arithmetic, maturity cap, and per-verdict guidance."
    )
    explain_parser.add_argument("--input", "-i", help="Path to a FeatureReport JSON. Reads stdin if omitted.")
    explain_parser.add_argument("--output", "-o", help="Path to write the explanation JSON. Prints to stdout if omitted.")
    explain_parser.set_defaults(func=_run_explain)

    calibrate_parser = subparsers.add_parser(
        "calibrate", help="Run a golden-set file through triage() and report pass/fail per case."
    )
    calibrate_parser.add_argument("--input", "-i", help="Path to a golden-set JSON file. Reads stdin if omitted.")
    calibrate_parser.add_argument("--output", "-o", help="Path to write the calibration result JSON. Prints to stdout if omitted.")
    calibrate_parser.set_defaults(func=_run_calibrate)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    # args.func is set dynamically via set_defaults(func=...) per subcommand —
    # argparse.Namespace has no way to express that statically, so this cast
    # documents a real, understood boundary rather than papering over an
    # actual type error.
    return cast(int, args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
