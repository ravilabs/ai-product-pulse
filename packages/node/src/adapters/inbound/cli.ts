#!/usr/bin/env node
/**
 * CLI adapter for AI Product Pulse. Mirrors the MCP server's three
 * tools exactly — triage, aggregate, and diff — because a harness with
 * no MCP support should get identical behavior through the command
 * line. All three adapters call the same use-case functions
 * underneath; none of them contains logic the others don't also go
 * through.
 *
 * Usage:
 *   ai-product-pulse triage --input evidence.json [--output report.json]
 *   ai-product-pulse aggregate --input features.json [--output report.json]
 *   ai-product-pulse diff --previous prev.json --current cur.json [--output diff.json]
 *
 * No external CLI framework dependency — node:util's parseArgs (stdlib
 * since Node 18.3) instead, matching cli.py's argparse-only philosophy.
 * parseArgs has no native subcommand concept, so the first positional
 * argument is dispatched manually before parsing the rest.
 */
import { readFileSync, realpathSync, writeFileSync } from "node:fs";
import { parseArgs } from "node:util";
import { fileURLToPath } from "node:url";

import { FeatureReportSchema } from "../../domain/entities.js";
import { aggregateProductPulse } from "../../usecases/aggregateProductPulse.js";
import { regressionDiff } from "../../usecases/regressionDiff.js";
import { LayerInputSchema, triage } from "../../usecases/triage.js";

function readInput(path: string | undefined): unknown {
  const raw = path ? readFileSync(path, "utf-8") : readFileSync(0, "utf-8"); // fd 0 = stdin
  return JSON.parse(raw);
}

function writeOutput(payload: unknown, path: string | undefined): void {
  const text = JSON.stringify(payload, null, 2);
  if (path) {
    writeFileSync(path, text + "\n", "utf-8");
  } else {
    process.stdout.write(text + "\n");
  }
}

function runTriage(args: string[]): number {
  const { values } = parseArgs({
    args,
    options: {
      input: { type: "string", short: "i" },
      output: { type: "string", short: "o" },
    },
  });

  try {
    const data = readInput(values.input) as Record<string, unknown>;
    const layers = (data.layers as unknown[]).map((l) => LayerInputSchema.parse(l));
    const report = triage({
      subjectName: data.subject_name as string,
      layers,
      subjectDescription: data.subject_description as string | undefined,
      generatedByHarness: (data.generated_by_harness as string | undefined) ?? "cli",
      vanityMetricFlags: data.vanity_metric_flags as string[] | undefined,
      recommendations: data.recommendations as string | undefined,
    });
    writeOutput(report, values.output);
    return 0;
  } catch (error) {
    process.stderr.write(`triage failed: ${String(error instanceof Error ? error.message : error)}\n`);
    return 1;
  }
}

function runAggregate(args: string[]): number {
  const { values } = parseArgs({
    args,
    options: {
      input: { type: "string", short: "i" },
      output: { type: "string", short: "o" },
    },
  });

  try {
    const data = readInput(values.input) as Record<string, unknown>;
    const features = (data.features as unknown[]).map((f) => FeatureReportSchema.parse(f));
    const report = aggregateProductPulse({
      subjectName: data.subject_name as string,
      features,
      subjectDescription: data.subject_description as string | undefined,
      generatedByHarness: (data.generated_by_harness as string | undefined) ?? "cli",
    });
    writeOutput(report, values.output);
    return 0;
  } catch (error) {
    process.stderr.write(`aggregate failed: ${String(error instanceof Error ? error.message : error)}\n`);
    return 1;
  }
}

function runDiff(args: string[]): number {
  const { values } = parseArgs({
    args,
    options: {
      previous: { type: "string" },
      current: { type: "string" },
      output: { type: "string", short: "o" },
    },
  });

  try {
    const previous = FeatureReportSchema.parse(readInput(values.previous));
    const current = FeatureReportSchema.parse(readInput(values.current));
    const diff = regressionDiff({ previous, current });
    writeOutput(diff, values.output);
    return 0;
  } catch (error) {
    process.stderr.write(`diff failed: ${String(error instanceof Error ? error.message : error)}\n`);
    return 1;
  }
}

export function main(argv: string[] = process.argv.slice(2)): number {
  const [command, ...rest] = argv;
  switch (command) {
    case "triage":
      return runTriage(rest);
    case "aggregate":
      return runAggregate(rest);
    case "diff":
      return runDiff(rest);
    default:
      process.stderr.write(
        `Usage: ai-product-pulse <triage|aggregate|diff> [options]\n` +
          `Got: ${command ?? "(no command)"}\n`,
      );
      return 1;
  }
}

/**
 * Detects whether this module is the process entry point, not just
 * imported (e.g. by a test). A naive `import.meta.url === file://${process.argv[1]}`
 * comparison — the common pattern for this — is broken for exactly the
 * case that matters most here: running the installed `ai-product-pulse`
 * bin command. npm installs bin entries as symlinks in node_modules/.bin,
 * so process.argv[1] reflects the path as invoked (through the symlink)
 * while import.meta.url reflects the resolved real file — they never
 * match as strings. Resolving both sides with realpathSync before
 * comparing fixes it. Confirmed by actually installing a packed tarball
 * and running the real bin symlink — the naive version silently did
 * nothing, no error, no output, exit code 0.
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
  process.exit(main());
}
