# Architecture

## Two different things, kept visibly separate

Everything in this repository is one of two kinds of thing, and they're deliberately never allowed to blend into each other:

**The domain model** — the AI Product Pulse framework itself: three layers, twelve indicators, a maturity ladder, five verdict rules, four vanity-metric probes. This is proprietary intellectual work, encoded as data in `framework.json`. It didn't come from a citation; it came from field use.

**The software architecture** — how that data gets turned into a working tool. This part is built entirely on named, external, checkable patterns. Nothing here claims to be a novel architecture, because it doesn't need to be — the value is in the framework, not in inventing a new way to organize Python files.

Conflating these two is a specific failure mode worth naming directly: it lets an unproven piece of engineering borrow credibility from genuinely field-tested domain logic sitting next to it, and it means a reader who checks one and finds it hollow reasonably starts doubting the other. Keeping them apart protects both.

## The code structure: Hexagonal Architecture

The package follows Ports and Adapters, originally described by Alistair Cockburn in 2005. The shape:

- **`domain/`** — the framework's typed runtime form (`entities.py`), the one seam where the filesystem is touched (`loader.py`), and the deterministic rule-evaluation engine (`scoring_engine.py`). Nothing in this layer knows or cares how it's being called.
- **`usecases/`** — thin orchestration. `triage()` validates input and calls the domain layer to assemble one feature-level report. `aggregate_product_pulse()` does the same for rolling several features into a product-level report. Neither contains scoring logic of its own.
- **`adapters/inbound/`** — the two ways an agent actually reaches this code: an MCP server (`mcp_server.py`) and a CLI (`cli.py`). Both call the identical use-case functions. Neither contains a validation rule or a scoring formula the other doesn't also get for free — if they ever produced different results for the same input, that would be a bug in one adapter's translation layer, not a second copy of logic to debug.

This isn't a rename of anything. It's a different, older, independently-documented pattern that happens to fit the actual shape of this problem: a domain that needs to stay stable while the number of ways to call it — and the number of harnesses it needs to work inside — keeps growing.

## Tool exposition: MCP's own primitives

The MCP server uses the Model Context Protocol's native primitives — Tools for the deterministic scoring operations — correctly, rather than inventing a parallel taxonomy on top of them. This isn't a design choice being defended; it's just using the actual specification this server is built on.

## Nothing here is claimed as proven that isn't

Two verdicts (`business_outcome_orphaned`, `trust_failure_signal`) and the vanity-metric probes are original diagnostic vocabulary — presented as exactly that, not as an established industry standard. If you're citing this project's approach elsewhere, the distinction that matters is: the layers-and-indicators framework is field-tested proprietary work; the code organization is borrowed, cited, and unoriginal on purpose.

## Why every derived file is generated, never hand-authored

`framework.json` is the single source of truth for the framework's content. Four things are mechanically derived from it or from the code, and none of them are meant to be edited directly:

| Generated file | Source | Script |
|---|---|---|
| `framework.yaml` | `framework.json` | `scripts/sync_framework_yaml.py` |
| `report.schema.json` | Pydantic models in `domain/entities.py` | `scripts/sync_report_schema.py` |
| `packages/python/src/ai_product_pulse/framework.json` | root `framework.json` | `scripts/sync_package_data.py` |
| `docs/mcp.md` | live MCP tool registry | `scripts/sync_mcp_docs.py` |

A CI workflow (`.github/workflows/parity.yml`) regenerates all four on every push and fails the build if any of them differ from what's committed. This is the actual enforcement mechanism, not just a documented convention — a script that exists but isn't run in CI only proves drift is possible to prevent, not that it's actually prevented.

## The one place this system isn't deterministic

Everything downstream of a layer score — the maturity label, the overall score, the maturity level, which verdicts fire — is computed by `domain/scoring_engine.py` with zero LLM calls. The one judgment call in the entire pipeline is upstream of that: reading whatever evidence a user gives an agent and assigning a 1-to-5 score per layer against the maturity ladder in `framework.json`.

That's a deliberate boundary, not an oversight. See `docs/failure-modes.md` for what it costs.

## A note on the formula strings inside `framework.json`

Fields like `scoring.overall_score.formula` contain strings such as `"weighted_mean(layer_scores, weights)"`. These are documentation for a human reader, not a mini-language `scoring_engine.py` parses or evaluates — the actual formula is Python code, and the string exists so someone reading `framework.json` doesn't have to open a second file to know what a number means. Evaluating an arbitrary string from a data file as code would be a real risk for no corresponding benefit here.

## Testing philosophy

A few things the test suite does on purpose, beyond checking that inputs produce outputs:

- **Real installs, not just editable ones.** Several bugs in this project only existed under a genuine non-editable `pip install` run from a directory with no repository nearby — editable installs kept pointing back at source files in a way that hid the actual problem. CI installs the package for real, not just with `-e`.
- **Negative-path tests, not just happy-path ones.** A validator nobody's shown capable of failing isn't proven to be checking anything — see the two tests in `test_domain.py` that deliberately break `framework.json`'s invariants (mismatched weights, mismatched layer keys) and confirm the validator actually raises.
- **A named regression test for the one bug that shipped.** `blind_spot`'s trigger once had no exclusion for `business_outcome`, so it silently duplicated `business_outcome_orphaned` on every orphaned feature. `test_blind_spot_does_not_duplicate_business_outcome_orphaned` exists specifically so that doesn't come back quietly.
