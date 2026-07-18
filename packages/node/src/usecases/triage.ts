/**
 * triage — the primary use case. Direct port of usecases/triage.py.
 * Takes what the calling agent already assessed (a 1-5 score per layer,
 * judged against the maturity_ladder, plus whatever indicator evidence
 * it found) and returns a validated FeatureReport.
 *
 * Kept structurally parallel to triage.py on purpose, same as
 * scoringEngine.ts — anyone debugging a cross-language parity mismatch
 * should be able to read the two side by side.
 */
import { z } from "zod";

import {
  IndicatorEvidenceSchema,
  LayerIdSchema,
  LayerResultSchema,
  getLayer,
  getMaturityLabel,
  newReportId,
  nowIso,
  type FeatureReport,
  type Framework,
  type IndicatorEvidence,
} from "../domain/entities.js";
import { framework as defaultFramework } from "../domain/loader.js";
import {
  applyRiskThresholds,
  computeMaturityLevel,
  computeOverallScore,
  evaluateVerdicts,
} from "../domain/scoringEngine.js";

/**
 * What the calling agent provides for one layer, after reviewing
 * whatever evidence the user gave it. score is the agent's judgment
 * against framework.json's maturity_ladder — the one place in the whole
 * pipeline that isn't deterministic, by design.
 */
export const LayerInputSchema = z.object({
  layer_id: LayerIdSchema,
  score: z.number().int().min(1).max(5),
  evidence_summary: z.string(),
  indicators: z.array(IndicatorEvidenceSchema).default([]),
});
export type LayerInput = z.infer<typeof LayerInputSchema>;

export interface TriageOptions {
  subjectName: string;
  layers: LayerInput[];
  subjectDescription?: string | undefined;
  generatedByHarness?: string | undefined;
  vanityMetricFlags?: string[] | undefined;
  recommendations?: string | undefined;
  fw?: Framework;
}

function rejectWrongLayerSet(fw: Framework, layers: LayerInput[]): void {
  const expected = new Set(fw.layers.map((l) => l.id));
  const provided = layers.map((li) => li.layer_id);

  if (new Set(provided).size !== provided.length) {
    throw new Error(`triage() received a duplicate layer_id: ${JSON.stringify(provided)}`);
  }

  const providedSet = new Set(provided);
  const sameSize = providedSet.size === expected.size;
  const sameMembers = sameSize && [...providedSet].every((id) => expected.has(id));
  if (!sameMembers) {
    const missing = [...expected].filter((id) => !providedSet.has(id)).sort();
    const unexpected = [...providedSet].filter((id) => !expected.has(id)).sort();
    throw new Error(
      `triage() requires exactly the three Triangle layers ${JSON.stringify([...expected].sort())}. ` +
        `Missing: ${missing.length ? JSON.stringify(missing) : "none"}. ` +
        `Unexpected: ${unexpected.length ? JSON.stringify(unexpected) : "none"}.`,
    );
  }
}

function rejectUnknownIndicatorIds(fw: Framework, layers: LayerInput[]): void {
  for (const li of layers) {
    const layerDef = getLayer(fw, li.layer_id);
    const validIndicatorIds = new Set(layerDef.indicators.map((ind: { id: string }) => ind.id));
    for (const evidence of li.indicators) {
      if (!validIndicatorIds.has(evidence.indicator_id)) {
        throw new Error(
          `Indicator '${evidence.indicator_id}' is not defined on layer '${li.layer_id}'. ` +
            `Valid indicators there: ${JSON.stringify([...validIndicatorIds].sort())}`,
        );
      }
    }
  }
}

function validateLayers(fw: Framework, layers: LayerInput[]): void {
  rejectWrongLayerSet(fw, layers);
  rejectUnknownIndicatorIds(fw, layers);
}

function validateVanityFlags(fw: Framework, flags: string[]): void {
  const validIds = new Set(fw.vanity_metric_probes.map((p) => p.id));
  const unknown = flags.filter((f) => !validIds.has(f));
  if (unknown.length > 0) {
    throw new Error(
      `Unknown vanity_metric_probe id(s): ${JSON.stringify(unknown)}. ` +
        `Valid probes: ${JSON.stringify([...validIds].sort())}`,
    );
  }
}

export function triage(options: TriageOptions): FeatureReport {
  const fw = options.fw ?? defaultFramework();
  const layers = options.layers.map((l) => LayerInputSchema.parse(l));
  const vanityMetricFlags = options.vanityMetricFlags ?? [];

  validateLayers(fw, layers);
  validateVanityFlags(fw, vanityMetricFlags);

  const layerScores = new Map(layers.map((li) => [li.layer_id, li.score] as const));
  const indicatorEvidence = new Map<string, IndicatorEvidence>(
    layers.flatMap((li) => li.indicators.map((ev) => [ev.indicator_id, ev] as const)),
  );

  applyRiskThresholds(fw, indicatorEvidence);

  const layerResults = layers.map((li) =>
    LayerResultSchema.parse({
      layer_id: li.layer_id,
      score: li.score,
      maturity_label: getMaturityLabel(fw, li.score),
      indicators: li.indicators,
      evidence_summary: li.evidence_summary,
    }),
  );

  const report: FeatureReport = {
    report_id: newReportId(),
    framework_id: "ai-product-pulse",
    framework_version: fw.version,
    unit_of_assessment: "feature",
    subject_name: options.subjectName,
    subject_description: options.subjectDescription ?? null,
    generated_at: nowIso(),
    generated_by_harness: options.generatedByHarness ?? null,
    layers: layerResults,
    overall_score: computeOverallScore(fw, layerScores),
    maturity_level: computeMaturityLevel(layerScores),
    verdicts: evaluateVerdicts(fw, layerScores, indicatorEvidence),
    vanity_metric_flags: vanityMetricFlags,
    recommendations: options.recommendations ?? null,
  };

  return report;
}
