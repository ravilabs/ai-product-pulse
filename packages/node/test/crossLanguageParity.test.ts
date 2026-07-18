/**
 * Cross-language parity test. Runs a fixed set of scenarios through the
 * TypeScript scoring engine directly, and through the real Python CLI
 * as a subprocess — same framework.json, same inputs — and compares the
 * deterministic parts of the output. This is the actual proof the port
 * is faithful, not just structurally similar; a port that merely reads
 * like the Python source could still diverge in behavior, and this is
 * the test that would catch it.
 *
 * Requires the Python package to be present at ../python relative to
 * this package, with its dependencies installed (see
 * packages/python/pyproject.toml). Skips with a clear message if it
 * can't find a working `python3`, rather than failing CI for an
 * unrelated environment reason.
 */
import { execFileSync } from "node:child_process";
import { existsSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it, afterAll, beforeAll } from "vitest";

import type { IndicatorEvidence } from "../src/domain/entities.js";
import { framework } from "../src/domain/loader.js";
import { applyRiskThresholds, computeMaturityLevel, computeOverallScore, evaluateVerdicts } from "../src/domain/scoringEngine.js";

const THIS_DIR = fileURLToPath(new URL(".", import.meta.url));
const PYTHON_SRC = join(THIS_DIR, "..", "..", "python", "src");
const PYTHON_AVAILABLE = existsSync(PYTHON_SRC);

interface Scenario {
  name: string;
  scores: { model_performance: number; product_behaviour: number; business_outcome: number };
  overrideRateValue?: number;
}

const SCENARIOS: Scenario[] = [
  { name: "balanced", scores: { model_performance: 3, product_behaviour: 3, business_outcome: 3 } },
  {
    name: "business_outcome_orphaned",
    scores: { model_performance: 4, product_behaviour: 4, business_outcome: 1 },
  },
  {
    name: "trust_failure_signal",
    scores: { model_performance: 4, product_behaviour: 2, business_outcome: 3 },
    overrideRateValue: 46.0,
  },
  {
    name: "trust_failure_signal_below_threshold",
    scores: { model_performance: 4, product_behaviour: 2, business_outcome: 3 },
    overrideRateValue: 25.0,
  },
  { name: "vanity_metric_risk", scores: { model_performance: 5, product_behaviour: 2, business_outcome: 2 } },
  {
    name: "two_blind_spots",
    scores: { model_performance: 1, product_behaviour: 1, business_outcome: 3 },
  },
  { name: "all_blind", scores: { model_performance: 1, product_behaviour: 1, business_outcome: 1 } },
  { name: "all_perfect", scores: { model_performance: 5, product_behaviour: 5, business_outcome: 5 } },
];

interface ComparableResult {
  overallScore: number;
  maturityLevel: number;
  verdictPairs: string[]; // "verdict_id::layer_id" sorted, layer_id "-" if absent
}

function computeViaTypeScript(scenario: Scenario): ComparableResult {
  const fw = framework();
  const scores = new Map(Object.entries(scenario.scores));
  const evidence = new Map<string, IndicatorEvidence>();
  if (scenario.overrideRateValue !== undefined) {
    evidence.set("override_rate", {
      indicator_id: "override_rate",
      tracked: true,
      value: scenario.overrideRateValue,
    });
  }
  applyRiskThresholds(fw, evidence);
  const verdicts = evaluateVerdicts(fw, scores, evidence);

  return {
    overallScore: computeOverallScore(fw, scores),
    maturityLevel: computeMaturityLevel(scores),
    verdictPairs: verdicts.map((v) => `${v.verdict_id}::${v.layer_id ?? "-"}`).sort(),
  };
}

function computeViaPython(scenario: Scenario, tmpDir: string): ComparableResult {
  const evidence = scenario.overrideRateValue !== undefined
    ? [{ indicator_id: "override_rate", tracked: true, value: scenario.overrideRateValue }]
    : [];

  const input = {
    subject_name: scenario.name,
    layers: [
      {
        layer_id: "model_performance",
        score: scenario.scores.model_performance,
        evidence_summary: "parity test",
        indicators: [],
      },
      {
        layer_id: "product_behaviour",
        score: scenario.scores.product_behaviour,
        evidence_summary: "parity test",
        indicators: evidence,
      },
      {
        layer_id: "business_outcome",
        score: scenario.scores.business_outcome,
        evidence_summary: "parity test",
        indicators: [],
      },
    ],
  };

  const inputPath = join(tmpDir, `${scenario.name}.json`);
  writeFileSync(inputPath, JSON.stringify(input));

  const stdout = execFileSync(
    "python3",
    ["-m", "ai_product_pulse.adapters.inbound.cli", "triage", "--input", inputPath],
    { env: { ...process.env, PYTHONPATH: PYTHON_SRC }, encoding: "utf-8" },
  );
  const report = JSON.parse(stdout) as {
    overall_score: number;
    maturity_level: number;
    verdicts: { verdict_id: string; layer_id: string | null }[];
  };

  return {
    overallScore: report.overall_score,
    maturityLevel: report.maturity_level,
    verdictPairs: report.verdicts.map((v) => `${v.verdict_id}::${v.layer_id ?? "-"}`).sort(),
  };
}

