#!/usr/bin/env python3
"""
Copies the canonical repo-root framework.json into every package that
needs a bundled copy: the Python package (so importlib.resources can
find it regardless of install type) and the Node package (so its own
loader.ts, resolving relative to the compiled module's own location,
finds it the same way).

The repo-root copy remains the single source of truth for editing.
This script does no transformation — a byte-for-byte copy to each
destination — because unlike framework.yaml or report.schema.json,
there's no format conversion happening here, just a packaging
necessity. Tests in each package's suite fail if a copy drifts from
the source (test_packaged_framework_json_matches_repo_root_source on
the Python side; the equivalent check belongs in the Node suite too).

Usage: python scripts/sync_package_data.py
"""
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "framework.json"
DESTINATIONS = [
    REPO_ROOT / "packages" / "python" / "src" / "ai_product_pulse" / "framework.json",
    REPO_ROOT / "packages" / "node" / "framework.json",
]


def main() -> None:
    if not SOURCE.exists():
        print(f"Source not found: {SOURCE}", file=sys.stderr)
        sys.exit(1)

    source_bytes = SOURCE.read_bytes()
    for dest in DESTINATIONS:
        if not dest.parent.exists():
            print(f"Skipping {dest} — parent directory doesn't exist yet.")
            continue
        shutil.copyfile(SOURCE, dest)
        if dest.read_bytes() != source_bytes:
            print(f"PARITY CHECK FAILED — {dest} did not match source after copying", file=sys.stderr)
            sys.exit(1)
        print(f"OK — {dest} synced from {SOURCE}.")


if __name__ == "__main__":
    main()
