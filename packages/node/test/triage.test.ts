import { describe, expect, it } from "vitest";

import type { IndicatorEvidence } from "../src/domain/entities.js";
import { framework } from "../src/domain/loader.js";
import { triage, type LayerInput } from "../src/usecases/triage.js";

const fw = framework();

function layers(mp: number, pb: number, bo: number, pbIndicators: IndicatorEvidence[] = []): LayerInput[] {
  return [
    { layer_id: "model_performance", score: mp, evidence_summary: "x", indicators: [] },
    { layer_id: "product_behaviour", score: pb, evidence_summary: "x", indicators: pbIndicators },
    { layer_id: "business_outcome", score: bo, evidence_summary: "x", indicators: [] },
  ];
}

function verdictIds(report: ReturnType<typeof triage>): Set<string> {
  return new Set(report.verdicts.map((v) => v.verdict_id));
}

describe("balanced", () => {
  it("fires when all layers are at least instrumented", () => {
    const report = triage({ subjectName: "Feature", layers: layers(3, 3, 3), fw });
    expect(verdictIds(report).has("balanced")).toBe(true);
  });

  it("does not fire when one layer is below three", () => {
    const report = triage({ subjectName: "Feature", layers: layers(3, 3, 2), fw });
    expect(verdictIds(report).has("balanced")).toBe(false);
  });
});

describe("business_outcome_orphaned", () => {
  it("fires regardless of other layers", () => {
    const report = triage({ subjectName: "Feature", layers: layers(1, 1, 1), fw });
    expect(verdictIds(report).has("business_outcome_orphaned")).toBe(true);
  });
});

describe("blind_spot / business_outcome_orphaned exclusion (regression test)", () => {
  it("does not duplicate business_outcome_orphaned as a blind_spot", () => {
    const report = triage({ subjectName: "Feature", layers: layers(4, 4, 1), fw });
    expect(verdictIds(report).has("business_outcome_orphaned")).toBe(true);
    expect(
      report.verdicts.some((v) => v.verdict_id === "blind_spot" && v.layer_id === "business_outcome"),
    ).toBe(false);
  });

  it("still fires for model_performance, with the label rendered", () => {
    const report = triage({ subjectName: "Feature", layers: layers(1, 4, 4), fw });
    const blindSpots = report.verdicts.filter((v) => v.verdict_id === "blind_spot");
    expect(blindSpots).toHaveLength(1);
    expect(blindSpots[0]?.layer_id).toBe("model_performance");
    expect(blindSpots[0]?.message).toContain("Model Performance");
  });

  it("can fire twice for two untracked layers", () => {
    const report = triage({ subjectName: "Feature", layers: layers(1, 1, 3), fw });
    const blindSpotLayers = new Set(
      report.verdicts.filter((v) => v.verdict_id === "blind_spot").map((v) => v.layer_id),
    );
    expect(blindSpotLayers).toEqual(new Set(["model_performance", "product_behaviour"]));
  });

  it("does not fire if no other layer clears the bar", () => {
    const report = triage({ subjectName: "Feature", layers: layers(1, 1, 1), fw });
    expect(report.verdicts.some((v) => v.verdict_id === "blind_spot")).toBe(false);
  });
});

describe("trust_failure_signal", () => {
  it("fires on high performance + override_rate over threshold", () => {
    const report = triage({
      subjectName: "Feature",
      layers: layers(4, 2, 3, [{ indicator_id: "override_rate", tracked: true, value: 46.0 }]),
      fw,
    });
    expect(verdictIds(report).has("trust_failure_signal")).toBe(true);
    const pbLayer = report.layers.find((l) => l.layer_id === "product_behaviour");
    const overrideEvidence = pbLayer?.indicators.find((i) => i.indicator_id === "override_rate");
    expect(overrideEvidence?.risk_threshold_exceeded).toBe(true);
  });

  it("does not fire below the risk threshold", () => {
    const report = triage({
      subjectName: "Feature",
      layers: layers(4, 2, 3, [{ indicator_id: "override_rate", tracked: true, value: 25.0 }]),
      fw,
    });
    expect(verdictIds(report).has("trust_failure_signal")).toBe(false);
  });

  it("does not fire without evidence at all", () => {
    const report = triage({ subjectName: "Feature", layers: layers(4, 3, 3), fw });
    expect(verdictIds(report).has("trust_failure_signal")).toBe(false);
  });
});

describe("vanity_metric_risk", () => {
  it("fires on shallow outcome next to a strong layer", () => {
    const report = triage({ subjectName: "Feature", layers: layers(5, 2, 2), fw });
    expect(verdictIds(report).has("vanity_metric_risk")).toBe(true);
  });

  it("is distinct from orphaned", () => {
    const report = triage({ subjectName: "Feature", layers: layers(5, 5, 1), fw });
    const ids = verdictIds(report);
    expect(ids.has("business_outcome_orphaned")).toBe(true);
    expect(ids.has("vanity_metric_risk")).toBe(false);
  });
});

describe("validation", () => {
  it("rejects a missing layer", () => {
    expect(() =>
      triage({
        subjectName: "Feature",
        layers: [
          { layer_id: "model_performance", score: 3, evidence_summary: "x", indicators: [] },
          { layer_id: "product_behaviour", score: 3, evidence_summary: "x", indicators: [] },
        ],
        fw,
      }),
    ).toThrow(/requires exactly the three/);
  });

  it("rejects a duplicate layer", () => {
    expect(() =>
      triage({
        subjectName: "Feature",
        layers: [...layers(3, 3, 3), { layer_id: "model_performance", score: 4, evidence_summary: "x", indicators: [] }],
        fw,
      }),
    ).toThrow(/duplicate layer_id/);
  });

  it("rejects an unknown indicator id", () => {
    expect(() =>
      triage({
        subjectName: "Feature",
        layers: layers(3, 3, 3, [{ indicator_id: "totally_made_up", tracked: true }]),
        fw,
      }),
    ).toThrow(/not defined on layer/);
  });

  it("rejects an unknown vanity_metric_probe id", () => {
    expect(() =>
      triage({ subjectName: "Feature", layers: layers(3, 3, 3), vanityMetricFlags: ["not_real"], fw }),
    ).toThrow(/Unknown vanity_metric_probe/);
  });

  it("passes through a valid vanity_metric_flag", () => {
    const report = triage({
      subjectName: "Feature",
      layers: layers(3, 3, 3),
      vanityMetricFlags: ["internal_eval_as_business_outcome"],
      fw,
    });
    expect(report.vanity_metric_flags).toEqual(["internal_eval_as_business_outcome"]);
  });
});

describe("arithmetic", () => {
  it("overall_score is the weighted mean", () => {
    const report = triage({ subjectName: "Feature", layers: layers(4, 2, 1), fw });
    expect(report.overall_score).toBeGreaterThanOrEqual(2.33);
    expect(report.overall_score).toBeLessThanOrEqual(2.34);
  });

  it("maturity_level is the minimum, not the average", () => {
    const report = triage({ subjectName: "Feature", layers: layers(5, 5, 1), fw });
    expect(report.maturity_level).toBe(1);
  });
});
