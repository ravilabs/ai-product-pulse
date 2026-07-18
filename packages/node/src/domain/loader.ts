/**
 * Loads framework.json into a typed Framework object.
 *
 * Resolves the path via import.meta.url — the module's own actual
 * location after compilation — rather than counting parent directories
 * from an assumed repo root. The Python package had a real bug from
 * exactly that shortcut (loader.py's DEFAULT_FRAMEWORK_PATH originally
 * used `parents[N]`, which broke under a genuine `pip install` outside
 * the monorepo). Using the module's own resolved path here avoids that
 * class of bug from the start rather than fixing it after the fact.
 *
 * framework.json is copied into the package root by
 * scripts/sync_package_data.py (the same script that copies it into the
 * Python package) — see package.json's "files" field, which ships it
 * alongside dist/ when published.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { FrameworkSchema, type Framework } from "./entities.js";

const THIS_DIR = dirname(fileURLToPath(import.meta.url));
// This file compiles to dist/domain/loader.js — two directories up from
// there is the package root, where framework.json lives alongside dist/.
const DEFAULT_FRAMEWORK_PATH = join(THIS_DIR, "..", "..", "framework.json");

export function loadFramework(path: string = DEFAULT_FRAMEWORK_PATH): Framework {
  const raw = readFileSync(path, "utf-8");
  const parsed: unknown = JSON.parse(raw);
  return FrameworkSchema.parse(parsed);
}

let cached: Framework | undefined;

/**
 * Process-wide cached singleton, mirroring loader.py's `framework()`.
 * framework.json doesn't change during a run, and re-parsing +
 * re-validating it on every tool call is wasted work across many
 * use-case invocations in a single triage session.
 */
export function framework(): Framework {
  cached ??= loadFramework();
  return cached;
}

/** Test-only escape hatch — clears the cache so tests can load a
 * mutated framework without process-level state leaking between them. */
export function _resetFrameworkCacheForTests(): void {
  cached = undefined;
}
