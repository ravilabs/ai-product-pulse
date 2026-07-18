# Security Policy

## Supported versions

AI Product Pulse is pre-1.0. Security fixes are made against the latest
released version only — there's no back-porting policy yet, since there's
no version old enough to need one.

| Version | Supported |
|---|---|
| 0.1.x | Yes |

## Reporting a vulnerability

Please report security vulnerabilities privately, not through a public
GitHub issue.

Use GitHub's private vulnerability reporting: go to the
[Security tab](https://github.com/ravilabs/ai-product-pulse/security) of
this repository and select **Report a vulnerability**. This opens a
private advisory visible only to the maintainer until a fix is ready —
no need to share details in the open before there's a patch.

Include, as far as you're able:

- What the vulnerability is and where it lives (which file, which tool
  call, which input)
- Steps to reproduce, or a minimal example
- What you'd expect to happen instead

## What to expect

This is a solo-maintained project. There's no funded security team and no
contractual SLA — reports get triaged and addressed on a best-effort
basis. Reasonable range to expect an initial response: a few days, not
hours. If it's genuinely urgent (e.g., a flaw that lets one user's
`triage()` call affect another's data, or a code-execution path through
`framework.json` or an MCP tool argument), say so explicitly in the
report.

## Scope

In scope: the Python package (`packages/python`), the MCP server and CLI
adapters, and the skill files under `skills/`, `.claude/skills/`, and
`.cursor/skills/`.

Out of scope: vulnerabilities in Claude Code, Cursor, OpenClaw, Hermes,
or any other harness this project integrates with — report those to the
harness's own maintainers.