describe.skipIf(!PYTHON_AVAILABLE)("cross-language parity: TypeScript vs. Python", () => {
  let tmpDir: string;

  beforeAll(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "ai-product-pulse-parity-"));
  });

  afterAll(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  for (const scenario of SCENARIOS) {
    it(`matches for scenario: ${scenario.name}`, () => {
      const tsResult = computeViaTypeScript(scenario);
      const pyResult = computeViaPython(scenario, tmpDir);

      expect(tsResult.overallScore).toBe(pyResult.overallScore);
      expect(tsResult.maturityLevel).toBe(pyResult.maturityLevel);
      expect(tsResult.verdictPairs).toEqual(pyResult.verdictPairs);
    });
  }
});

if (!PYTHON_AVAILABLE) {
  describe("cross-language parity", () => {
    it.skip(`skipped — Python package not found at ${PYTHON_SRC}`, () => {
      // Intentionally empty: this test exists only to make the skip
      // reason visible in test output, not to assert anything.
    });
  });
}

// ── use-case-level parity: triage / aggregate / regression_diff ────────
// The scenario tests above prove the scoring engine matches. These prove
// the full use-case layer built on top of it — validation, report
// assembly, aggregation, and diffing — also matches end to end.

describe.skipIf(!PYTHON_AVAILABLE)("cross-language parity: use cases", () => {
  let tmpDir: string;

  beforeAll(() => {
    tmpDir = mkdtempSync(join(tmpdir(), "ai-product-pulse-usecase-parity-"));
  });

  afterAll(() => {
    rmSync(tmpDir, { recursive: true, force: true });
  });

  function pythonTriage(input: unknown, name: string): Record<string, unknown> {
    const inputPath = join(tmpDir, `${name}.json`);
    writeFileSync(inputPath, JSON.stringify(input));
    const stdout = execFileSync(
      "python3",
      ["-m", "ai_product_pulse.adapters.inbound.cli", "triage", "--input", inputPath],
      { env: { ...process.env, PYTHONPATH: PYTHON_SRC }, encoding: "utf-8" },
    );
    return JSON.parse(stdout) as Record<string, unknown>;
  }

  function pythonAggregate(features: unknown[], subjectName: string, name: string): Record<string, unknown> {
    const inputPath = join(tmpDir, `${name}.json`);
    writeFileSync(inputPath, JSON.stringify({ subject_name: subjectName, features }));
    const stdout = execFileSync(
      "python3",
      ["-m", "ai_product_pulse.adapters.inbound.cli", "aggregate", "--input", inputPath],
      { env: { ...process.env, PYTHONPATH: PYTHON_SRC }, encoding: "utf-8" },
    );
    return JSON.parse(stdout) as Record<string, unknown>;
  }

  function pythonDiff(previous: unknown, current: unknown, name: string): Record<string, unknown> {
    const prevPath = join(tmpDir, `${name}-prev.json`);
    const curPath = join(tmpDir, `${name}-cur.json`);
    writeFileSync(prevPath, JSON.stringify(previous));
    writeFileSync(curPath, JSON.stringify(current));
    const stdout = execFileSync(
      "python3",
      ["-m", "ai_product_pulse.adapters.inbound.cli", "diff", "--previous", prevPath, "--current", curPath],
      { env: { ...process.env, PYTHONPATH: PYTHON_SRC }, encoding: "utf-8" },
    );
    return JSON.parse(stdout) as Record<string, unknown>;
  }

  const ORPHANED_INPUT = {
    subject_name: "Parity Feature",
    layers: [
      { layer_id: "model_performance", score: 4, evidence_summary: "x", indicators: [] },
      {
        layer_id: "product_behaviour",
        score: 2,
        evidence_summary: "x",
        indicators: [{ indicator_id: "override_rate", tracked: true, value: 46.0 }],
      },
      { layer_id: "business_outcome", score: 1, evidence_summary: "x", indicators: [] },
    ],
  };

  it("triage: TS use case matches Python CLI output (deterministic fields)", async () => {
    const { triage } = await import("../src/usecases/triage.js");
    const tsReport = triage({
      subjectName: ORPHANED_INPUT.subject_name,
      layers: ORPHANED_INPUT.layers as never,
    });
    const pyReport = pythonTriage(ORPHANED_INPUT, "triage_parity");

    expect(tsReport.overall_score).toBe(pyReport.overall_score);
    expect(tsReport.maturity_level).toBe(pyReport.maturity_level);
    expect(new Set(tsReport.verdicts.map((v) => v.verdict_id))).toEqual(
      new Set((pyReport.verdicts as { verdict_id: string }[]).map((v) => v.verdict_id)),
    );
  });

  it("aggregate: TS use case matches Python CLI output", async () => {
    const { triage } = await import("../src/usecases/triage.js");
    const { aggregateProductPulse } = await import("../src/usecases/aggregateProductPulse.js");
    const { FeatureReportSchema } = await import("../src/domain/entities.js");

    const balancedInput = {
      subject_name: "Balanced Feature",
      layers: [
        { layer_id: "model_performance", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "product_behaviour", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "business_outcome", score: 3, evidence_summary: "x", indicators: [] },
      ],
    };

    const tsFeatureA = triage({ subjectName: ORPHANED_INPUT.subject_name, layers: ORPHANED_INPUT.layers as never });
    const tsFeatureB = triage({ subjectName: balancedInput.subject_name, layers: balancedInput.layers as never });
    const tsProduct = aggregateProductPulse({
      subjectName: "Parity Suite",
      features: [tsFeatureA, tsFeatureB],
    });

    const pyFeatureA = pythonTriage(ORPHANED_INPUT, "agg_a");
    const pyFeatureB = pythonTriage(balancedInput, "agg_b");
    const pyProduct = pythonAggregate(
      [pyFeatureA, pyFeatureB].map((f) => FeatureReportSchema.parse(f)),
      "Parity Suite",
      "agg_product",
    );

    expect(tsProduct.product_overall_score).toBe(pyProduct.product_overall_score);
    expect(tsProduct.product_maturity_level).toBe(pyProduct.product_maturity_level);
    expect(tsProduct.verdict_rollup.length).toBe((pyProduct.verdict_rollup as unknown[]).length);
  });

  it("diff: TS use case matches Python CLI output", async () => {
    const { triage } = await import("../src/usecases/triage.js");
    const { regressionDiff } = await import("../src/usecases/regressionDiff.js");

    const fixedInput = {
      subject_name: ORPHANED_INPUT.subject_name,
      layers: [
        ORPHANED_INPUT.layers[0],
        ORPHANED_INPUT.layers[1],
        { layer_id: "business_outcome", score: 3, evidence_summary: "Fixed.", indicators: [] },
      ],
    };

    const tsPrevious = {
      ...triage({ subjectName: ORPHANED_INPUT.subject_name, layers: ORPHANED_INPUT.layers as never }),
      generated_at: "2026-01-01T00:00:00Z",
    };
    const tsCurrent = {
      ...triage({ subjectName: fixedInput.subject_name, layers: fixedInput.layers as never }),
      generated_at: "2026-06-01T00:00:00Z",
    };
    const tsDiff = regressionDiff({ previous: tsPrevious, current: tsCurrent });

    const pyPreviousRaw = pythonTriage(ORPHANED_INPUT, "diff_prev");
    pyPreviousRaw.generated_at = "2026-01-01T00:00:00Z";
    const pyCurrentRaw = pythonTriage(fixedInput, "diff_cur");
    pyCurrentRaw.generated_at = "2026-06-01T00:00:00Z";
    const pyDiff = pythonDiff(pyPreviousRaw, pyCurrentRaw, "diff_result");

    expect(tsDiff.summary).toBe(pyDiff.summary);
    expect(tsDiff.overall_score_delta).toBe(pyDiff.overall_score_delta);
    expect(tsDiff.maturity_level_delta).toBe(pyDiff.maturity_level_delta);
    expect(new Set(tsDiff.verdicts_resolved.map((v) => v.verdict_id))).toEqual(
      new Set((pyDiff.verdicts_resolved as { verdict_id: string }[]).map((v) => v.verdict_id)),
    );
  });
});
