#!/usr/bin/env python3
"""
Regenerates framework.yaml from framework.json.

framework.json is the single source of truth (see its own
implementation_notes field). This script is the only thing that should
ever produce or modify framework.yaml. Run it after any edit to
framework.json, before committing.

Usage: python scripts/sync_framework_yaml.py
"""
import json
import yaml
import sys
from pathlib import Path

HEADER = """# ═══════════════════════════════════════════════════════════════════
# GENERATED FILE — DO NOT EDIT DIRECTLY
# ═══════════════════════════════════════════════════════════════════
# This is a read-only YAML mirror of framework.json, generated for
# human readability — GitHub renders it cleanly, and it skims faster
# than JSON without losing any structure. framework.json remains the
# single source of truth (see its implementation_notes field).
#
# To change the framework: edit framework.json, then regenerate this
# file. Hand-editing framework.yaml will be silently overwritten on
# the next sync, and risks the exact doc-drift this repo is built to
# avoid.
#
# Regenerate with: python scripts/sync_framework_yaml.py
# ═══════════════════════════════════════════════════════════════════

"""


def _str_presenter(dumper: yaml.Dumper, data: str):
    """Long prose renders as a folded block scalar (>) instead of a
    quote-escaped one-liner — no '' apostrophe escaping, no colon
    ambiguity, and it wraps to `width` instead of running off the edge.
    Short strings (ids, names) stay plain and unquoted."""
    if len(data) > 80 or "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=">")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, _str_presenter)


def main(json_path: str, yaml_path: str) -> None:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))

    body = yaml.dump(
        data,
        sort_keys=False,       # preserve the deliberate field order from framework.json
        allow_unicode=True,    # keep em dashes etc. readable, not \u-escaped
        default_flow_style=False,
        width=100,
        indent=2,
    )

    Path(yaml_path).write_text(HEADER + body, encoding="utf-8")

    # Round-trip parity check: strip the header, reparse, compare to source.
    reparsed = yaml.safe_load(body)
    if reparsed != data:
        print("PARITY CHECK FAILED — generated YAML does not match framework.json", file=sys.stderr)
        sys.exit(1)
    print(f"OK — {yaml_path} regenerated from {json_path}, parity check passed.")


if __name__ == "__main__":
    main("framework.json", "framework.yaml")
