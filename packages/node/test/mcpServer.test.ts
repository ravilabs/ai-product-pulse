import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

// Import the module fresh per test run isn't needed here — the server
// instance is a module-level singleton, same as the Python version's
// module-level `mcp` object. We import it directly rather than the
// `main()` entry point, which would try to attach a real stdio transport.
import { server } from "../src/adapters/inbound/mcpServer.js";

const TRIAGE_ARGS = {
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

let client: Client;

function extractJson(result: Awaited<ReturnType<Client["callTool"]>>): unknown {
  const content = result.content;
  if (!Array.isArray(content)) throw new Error("expected content array in tool result");
  const textBlock = content.find((c) => (c as { type?: string }).type === "text") as
    | { text: string }
    | undefined;
  if (!textBlock) throw new Error("no text block found in tool result content");
  return JSON.parse(textBlock.text) as unknown;
}

beforeEach(async () => {
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  client = new Client({ name: "test-client", version: "0.0.1" });
  await Promise.all([client.connect(clientTransport), server.connect(serverTransport)]);
});

afterEach(async () => {
  await client.close();
});

describe("server registration", () => {
  it("registers all three tools", async () => {
    const { tools } = await client.listTools();
    const names = new Set(tools.map((t) => t.name));
    expect(names).toEqual(new Set(["triage", "aggregate_product_pulse", "regression_diff"]));
  });

  it("triage's schema requires subject_name and layers", async () => {
    const { tools } = await client.listTools();
    const triageTool = tools.find((t) => t.name === "triage");
    const required = new Set(triageTool?.inputSchema.required ?? []);
    expect(required.has("subject_name")).toBe(true);
    expect(required.has("layers")).toBe(true);
  });
});

describe("triage tool", () => {
  it("produces a valid feature report through a real round trip", async () => {
    const result = await client.callTool({ name: "triage", arguments: TRIAGE_ARGS });
    const report = extractJson(result) as {
      unit_of_assessment: string;
      subject_name: string;
      verdicts: { verdict_id: string }[];
    };

    expect(report.unit_of_assessment).toBe("feature");
    expect(report.subject_name).toBe("AI Search Assistant");
    const verdictIds = new Set(report.verdicts.map((v) => v.verdict_id));
    expect(verdictIds.has("business_outcome_orphaned")).toBe(true);
    expect(verdictIds.has("trust_failure_signal")).toBe(true);
  });

  it("surfaces validation errors as a tool error, not a crash", async () => {
    const badArgs = { ...TRIAGE_ARGS, layers: TRIAGE_ARGS.layers.slice(0, 2) };
    const result = await client.callTool({ name: "triage", arguments: badArgs });
    expect(result.isError).toBe(true);
  });
});

describe("aggregate_product_pulse tool", () => {
  it("rolls up two triage results via real tool calls", async () => {
    const featureAResult = await client.callTool({ name: "triage", arguments: TRIAGE_ARGS });
    const featureA = extractJson(featureAResult) as Record<string, unknown>;

    const balancedArgs = {
      subject_name: "AI Summarizer",
      layers: [
        { layer_id: "model_performance", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "product_behaviour", score: 3, evidence_summary: "x", indicators: [] },
        { layer_id: "business_outcome", score: 3, evidence_summary: "x", indicators: [] },
      ],
    };
    const featureBResult = await client.callTool({ name: "triage", arguments: balancedArgs });
    const featureB = extractJson(featureBResult) as Record<string, unknown>;

    const productResult = await client.callTool({
      name: "aggregate_product_pulse",
      arguments: { subject_name: "Core AI Suite", features: [featureA, featureB] },
    });
    const product = extractJson(productResult) as {
      unit_of_assessment: string;
      product_maturity_level: number;
      features: unknown[];
    };

    expect(product.unit_of_assessment).toBe("product");
    expect(product.product_maturity_level).toBe(1);
    expect(product.features).toHaveLength(2);
  });
});

describe("regression_diff tool", () => {
  it("compares two triage results via real tool calls", async () => {
    const orphanedResult = await client.callTool({ name: "triage", arguments: TRIAGE_ARGS });
    const orphaned = extractJson(orphanedResult) as Record<string, unknown>;
    orphaned.generated_at = "2026-01-01T00:00:00Z";

    const fixedArgs = {
      ...TRIAGE_ARGS,
      layers: [
        TRIAGE_ARGS.layers[0],
        TRIAGE_ARGS.layers[1],
        { layer_id: "business_outcome", score: 3, evidence_summary: "Fixed.", indicators: [] },
      ],
    };
    const fixedResult = await client.callTool({ name: "triage", arguments: fixedArgs });
    const fixed = extractJson(fixedResult) as Record<string, unknown>;
    fixed.generated_at = "2026-06-01T00:00:00Z";

    const diffResult = await client.callTool({
      name: "regression_diff",
      arguments: { previous: orphaned, current: fixed },
    });
    const diff = extractJson(diffResult) as { summary: string; verdicts_resolved: { verdict_id: string }[] };

    expect(diff.summary).toBe("improved");
    expect(diff.verdicts_resolved.some((v) => v.verdict_id === "business_outcome_orphaned")).toBe(true);
  });
});
