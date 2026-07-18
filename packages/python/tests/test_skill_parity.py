"""
Validates skills/ai-product-pulse/SKILL.md against the actual agentskills.io
spec rules (not assumptions about them), and confirms every staged copy
(.claude/skills/, .cursor/skills/) is byte-identical to the canonical
version. This is the mechanism, not just the intention, behind "one
skill, staged in several places, never hand-edited per-harness."
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = REPO_ROOT / "skills" / "ai-product-pulse" / "SKILL.md"
STAGED_COPIES = [
    REPO_ROOT / ".claude" / "skills" / "ai-product-pulse" / "SKILL.md",
    REPO_ROOT / ".cursor" / "skills" / "ai-product-pulse" / "SKILL.md",
]

_NAME_PATTERN = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")


def _split_frontmatter(text: str) -> tuple[dict, str]:
    assert text.startswith("---\n"), "SKILL.md must start with a frontmatter delimiter"
    parts = text.split("---\n", 2)
    assert len(parts) == 3, "expected exactly two '---' delimiters framing the frontmatter"
    frontmatter = yaml.safe_load(parts[1])
    body = parts[2]
    return frontmatter, body


@pytest.fixture
def canonical_text() -> str:
    assert CANONICAL.exists(), "canonical SKILL.md is missing"
    return CANONICAL.read_text(encoding="utf-8")


# ── frontmatter spec compliance ─────────────────────────────────────────


def test_name_matches_parent_folder_exactly(canonical_text):
    fm, _ = _split_frontmatter(canonical_text)
    assert fm["name"] == CANONICAL.parent.name


def test_name_is_valid_kebab_case_under_64_chars(canonical_text):
    fm, _ = _split_frontmatter(canonical_text)
    name = fm["name"]
    assert _NAME_PATTERN.fullmatch(name), f"'{name}' is not valid kebab-case"
    assert len(name) <= 64


def test_description_present_and_under_1024_chars(canonical_text):
    fm, _ = _split_frontmatter(canonical_text)
    assert "description" in fm
    assert len(fm["description"]) <= 1024


def test_description_has_no_angle_brackets():
    """Angle brackets in frontmatter can inject unintended instructions
    into the system prompt per the spec's own safety note — this isn't
    a style preference, it's a real injection vector."""
    fm, _ = _split_frontmatter(CANONICAL.read_text(encoding="utf-8"))
    desc = fm["description"]
    assert "<" not in desc and ">" not in desc


def test_description_states_both_what_and_when():
    """Loose heuristic, not a strict parse: the description should read
    like it covers both capability and trigger condition, not just one."""
    fm, _ = _split_frontmatter(CANONICAL.read_text(encoding="utf-8"))
    desc = fm["description"].lower()
    assert "use when" in desc or "use this" in desc, (
        "description should state when to use the skill, not just what it does"
    )


def test_body_stays_within_recommended_token_budget(canonical_text):
    """Soft guidance from the spec: full SKILL.md body under ~5000 tokens
    since it all loads into context on activation. Rough 4-chars/token
    estimate — not exact, but enough to catch real bloat."""
    _, body = _split_frontmatter(canonical_text)
    approx_tokens = len(body) / 4
    assert approx_tokens < 5000, f"body is ~{approx_tokens:.0f} estimated tokens, over the recommended budget"


def test_license_field_present(canonical_text):
    fm, _ = _split_frontmatter(canonical_text)
    assert fm.get("license") == "MIT"


# ── staged-copy parity (the actual "no per-harness drift" guarantee) ───


@pytest.mark.parametrize("staged_path", STAGED_COPIES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_staged_copy_is_byte_identical_to_canonical(staged_path, canonical_text):
    assert staged_path.exists(), f"staged copy missing: {staged_path}"
    assert staged_path.read_text(encoding="utf-8") == canonical_text, (
        f"{staged_path} has drifted from the canonical skill — "
        "re-run install-skill.sh or copy it manually, never hand-edit a staged copy"
    )
