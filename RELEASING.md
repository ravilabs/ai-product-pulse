# Releasing

`publish.yml` handles PyPI and npm publishing via OIDC trusted
publishing — no stored tokens, gated behind a manual approval step
(GitHub Environments with required reviewers) since publishing is
irreversible on both registries. This document describes the real,
current process.

## One-time setup — only you can do this part

Neither CI nor an agent can complete these: they require your own
registry accounts, 2FA, and in npm's case a manual publish from a
machine you're logged into. Do this once, before the first tagged
release.

**GitHub side, both registries:**
1. Repo Settings → Environments → create `pypi` and `npm` environments.
2. On each, add yourself as a required reviewer. This is what makes the
   workflow pause for approval instead of publishing the moment a tag
   is pushed.

**PyPI** — supports registering a trusted publisher before the project
exists ("pending" publisher):
1. On pypi.org, while logged in: Publishing → add a pending publisher.
2. Project name `ai-product-pulse`, owner/repo `ravilabs/ai-product-pulse`,
   workflow filename `publish.yml`, environment name `pypi`.
3. Nothing else needed — the first successful tag-triggered run creates
   the project and publishes it in one step.

**npm** — does not support this for a package that doesn't exist yet.
The first publish has to happen manually:
1. `npm login` (needs your npm account, 2FA if enabled — as it should be).
2. `cd packages/node && npm publish` — this is the one manual publish,
   ever. Confirm it actually worked: check `https://www.npmjs.com/package/ai-product-pulse`.
3. Only after that: on npmjs.com, go to the package's Settings →
   Trusted Publisher → GitHub Actions, and fill in owner/repo
   `ravilabs/ai-product-pulse`, workflow filename `publish.yml`,
   environment name `npm`.
4. From here on, `publish.yml` handles it — the manual step above
   never needs repeating.

Both names were confirmed available (via each registry's own API, not
just search) before any of this was built.

## Before releasing

1. All checks pass — see CONTRIBUTING.md's "Before opening a PR" section.
   Run the full suite for both packages, not just the one you changed.
2. If `framework.json` changed, confirm the sync scripts have been run
   and their outputs committed:
   ```bash
   python scripts/sync_framework_yaml.py
   python scripts/sync_report_schema.py
   python scripts/sync_package_data.py
   ```
   `parity.yml` checks this on every push, and `publish.yml` checks it
   again immediately before building — but catching it before you tag
   is faster than watching a release run fail.
3. Confirm both packages install and run for real, not just from an
   editable/dev checkout — this is the exact class of bug that shipped
   twice during initial development (`framework.json` not bundled in
   the Python wheel; the CLI silently doing nothing through npm's bin
   symlink). `npm test` in `packages/node` already does this via
   `test/packaging.test.ts`; for Python:
   ```bash
   python3 -m venv /tmp/release_check
   /tmp/release_check/bin/pip install packages/python
   cd /tmp && echo '{"subject_name":"x","layers":[...]}' | /tmp/release_check/bin/ai-product-pulse triage
   ```
   Run from a directory with no repo checkout nearby — the point is
   confirming it doesn't depend on one being present.

## Version bumps

Four places currently need to agree, since there's no single-source
version yet:

- `framework.json`'s `version` field
- `packages/python/pyproject.toml`'s `version` field (Python package)
- `packages/python/src/ai_product_pulse/__init__.py`'s `__version__`
- `packages/node/package.json`'s `version` field (Node package)
- `CITATION.cff`'s `version` field

Bump `framework.json`'s version for any change to indicators, verdicts,
or thresholds, per CONTRIBUTING.md. Bump both package versions together
for any release — they're kept in lockstep by convention, not by a
technical constraint, so they could diverge if there's ever a real
reason to (a code-only fix in one language, say). Nothing enforces that
yet; decide deliberately if it happens, don't let it happen by accident.

## Tagging

```bash
git tag -a v0.1.1 -m "Short description of what changed"
git push origin v0.1.1
```

This is what triggers `publish.yml`. Use the package version, not the
framework schema version, for the tag.

## What happens after you push a tag

1. `publish-python` and `publish-node` both start, in parallel.
2. Each pauses at its Environment's approval gate. You'll get a
   notification; review the run, then approve it from the Actions tab.
3. `publish-python` re-verifies no sync-script drift, builds, publishes
   via PyPI's trusted publisher (no token).
4. `publish-node` runs the full test suite (including the real
   pack/install/bin-symlink test) one more time on this exact commit,
   then publishes via npm's trusted publisher (no token) — after the
   one-time manual first publish described above.

## After releasing

Confirm the install actually works from the published registry, not
just from a local build:

```bash
uvx --from ai-product-pulse ai-product-pulse-mcp
npx --yes ai-product-pulse-mcp
```

If either fails right after a release, that's the first thing to fix,
before anything else — these are the exact commands every `SKILL.md`
and `mcp/*.json.example` in this repo tells a user to run.
