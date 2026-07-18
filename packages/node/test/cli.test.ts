import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { main } from "../src/adapters/inbound/cli.js";

const TRIAGE_INPUT = {
  subject_name: "AI Search Assistant",
  layers: [
    {
      layer_id: "model_performance",
      score: 4,
      evidence_summary: "Tracked weekly.",
      indicators: [{ indicator_id: "task_success_rate", tracked: true, value: 91.2, unit: "percentage" }],
    },
    {
      layer_id: "product_behaviour",
      score: 2,
      evidence_summary: "Observed once, not systematic.",
      indicators: [{ indicator_id: "override_rate", tracked: true, value: 46.0 }],
    },
    {
      layer_id: "business_outcome",
      score: 1,
      evidence_summary: "No metric defined.",
      indicators: [{ indicator_id: "attributed_business_impact", tracked: false }],
    },
  ],
};

let tmpDir: string;

beforeEach(() => {
  tmpDir = mkdtempSync(join(tmpdir(), "ai-product-pulse-cli-"));
});

describe("triage", () => {
  it("reads from a file, writes to a file", () => {
    const inputPath = join(tmpDir, "evidence.json");
    const outputPath = join(tmpDir, "report.json");
    writeFileSync(inputPath, JSON.stringify(TRIAGE_INPUT));

    const exitCode = main(["triage", "--input", inputPath, "--output", outputPath]);

    expect(exitCode).toBe(0);
    const report = JSON.parse(readFileSync(outputPath, "utf-8")) as {
      subject_name: string;
      verdicts: { verdict_id: string }[];
      generated_by_harness: string;
    };
    expect(report.subject_name).toBe("AI Search Assistant");
    const verdictIds = new Set(report.verdicts.map((v) => v.verdict_id));
    expect(verdictIds.has("business_outcome_orphaned")).toBe(true);
    expect(verdictIds.has("trust_failure_signal")).toBe(true);
    expect(report.generated_by_harness).toBe("cli");
  });

  it("fails cleanly on a missing layer", () => {
    const broken = { ...TRIAGE_INPUT, layers: TRIAGE_INPUT.layers.slice(0, 2) };
    const inputPath = join(tmpDir, "evidence.json");
    writeFileSync(inputPath, JSON.stringify(broken));

    const stderrSpy = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exitCode = main(["triage", "--input", inputPath]);
    expect(exitCode).toBe(1);
    expect(stderrSpy.mock.calls.some((call) => String(call[0]).includes("triage failed"))).toBe(true);
    stderrSpy.mockRestore();
  });
});

describe("aggregate", () => {
  it("rolls up two chained triage outputs", () => {
    const inputA = join(tmpDir, "a.json");
    const reportA = join(tmpDir, "report_a.json");
    writeFileSync(inputA, JSON.stringify(TRIAGE_INPUT));
    expect(main(["triage", "--input", inputA, "--output", reportA])).toBe(0);

    const balancedInput = {
      subject_name: "AI Summarizer",
      layers: [
        { layer_id: "model_performance", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "product_behaviour", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "business_outcome", score: 3, evidence_summary: "x", indicators: [] },
      ],
    };
    const inputB = join(tmpDir, "b.json");
    const reportB = join(tmpDir, "report_b.json");
    writeFileSync(inputB, JSON.stringify(balancedInput));
    expect(main(["triage", "--input", inputB, "--output", reportB])).toBe(0);

    const featuresInput = join(tmpDir, "features.json");
    writeFileSync(
      featuresInput,
      JSON.stringify({
        subject_name: "Core AI Suite",
        features: [
          JSON.parse(readFileSync(reportA, "utf-8")) as unknown,
          JSON.parse(readFileSync(reportB, "utf-8")) as unknown,
        ],
      }),
    );
    const productOutput = join(tmpDir, "product.json");

    const exitCode = main(["aggregate", "--input", featuresInput, "--output", productOutput]);

    expect(exitCode).toBe(0);
    const product = JSON.parse(readFileSync(productOutput, "utf-8")) as {
      unit_of_assessment: string;
      product_maturity_level: number;
      features: unknown[];
    };
    expect(product.unit_of_assessment).toBe("product");
    expect(product.product_maturity_level).toBe(1);
    expect(product.features).toHaveLength(2);
  });

  it("fails cleanly on a single feature", () => {
    const inputA = join(tmpDir, "a.json");
    const reportA = join(tmpDir, "report_a.json");
    writeFileSync(inputA, JSON.stringify(TRIAGE_INPUT));
    main(["triage", "--input", inputA, "--output", reportA]);

    const featuresInput = join(tmpDir, "features.json");
    writeFileSync(
      featuresInput,
      JSON.stringify({ subject_name: "Suite", features: [JSON.parse(readFileSync(reportA, "utf-8")) as unknown] }),
    );

    const stderrSpy = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    const exitCode = main(["aggregate", "--input", featuresInput]);
    expect(exitCode).toBe(1);
    expect(stderrSpy.mock.calls.some((call) => String(call[0]).includes("aggregate failed"))).toBe(true);
    stderrSpy.mockRestore();
  });
});

