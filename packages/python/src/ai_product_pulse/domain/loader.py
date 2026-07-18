"""
Loads framework.json into a typed Framework object.

Uses importlib.resources to find the packaged copy of framework.json —
the one shipped inside the ai_product_pulse package directory itself,
not the repo-root copy a developer edits directly. This resolves
correctly regardless of how the package was installed (editable, wheel,
or `pip install ai-product-pulse` from PyPI with no repo checkout in
sight), which a filesystem-relative path counting parent directories
cannot guarantee — a real install copies files into site-packages at a
path with no fixed relationship to the repo root at all.

The repo-root framework.json remains the single source of truth for
editing. scripts/sync_package_data.py copies it into the package
directory, and a test in the suite fails if the two drift apart — see
tests/test_domain.py::test_packaged_framework_json_matches_repo_root_source.

Kept separate from entities.py on purpose: entities.py is pure domain,
no I/O, importable and testable without touching disk. This module is
the one seam where the filesystem (or package resources) enters —
consistent with the hexagonal architecture split agreed for this repo.
"""
from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources
from pathlib import Path

from .entities import Framework


def load_framework(path: str | Path | None = None) -> Framework:
    """Load and validate framework.json. Raises pydantic.ValidationError
    with a precise field path if the file is malformed — this is the
    first line of defense against framework.json and the code drifting,
    since the app simply won't start if they disagree.

    With no path given, reads the copy packaged inside ai_product_pulse
    itself via importlib.resources — this is what every real install
    resolves to. Pass an explicit path only for pointing at a specific
    file, e.g. the live repo-root copy during development."""
    if path is not None:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    else:
        packaged = resources.files("ai_product_pulse").joinpath("framework.json")
        raw = json.loads(packaged.read_text(encoding="utf-8"))
    return Framework.model_validate(raw)


@lru_cache(maxsize=1)
def framework() -> Framework:
    """Process-wide cached singleton. Framework.json doesn't change during
    a run, and re-parsing + re-validating it on every tool call is wasted
    work across 20+ use-case invocations in a single triage session."""
    return load_framework()
