import { describe, expect, it } from "vitest";

import { framework } from "../src/domain/loader.js";
import { aggregateProductPulse } from "../src/usecases/aggregateProductPulse.js";
import { triage, type LayerInput } from "../src/usecases/triage.js";

const fw = framework();

function feature(name: string, mp: number, pb: number, bo: number) {
  const layers: LayerInput[] = [
    { layer_id: "model_performance", score: mp, evidence_summary: "x", indicators: [] },
    { layer_id: "product_behaviour", score: pb, evidence_summary: "x", indicators: [] },
    { layer_id: "business_outcome", score: bo, evidence_summary: "x", indicators: [] },
  ];
  return triage({ subjectName: name, layers, fw });
}

describe("product_maturity_level", () => {
  it("is the minimum across features, not the average", () => {
    const strong = feature("Search", 5, 4, 4);
    const weak = feature("Tagging", 1, 3, 3);
    const product = aggregateProductPulse({ subjectName: "Core AI Suite", features: [strong, weak], fw });
    expect(product.product_maturity_level).toBe(1);
  });
});

describe("product_overall_score", () => {
  it("is the flat mean across features", () => {
    const a = feature("A", 5, 5, 5);
    const b = feature("B", 1, 1, 1);
    const product = aggregateProductPulse({ subjectName: "Suite", features: [a, b], fw });
    expect(product.product_overall_score).toBeCloseTo(3.0, 2);
  });
});

describe("verdict_rollup", () => {
  it("preserves every verdict attributed to its feature", () => {
    const orphaned = feature("Orphaned Feature", 4, 4, 1);
    const balanced = feature("Balanced Feature", 3, 3, 3);
    const product = aggregateProductPulse({ subjectName: "Suite", features: [orphaned, balanced], fw });

    expect(product.verdict_rollup).toHaveLength(orphaned.verdicts.length + balanced.verdicts.length);

    const orphanedEntries = product.verdict_rollup.filter((v) => v.verdict_id === "business_outcome_orphaned");
    expect(orphanedEntries).toHaveLength(1);
    expect(orphanedEntries[0]?.feature_name).toBe("Orphaned Feature");

    const balancedEntries = product.verdict_rollup.filter((v) => v.verdict_id === "balanced");
    expect(balancedEntries).toHaveLength(1);
    expect(balancedEntries[0]?.feature_name).toBe("Balanced Feature");
  });

  it("does not hide one bad feature behind good ones", () => {
    const good = [feature("Good 0", 4, 4, 4), feature("Good 1", 4, 4, 4), feature("Good 2", 4, 4, 4)];
    const bad = feature("Bad", 4, 4, 1);
    const product = aggregateProductPulse({ subjectName: "Suite", features: [...good, bad], fw });
    expect(
      product.verdict_rollup.some((v) => v.verdict_id === "business_outcome_orphaned" && v.feature_name === "Bad"),
    ).toBe(true);
  });
});

describe("guardrails", () => {
  it("requires at least two features", () => {
    const single = feature("Only Feature", 3, 3, 3);
    expect(() => aggregateProductPulse({ subjectName: "Suite", features: [single], fw })).toThrow(/at least two/);
  });

  it("rejects mismatched framework versions", () => {
    const a = feature("A", 3, 3, 3);
    const b = { ...feature("B", 3, 3, 3), framework_version: "0.0.9-fake" };
    expect(() => aggregateProductPulse({ subjectName: "Suite", features: [a, b], fw })).toThrow(
      /same framework_version/,
    );
  });

  it("rejects duplicate feature names", () => {
    const a = feature("Same Name", 3, 3, 3);
    const b = feature("Same Name", 4, 4, 4);
    expect(() => aggregateProductPulse({ subjectName: "Suite", features: [a, b], fw })).toThrow(/unique/);
  });
});