describe("diff", () => {
  it("compares two chained triage outputs", () => {
    const orphanedInput = join(tmpDir, "orphaned.json");
    const orphanedReport = join(tmpDir, "orphaned_report.json");
    writeFileSync(orphanedInput, JSON.stringify(TRIAGE_INPUT));
    main(["triage", "--input", orphanedInput, "--output", orphanedReport]);
    const orphanedData = JSON.parse(readFileSync(orphanedReport, "utf-8")) as Record<string, unknown>;
    orphanedData.generated_at = "2026-01-01T00:00:00Z";
    writeFileSync(orphanedReport, JSON.stringify(orphanedData));

    const fixedInputData = {
      ...TRIAGE_INPUT,
      layers: [
        TRIAGE_INPUT.layers[0],
        TRIAGE_INPUT.layers[1],
        { layer_id: "business_outcome", score: 3, evidence_summary: "Fixed.", indicators: [] },
      ],
    };
    const fixedInput = join(tmpDir, "fixed.json");
    const fixedReport = join(tmpDir, "fixed_report.json");
    writeFileSync(fixedInput, JSON.stringify(fixedInputData));
    main(["triage", "--input", fixedInput, "--output", fixedReport]);
    const fixedData = JSON.parse(readFileSync(fixedReport, "utf-8")) as Record<string, unknown>;
    fixedData.generated_at = "2026-06-01T00:00:00Z";
    writeFileSync(fixedReport, JSON.stringify(fixedData));

    const diffOutput = join(tmpDir, "diff.json");
    const exitCode = main([
      "diff",
      "--previous",
      orphanedReport,
      "--current",
      fixedReport,
      "--output",
      diffOutput,
    ]);

    expect(exitCode).toBe(0);
    const diff = JSON.parse(readFileSync(diffOutput, "utf-8")) as {
      summary: string;
      verdicts_resolved: { verdict_id: string }[];
    };
    expect(diff.summary).toBe("improved");
    expect(diff.verdicts_resolved.some((v) => v.verdict_id === "business_outcome_orphaned")).toBe(true);
  });

  it("fails cleanly on out-of-order timestamps", () => {
    const laterInput = join(tmpDir, "later.json");
    const laterReport = join(tmpDir, "later_report.json");
    writeFileSync(laterInput, JSON.stringify(TRIAGE_INPUT));
    main(["triage", "--input", laterInput, "--output", laterReport]);
    const laterData = JSON.parse(readFileSync(laterReport, "utf-8")) as Record<string, unknown>;
    laterData.generated_at = "2026-06-01T00:00:00Z";
    writeFileSync(laterReport, JSON.stringify(laterData));

    const earlierInput = join(tmpDir, "earlier.json");
    const earlierReport = join(tmpDir, "earlier_report.json");
    writeFileSync(earlierInput, JSON.stringify(TRIAGE_INPUT));
    main(["triage", "--input", earlierInput, "--output", earlierReport]);
    const earlierData = JSON.parse(readFileSync(earlierReport, "utf-8")) as Record<string, unknown>;
    earlierData.generated_at = "2026-01-01T00:00:00Z";
    writeFileSync(earlierReport, JSON.stringify(earlierData));

    const stderrSpy = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    // later report passed as --previous, earlier as --current: backwards.
    const exitCode = main(["diff", "--previous", laterReport, "--current", earlierReport]);
    expect(exitCode).toBe(1);
    expect(stderrSpy.mock.calls.some((call) => String(call[0]).includes("diff failed"))).toBe(true);
    stderrSpy.mockRestore();
  });
});

describe("no command", () => {
  it("exits non-zero", () => {
    const stderrSpy = vi.spyOn(process.stderr, "write").mockImplementation(() => true);
    expect(main([])).toBe(1);
    stderrSpy.mockRestore();
  });
});

describe("real subprocess invocation", () => {
  it("works via the built dist/ output, exactly as a real user would run it", () => {
    const cliPath = fileURLToPath(new URL("../dist/adapters/inbound/cli.js", import.meta.url));
    const inputPath = join(tmpDir, "evidence.json");
    writeFileSync(inputPath, JSON.stringify(TRIAGE_INPUT));

    const stdout = execFileSync("node", [cliPath, "triage", "--input", inputPath], { encoding: "utf-8" });
    const report = JSON.parse(stdout) as { subject_name: string };
    expect(report.subject_name).toBe("AI Search Assistant");
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});
