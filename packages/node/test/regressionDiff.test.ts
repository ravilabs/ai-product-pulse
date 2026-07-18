import { describe, expect, it } from "vitest";

import type { FeatureReport, IndicatorEvidence } from "../src/domain/entities.js";
import { framework } from "../src/domain/loader.js";
import { regressionDiff } from "../src/usecases/regressionDiff.js";
import { triage, type LayerInput } from "../src/usecases/triage.js";

const fw = framework();
const T0 = "2026-01-01T00:00:00Z";
const T1 = "2026-04-01T00:00:00Z";

function feature(
  name: string,
  mp: number,
  pb: number,
  bo: number,
  at: string,
  pbIndicators: IndicatorEvidence[] = [],
): FeatureReport {
  const layers: LayerInput[] = [
    { layer_id: "model_performance", score: mp, evidence_summary: "x", indicators: [] },
    { layer_id: "product_behaviour", score: pb, evidence_summary: "x", indicators: pbIndicators },
    { layer_id: "business_outcome", score: bo, evidence_summary: "x", indicators: [] },
  ];
  const report = triage({ subjectName: name, layers, fw });
  return { ...report, generated_at: at };
}

describe("classification", () => {
  it("improved when a verdict resolves with none introduced (accounting for balanced)", () => {
    const previous = feature("Search", 4, 4, 1, T0); // business_outcome_orphaned
    const current = feature("Search", 4, 4, 3, T1); // fixed, and now balanced too
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("improved");
    expect(diff.verdicts_resolved.map((v) => v.verdict_id)).toEqual(["business_outcome_orphaned"]);
    // "balanced" is newly introduced too, but severity "none" — good
    // news, not a second kind of change that should make this "mixed".
    expect(diff.verdicts_introduced.map((v) => v.verdict_id)).toEqual(["balanced"]);
  });

  it("regressed when a verdict is introduced with none resolved", () => {
    const previous = feature("Search", 4, 4, 3, T0); // balanced
    const current = feature("Search", 4, 4, 1, T1); // now orphaned
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("regressed");
    expect(diff.verdicts_introduced.map((v) => v.verdict_id)).toContain("business_outcome_orphaned");
    // losing "balanced" is real, reportable output — just correctly
    // excluded from the classification math itself.
    expect(diff.verdicts_resolved.map((v) => v.verdict_id)).toEqual(["balanced"]);
  });

  it("mixed when one resolves and another is introduced", () => {
    const previous = feature("Search", 1, 4, 4, T0); // blind_spot: model_performance
    const current = feature("Search", 4, 1, 4, T1); // blind_spot: product_behaviour instead
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("mixed");
    expect(diff.verdicts_resolved).toHaveLength(1);
    expect(diff.verdicts_introduced).toHaveLength(1);
  });

  it("unchanged when nothing moves", () => {
    const previous = feature("Search", 3, 3, 3, T0);
    const current = feature("Search", 3, 3, 3, T1);
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("unchanged");
    expect(diff.overall_score_delta).toBe(0);
    expect(diff.maturity_level_delta).toBe(0);
  });

  it("balanced newly firing does not get classified as mixed (regression test)", () => {
    const previous = feature("Search", 4, 4, 1, T0);
    const current = feature("Search", 4, 4, 3, T1);
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("improved");
    expect(diff.verdicts_introduced.some((v) => v.verdict_id === "balanced")).toBe(true);
  });

  it("improved on score movement even without a verdict set change", () => {
    const previous = feature("Search", 3, 3, 3, T0);
    const current = feature("Search", 4, 4, 4, T1);
    const diff = regressionDiff({ previous, current });
    expect(diff.summary).toBe("improved");
    expect(diff.verdicts_resolved).toHaveLength(0);
    expect(diff.verdicts_introduced).toHaveLength(0);
    expect(diff.overall_score_delta).toBeGreaterThan(0);
  });
});

describe("verdict identity across layers", () => {
  it("treats blind_spot on different layers as resolved+introduced, not persisting", () => {
    const previous = feature("Search", 1, 4, 4, T0);
    const current = feature("Search", 4, 1, 4, T1);
    const diff = regressionDiff({ previous, current });
    expect(diff.verdicts_resolved[0]?.layer_id).toBe("model_performance");
    expect(diff.verdicts_introduced[0]?.layer_id).toBe("product_behaviour");
    expect(diff.verdicts_persisting).toHaveLength(0);
  });
});

describe("layer-level detail", () => {
  it("reports correct deltas and maturity labels", () => {
    const previous = feature("Search", 2, 3, 1, T0);
    const current = feature("Search", 4, 3, 1, T1);
    const diff = regressionDiff({ previous, current });
    const mpChange = diff.layer_changes.find((c) => c.layer_id === "model_performance");
    expect(mpChange?.previous_score).toBe(2);
    expect(mpChange?.current_score).toBe(4);
    expect(mpChange?.delta).toBe(2);
    expect(mpChange?.previous_maturity_label).toBe("Ad Hoc");
    expect(mpChange?.current_maturity_label).toBe("Operationalized");

    const pbChange = diff.layer_changes.find((c) => c.layer_id === "product_behaviour");
    expect(pbChange?.delta).toBe(0);
  });
});

describe("guardrails", () => {
  it("rejects different subject names", () => {
    const previous = feature("Search", 3, 3, 3, T0);
    const current = feature("Summarizer", 3, 3, 3, T1);
    expect(() => regressionDiff({ previous, current })).toThrow(/same feature over time/);
  });

  it("rejects mismatched framework versions", () => {
    const previous = feature("Search", 3, 3, 3, T0);
    const current = { ...feature("Search", 3, 3, 3, T1), framework_version: "0.0.9-fake" };
    expect(() => regressionDiff({ previous, current })).toThrow(/same framework_version/);
  });

  it("rejects current earlier than previous", () => {
    const previous = feature("Search", 3, 3, 3, T1); // later timestamp
    const current = feature("Search", 4, 4, 4, T0); // earlier, passed as "current"
    expect(() => regressionDiff({ previous, current })).toThrow(/argument order/);
  });
});

describe("indicator-driven resolution", () => {
  it("trust_failure_signal can resolve via indicator evidence", () => {
    const previous = feature("Search", 4, 2, 3, T0, [
      { indicator_id: "override_rate", tracked: true, value: 46.0 },
    ]);
    const current = feature("Search", 4, 2, 3, T1, [
      { indicator_id: "override_rate", tracked: true, value: 15.0 },
    ]);
    const diff = regressionDiff({ previous, current });
    expect(diff.verdicts_resolved.some((v) => v.verdict_id === "trust_failure_signal")).toBe(true);
  });
});
