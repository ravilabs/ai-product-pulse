#!/usr/bin/env node
/**
 * MCP server adapter for AI Product Pulse.
 *
 * This file's only job is translation: MCP tool call in, use-case
 * function call, JSON-serializable result out. No scoring logic, no
 * validation beyond what the use cases already do — if you're
 * debugging why a verdict did or didn't fire, look in
 * domain/scoringEngine.ts, not here.
 *
 * Run directly for stdio transport (what Claude Code / Cursor expect):
 *   node dist/adapters/inbound/mcpServer.js
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { z } from "zod";

import { FeatureReportSchema, type FeatureReport, type ProductReport, type RegressionDiffResult } from "../../domain/entities.js";
import { aggregateProductPulse } from "../../usecases/aggregateProductPulse.js";
import { regressionDiff } from "../../usecases/regressionDiff.js";
import { LayerInputSchema, triage } from "../../usecases/triage.js";

export const server = new McpServer(
  { name: "ai-product-pulse", version: "0.1.0" },
  {
    instructions:
      "Triage AI product features against the AI Product Pulse framework " +
      "(Model Performance / Product Behaviour / Business Outcome). Score " +
      "each layer 1-5 against the maturity_ladder in framework.json based " +
      "on evidence the user provides, then call triage. For a product " +
      "with multiple AI features, call triage once per feature, then " +
      "pass all the resulting reports into aggregate_product_pulse. To " +
      "check whether a feature improved since a prior triage, call " +
      "regression_diff with both reports.",
  },
);

function toJsonable(value: FeatureReport | ProductReport | RegressionDiffResult): {
  content: { type: "text"; text: string }[];
} {
  return { content: [{ type: "text", text: JSON.stringify(value) }] };
}

server.registerTool(
  "triage",
  {
    description:
      "Score one AI feature against the AI Product Pulse framework. Requires exactly three layers " +
      "(model_performance, product_behaviour, business_outcome), each with a 1-5 score assigned by " +
      "reading the maturity_ladder in framework.json and matching it against whatever evidence the " +
      "user gave you. Everything past that score (maturity labels, overall_score, maturity_level, " +
      "which verdicts fire) is computed deterministically, not re-judged by you.",
    inputSchema: {
      subject_name: z.string().describe("Name of the AI feature being scored, e.g. 'AI Search Assistant'."),
      layers: z
        .array(LayerInputSchema)
        .describe("Exactly three entries, one each for model_performance, product_behaviour, and business_outcome."),
      subject_description: z.string().optional().describe("Optional free-text context about the feature."),
      generated_by_harness: z
        .string()
        .optional()
        .describe("Which harness produced this report, e.g. 'claude-code'. Used for harness-invariance comparisons."),
      vanity_metric_flags: z
        .array(z.string())
        .optional()
        .describe(
          "IDs of any vanity_metric_probes from framework.json that matched the evidence — see " +
            "framework.json's vanity_metric_probes list for valid IDs.",
        ),
      recommendations: z
        .string()
        .optional()
        .describe("Optional free-text next-step recommendations, not part of the deterministic scoring."),
    },
  },
  (args) => {
    const report = triage({
      subjectName: args.subject_name,
      layers: args.layers,
      subjectDescription: args.subject_description,
      generatedByHarness: args.generated_by_harness,
      vanityMetricFlags: args.vanity_metric_flags,
      recommendations: args.recommendations,
    });
    return toJsonable(report);
  },
);

server.registerTool(
  "aggregate_product_pulse",
  {
    description:
      "Roll up two or more feature-level triage results into one product-level pulse. Pass in the " +
      "full FeatureReport objects triage returned — this tool holds no state between calls, so it " +
      "needs all of them at once. Verdicts are never blended: every verdict from every feature " +
      "survives in the rollup, attributed to the feature that triggered it.",
    inputSchema: {
      subject_name: z.string().describe("Name of the product these features belong to, e.g. 'Core AI Suite'."),
      features: z
        .array(FeatureReportSchema)
        .describe(
          "Two or more FeatureReport objects, each previously returned by triage. Must share the " +
            "same framework_version and have unique subject_name values.",
        ),
      subject_description: z.string().optional().describe("Optional free-text context about the product."),
      generated_by_harness: z.string().optional().describe("Which harness produced this rollup, e.g. 'claude-code'."),
    },
  },
  (args) => {
    const report = aggregateProductPulse({
      subjectName: args.subject_name,
      features: args.features,
      subjectDescription: args.subject_description,
      generatedByHarness: args.generated_by_harness,
    });
    return toJsonable(report);
  },
);

server.registerTool(
  "regression_diff",
  {
    description:
      "Compares two triage reports for the same feature over time — answers whether a previously " +
      "flagged gap actually got fixed. Both reports must share subject_name and framework_version. " +
      "Returns which verdicts resolved, which are newly introduced, which persist, the per-layer " +
      "score deltas, and an overall improved/regressed/mixed/unchanged classification.",
    inputSchema: {
      previous: FeatureReportSchema.describe("The earlier FeatureReport, previously returned by triage."),
      current: FeatureReportSchema.describe(
        "The later FeatureReport for the same feature, previously returned by triage. Must be " +
          "chronologically after previous.",
      ),
    },
  },
  (args) => {
    const diff = regressionDiff({ previous: args.previous, current: args.current });
    return toJsonable(diff);
  },
);

export function main(): void {
  const transport = new StdioServerTransport();
  server.connect(transport).catch((error: unknown) => {
    process.stderr.write(`Failed to start MCP server: ${String(error)}\n`);
    process.exit(1);
  });
}

/**
 * See cli.ts's isRunningAsMainModule for why this can't be a naive
 * `import.meta.url === file://${process.argv[1]}` string comparison —
 * npm's bin symlinks break that exact check. Same fix here, since
 * ai-product-pulse-mcp is installed the identical way.
 */
function isRunningAsMainModule(): boolean {
  if (!process.argv[1]) return false;
  try {
    return fileURLToPath(import.meta.url) === realpathSync(process.argv[1]);
  } catch {
    return false;
  }
}

if (isRunningAsMainModule()) {
  main();
}
