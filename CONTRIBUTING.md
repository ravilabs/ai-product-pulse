# Contributing to AI Product Pulse

## Before anything else

Python (`packages/python`) is the reference implementation. If a change
touches scoring logic, verdict rules, or the framework schema, it starts
here — the Node/TS package is ported from Python and parity-tested
against it, not developed independently.

## Local setup

```bash
python3 -m venv .venv
.venv/bin/pip install -e "packages/python[dev]"
```

This installs the package plus `pytest`, `jsonschema`, and `pyyaml`. It
does not install the linting/type-checking tools below — add those
separately if you're touching code, not just tests:

```bash
.venv/bin/pip install ruff mypy radon bandit pytest-cov
```

## Before opening a PR

Run all of these. CI runs them too, but catching a failure locally is
faster than waiting on a workflow.

```bash
# tests — must pass, no exceptions
PYTHONPATH=packages/python/src pytest packages/python/tests/ -q

# lint — zero errors
ruff check packages/python/src/ai_product_pulse

# types — zero errors, strict mode
mypy packages/python/src/ai_product_pulse --strict --ignore-missing-imports

# if you touched framework.json: regenerate everything derived from it
python scripts/sync_framework_yaml.py
python scripts/sync_report_schema.py
python scripts/sync_package_data.py
```

Node (`packages/node`):

```bash
npm test                 # runs a real build first (pretest), then the full suite
npm run lint              # zero errors
npx tsc --noEmit -p tsconfig.json   # zero errors, strict mode
```

`npm test` includes a real `npm pack` + install + bin-symlink invocation
(`test/packaging.test.ts`) — this is not redundant with the rest of the
suite. Every other test calls exported functions directly or runs
`node dist/....js` by path; neither can catch a broken `package.json`
`files`/`bin` config or a `main`-module check that only fails through an
actual installed symlink. Both of those were real, confirmed bugs that
every other test in the suite missed — see that file's own comments for
what they were. If you touch `package.json`, `cli.ts`'s or
`mcpServer.ts`'s entry-point detection, or anything under `bin`, run
`npm test` specifically, not just `vitest run` — the latter skips
`pretest` and can pass locally while `npm publish` would still ship
something broken.

If any sync script reports a parity failure, that means something
derived from `framework.json` (the YAML mirror, the report schema, the
packaged copy) is now stale. Commit the regenerated output alongside
your change — never hand-edit `framework.yaml`, `report.schema.json`, or
`packages/python/src/ai_product_pulse/framework.json` directly.

## Proposing changes to framework.json

This is the one file everything else derives from, so it gets a higher
bar than typical code changes.

**Adding or changing an indicator, verdict, or maturity anchor:** explain
the product reasoning in the PR description — what failure mode this
catches, why the threshold is what it is. "Seems reasonable" isn't
sufficient justification for a number that ships to everyone.

**Proposing calibrated industry or feature weights:** industry-specific
weighting was deliberately cut from v1 because the earlier draft weights
weren't derived from real evidence — see `scoring.overall_score.weights_extensibility`
in `framework.json`. Reintroducing this needs a golden-set of real
(anonymized is fine) cases the weights are calibrated against, not
another set of numbers that merely sound plausible. A PR proposing
weights without accompanying calibration evidence will be asked for that
evidence before anything else.

**Changing `version` or `schema_version`:** bump `version` for any change
to the framework's content (new indicator, new verdict, changed
threshold). Bump `schema_version` only if the *shape* of `framework.json`
itself changes in a way that would break existing code reading it.

## Code style

Ruff and mypy `--strict` are the actual style guide — if both pass, the
style is fine. A few things beyond what the tools catch:

- Domain logic (`domain/`) stays free of file I/O except in `loader.py`,
  which is the one deliberate seam. New I/O belongs in `adapters/`.
- Trigger-handler functions in `scoring_engine.py` take `**_: Any` to
  absorb keyword arguments they don't use — this is intentional, for
  uniform dispatch, not a shortcut.
- Prefer extracting a validation check into its own named function over
  bundling several checks into one — easier to test, and `radon cc`
  will flag anything that creeps back into high complexity.

## Tests

New logic needs a test that would fail without it — a test that only
exercises the happy path doesn't prove the validation actually validates.
See `test_triage.py`'s `test_blind_spot_does_not_duplicate_business_outcome_orphaned`
for the pattern: it exists because that exact bug shipped once, briefly,
during development, and the test is what would catch it coming back.

## Golden-set contributions

Real (anonymized) product-metrics cases with a known-correct triage
verdict are the single most valuable kind of contribution — they're what
make the scoring logic's claims checkable instead of asserted. See
`shared/golden-set/README.md` for the format once that directory exists.
