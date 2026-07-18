import { describe, expect, it } from "vitest";

import type { IndicatorEvidence } from "../src/domain/entities.js";
import { framework } from "../src/domain/loader.js";
import {
  applyRiskThresholds,
  computeMaturityLevel,
  computeOverallScore,
  evaluateVerdicts,
} from "../src/domain/scoringEngine.js";

const fw = framework();

function layerScores(mp: number, pb: number, bo: number): Map<string, number> {
  return new Map([
    ["model_performance", mp],
    ["product_behaviour", pb],
    ["business_outcome", bo],
  ]);
}

function verdictIds(results: ReturnType<typeof evaluateVerdicts>): Set<string> {
  return new Set(results.map((v) => v.verdict_id));
}

describe("balanced", () => {
  it("fires when all layers are at least Instrumented", () => {
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(3, 3, 3), new Map()));
    expect(ids.has("balanced")).toBe(true);
  });

  it("does not fire when one layer is below 3", () => {
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(3, 3, 2), new Map()));
    expect(ids.has("balanced")).toBe(false);
  });
});

describe("business_outcome_orphaned", () => {
  it("fires on business_outcome == 1 regardless of other layers", () => {
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(1, 1, 1), new Map()));
    expect(ids.has("business_outcome_orphaned")).toBe(true);
  });
});

describe("blind_spot / business_outcome_orphaned exclusion (regression test)", () => {
  it("does not duplicate business_outcome_orphaned as a blind_spot", () => {
    const results = evaluateVerdicts(fw, layerScores(4, 4, 1), new Map());
    expect(verdictIds(results).has("business_outcome_orphaned")).toBe(true);
    expect(results.some((v) => v.verdict_id === "blind_spot" && v.layer_id === "business_outcome")).toBe(
      false,
    );
  });

  it("still fires blind_spot for model_performance", () => {
    const results = evaluateVerdicts(fw, layerScores(1, 4, 4), new Map());
    const blindSpots = results.filter((v) => v.verdict_id === "blind_spot");
    expect(blindSpots).toHaveLength(1);
    expect(blindSpots[0]?.layer_id).toBe("model_performance");
  });

  it("can fire twice for two untracked layers", () => {
    const results = evaluateVerdicts(fw, layerScores(1, 1, 3), new Map());
    const blindSpotLayers = new Set(
      results.filter((v) => v.verdict_id === "blind_spot").map((v) => v.layer_id),
    );
    expect(blindSpotLayers).toEqual(new Set(["model_performance", "product_behaviour"]));
  });
});

describe("trust_failure_signal", () => {
  it("fires on high model_performance + override_rate over threshold", () => {
    const evidence = new Map<string, IndicatorEvidence>([
      ["override_rate", { indicator_id: "override_rate", tracked: true, value: 46.0 }],
    ]);
    applyRiskThresholds(fw, evidence);
    expect(evidence.get("override_rate")?.risk_threshold_exceeded).toBe(true);

    const ids = verdictIds(evaluateVerdicts(fw, layerScores(4, 2, 3), evidence));
    expect(ids.has("trust_failure_signal")).toBe(true);
  });

  it("does not fire below the risk threshold", () => {
    const evidence = new Map<string, IndicatorEvidence>([
      ["override_rate", { indicator_id: "override_rate", tracked: true, value: 25.0 }],
    ]);
    applyRiskThresholds(fw, evidence);
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(4, 2, 3), evidence));
    expect(ids.has("trust_failure_signal")).toBe(false);
  });
});

describe("vanity_metric_risk", () => {
  it("fires on a shallow business_outcome next to a strong layer", () => {
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(5, 2, 2), new Map()));
    expect(ids.has("vanity_metric_risk")).toBe(true);
  });

  it("is distinct from business_outcome_orphaned (requires exactly 2, not 1)", () => {
    const ids = verdictIds(evaluateVerdicts(fw, layerScores(5, 5, 1), new Map()));
    expect(ids.has("business_outcome_orphaned")).toBe(true);
    expect(ids.has("vanity_metric_risk")).toBe(false);
  });
});

describe("overall score and maturity level arithmetic", () => {
  it("overall score is the weighted mean", () => {
    const score = computeOverallScore(fw, layerScores(4, 2, 1));
    expect(score).toBeGreaterThanOrEqual(2.33);
    expect(score).toBeLessThanOrEqual(2.34);
  });

  it("maturity level is the minimum, not the average", () => {
    expect(computeMaturityLevel(layerScores(5, 5, 1))).toBe(1);
  });
});
