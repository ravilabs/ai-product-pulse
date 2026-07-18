import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

import {
  FrameworkSchema,
  getLayer,
  getMaturityLabel,
  getVerdictRule,
} from "../src/domain/entities.js";
import { framework, loadFramework } from "../src/domain/loader.js";

describe("framework.json loading", () => {
  it("loads and validates the real framework.json", () => {
    const fw = framework();
    expect(fw.framework_id).toBe("ai-product-pulse");
    expect(fw.layers.map((l) => l.id).sort()).toEqual([
      "business_outcome",
      "model_performance",
      "product_behaviour",
    ]);
    expect(fw.verdicts).toHaveLength(5);
    expect(fw.maturity_ladder).toHaveLength(5);
  });

  it("maturity label lookup matches the maturity ladder", () => {
    const fw = loadFramework();
    expect(getMaturityLabel(fw, 1)).toBe("No Tracking");
    expect(getMaturityLabel(fw, 5)).toBe("Closed-Loop");
    expect(() => getMaturityLabel(fw, 6)).toThrow();
  });

  it("override_rate carries a risk threshold", () => {
    const fw = loadFramework();
    const layer = getLayer(fw, "product_behaviour");
    const overrideRate = layer.indicators.find((i) => i.id === "override_rate");
    expect(overrideRate?.risk_threshold?.value).toBe(40);
  });

  it("verdict lookup finds trust_failure_signal", () => {
    const fw = loadFramework();
    expect(getVerdictRule(fw, "trust_failure_signal").severity).toBe("high");
  });
});

// ── negative cases: validators must actually be able to fail ───────────
// Mirrors test_domain.py's philosophy exactly: a validator nobody's
// shown capable of failing isn't proven to be checking anything.

function loadRawFramework(): Record<string, unknown> {
  const raw = readFileSync(new URL("../framework.json", import.meta.url), "utf-8");
  return JSON.parse(raw) as Record<string, unknown>;
}

describe("framework.json validators actually fail when they should", () => {
  it("rejects weights that don't sum to 1.0", () => {
    const raw = loadRawFramework();
    const scoring = raw.scoring as Record<string, unknown>;
    const overallScore = scoring.overall_score as Record<string, unknown>;
    const weights = { ...(overallScore.weights as Record<string, number>) };
    weights.business_outcome = 0.9; // now sums to ~1.57
    overallScore.weights = weights;

    const result = FrameworkSchema.safeParse(raw);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues.some((i) => i.message.includes("must sum to 1.0"))).toBe(true);
    }
  });

  it("rejects a layer/weight key mismatch", () => {
    const raw = loadRawFramework();
    const scoring = raw.scoring as Record<string, unknown>;
    const overallScore = scoring.overall_score as Record<string, unknown>;
    const weights = { ...(overallScore.weights as Record<string, number>) };
    const businessOutcomeWeight = weights.business_outcome;
    if (typeof businessOutcomeWeight !== "number") {
      throw new Error("expected business_outcome weight to be present in the real framework.json");
    }
    delete weights.business_outcome;
    weights.a_typo_layer_name = businessOutcomeWeight;
    overallScore.weights = weights;

    const result = FrameworkSchema.safeParse(raw);
    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.error.issues.some((i) => i.message.includes("don't match layer ids"))).toBe(true);
    }
  });
});

describe("cached singleton", () => {
  it("framework() returns the same validated object on repeated calls", () => {
    const a = framework();
    const b = framework();
    expect(a).toBe(b); // reference equality — proves it's cached, not re-parsed
  });
});

describe("packaged framework.json matches the repo-root source", () => {
  it("is byte-identical to the repo root, catching drift from scripts/sync_package_data.py", () => {
    const repoRootSource = readFileSync(new URL("../../../framework.json", import.meta.url));
    const packagedCopy = readFileSync(new URL("../framework.json", import.meta.url));
    expect(packagedCopy.equals(repoRootSource)).toBe(true);
  });
});
