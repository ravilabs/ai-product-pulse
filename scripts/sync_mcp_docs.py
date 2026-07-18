#!/usr/bin/env python3
"""
Regenerates docs/mcp.md from the live MCP tool registry — the exact same
mcp.list_tools() call a real harness makes, not a hand-written
description of what the tools are supposed to do. If a parameter gets
renamed, added, or removed in mcp_server.py, this doc updates with it
automatically the next time this script runs; it cannot silently drift
the way a hand-maintained tool reference could.

Never hand-edit docs/mcp.md. Edit the tool functions in
adapters/inbound/mcp_server.py (or their docstrings), then rerun this.

Usage: python scripts/sync_mcp_docs.py
"""
from __future__ import annotations

import asyncio
import inspect
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "python" / "src"))

from ai_product_pulse.adapters.inbound.mcp_server import mcp  # noqa: E402

HEADER = """# MCP Tools

GENERATED FILE — DO NOT EDIT DIRECTLY. Produced by `scripts/sync_mcp_docs.py`
directly from the live tool registry (`mcp.list_tools()`), the same call a
real harness makes on connection. Edit the tool functions or their
docstrings in `packages/python/src/ai_product_pulse/adapters/inbound/mcp_server.py`,
then rerun the script.

Both tools call the identical use-case functions the CLI does —
`ai_product_pulse.usecases.triage.triage` and
`ai_product_pulse.usecases.aggregate_product_pulse.aggregate_product_pulse`.
Nothing described here is MCP-specific logic; this is a translation layer.

"""


def _render_schema_table(properties: dict, required: list[str]) -> str:
    if not properties:
        return "_No parameters._\n"
    lines = ["| Parameter | Type | Required | Description |", "|---|---|---|---|"]
    for name, spec in properties.items():
        type_str = _describe_type(spec)
        is_required = "Yes" if name in required else "No"
        description = spec.get("description", spec.get("title", "")).replace("\n", " ")
        lines.append(f"| `{name}` | {type_str} | {is_required} | {description} |")
    return "\n".join(lines) + "\n"


def _describe_type(spec: dict) -> str:
    if "$ref" in spec:
        return spec["$ref"].rsplit("/", 1)[-1]
    if "anyOf" in spec:
        return " \\| ".join(_describe_type(s) for s in spec["anyOf"] if s.get("type") != "null")
    if spec.get("type") == "array":
        items = spec.get("items", {})
        return f"array[{_describe_type(items)}]"
    return str(spec.get("type", "any"))


def main(out_path: Path) -> None:
    tools = asyncio.run(mcp.list_tools())

    sections = [HEADER]
    for tool in sorted(tools, key=lambda t: t.name):
        schema = tool.inputSchema
        properties = schema.get("properties", {})
        required = schema.get("required", [])

        sections.append(f"## `{tool.name}`\n")
        sections.append(f"{inspect.cleandoc(tool.description or '')}\n")
        sections.append("**Parameters:**\n")
        sections.append(_render_schema_table(properties, required))
        sections.append("")

    out_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"OK — {out_path} regenerated from the live tool registry ({len(tools)} tools).")


if __name__ == "__main__":
    main(REPO_ROOT / "docs" / "mcp.md")
