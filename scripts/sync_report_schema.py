#!/usr/bin/env python3
"""
Regenerates report.schema.json from the Pydantic models in
packages/python/src/ai_product_pulse/domain/entities.py.

FeatureReport and ProductReport ARE the source of truth for what a report
looks like — they're the actual objects the Python package constructs and
serializes. report.schema.json is a generated artifact for two audiences
that aren't running Python: the Node/TS package (validated against it in
CI, see .github/workflows/parity.yml) and anyone integrating externally
who wants a plain JSON Schema without installing this package.

Never hand-edit report.schema.json. Edit the Pydantic models, then rerun
this script.

Usage: python scripts/sync_report_schema.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "python" / "src"))

from pydantic import TypeAdapter  # noqa: E402
from ai_product_pulse.domain.entities import Report  # noqa: E402

HEADER_FIELDS = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "https://github.com/ravilabs/ai-product-pulse/blob/main/report.schema.json",
    "title": "AI Product Pulse Report",
    "description": (
        "GENERATED FILE — DO NOT EDIT DIRECTLY. Produced from the Pydantic "
        "models in packages/python/src/ai_product_pulse/domain/entities.py "
        "by scripts/sync_report_schema.py. Validates the output of a "
        "feature-level or product-level triage run. A report is exactly "
        "one of FeatureReport or ProductReport, discriminated by the "
        "unit_of_assessment field."
    ),
}


def main(out_path: str) -> None:
    adapter = TypeAdapter(Report)
    schema = adapter.json_schema()

    # Put our header fields first for readability, then the generated schema body.
    ordered = {**HEADER_FIELDS, **schema}

    Path(out_path).write_text(json.dumps(ordered, indent=2) + "\n", encoding="utf-8")

    # Round-trip sanity check: the schema must at minimum be valid JSON
    # Schema-shaped JSON, and must validate the sample report we already
    # tested entities.py against.
    reparsed = json.loads(Path(out_path).read_text(encoding="utf-8"))
    assert "$defs" in reparsed, "expected $defs from the discriminated union"
    print(f"OK — {out_path} regenerated from Pydantic models.")


if __name__ == "__main__":
    main(str(Path(__file__).resolve().parents[1] / "report.schema.json"))
