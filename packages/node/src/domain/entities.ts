/**
 * Domain entities for AI Product Pulse — TypeScript port of
 * domain/entities.py in the Python package (the reference implementation).
 *
 * Field names are snake_case, not the usual TS-idiomatic camelCase. This
 * is deliberate: these types describe the same wire format the Python
 * package reads and writes — the same framework.json, the same
 * report.schema.json. Reshaping field names here would mean a
 * translation layer at every serialization boundary, which is exactly
 * the kind of place a cross-language parity bug would hide.
 *
 * Two families of type live here, same split as the Python source:
 *   1. Static framework concepts — the typed form of framework.json.
 *   2. Runtime report concepts — what a triage run actually produces.
 */
import { randomUUID } from "node:crypto";
import { z } from "zod";

export const SeveritySchema = z.enum(["none", "low", "medium", "high", "critical"]);
export type Severity = z.infer<typeof SeveritySchema>;

export const LayerIdSchema = z.enum(["model_performance", "product_behaviour", "business_outcome"]);
export type LayerId = z.infer<typeof LayerIdSchema>;

export const DirectionSchema = z.enum(["higher_is_better", "lower_is_better", "context_dependent"]);
export type Direction = z.infer<typeof DirectionSchema>;

// ─────────────────────────────────────────────────────────────────────────
// Static framework concepts — the typed form of framework.json
// ─────────────────────────────────────────────────────────────────────────

export const RiskThresholdSchema = z.object({
  operator: z.enum(["gte", "lte", "gt", "lt", "eq"]),
  value: z.number(),
  signal: z.string(),
  note: z.string().nullable().optional(),
});
export type RiskThreshold = z.infer<typeof RiskThresholdSchema>;

export const IndicatorSchema = z.object({
  id: z.string(),
  name: z.string(),
  description: z.string(),
  unit: z.string(),
  direction: DirectionSchema,
  applicable_if: z.string().nullable().optional(),
  risk_threshold: RiskThresholdSchema.nullable().optional(),
});
export type Indicator = z.infer<typeof IndicatorSchema>;

export const LayerSchema = z.object({
  id: LayerIdSchema,
  name: z.string(),
  order: z.number().int(),
  question: z.string(),
  indicators: z.array(IndicatorSchema),
});
export type Layer = z.infer<typeof LayerSchema>;

/** Mirrors Layer.indicator() in entities.py. */
export function findIndicator(layer: Layer, indicatorId: string): Indicator {
  const found = layer.indicators.find((i) => i.id === indicatorId);
  if (!found) {
    throw new Error(`No indicator '${indicatorId}' on layer '${layer.id}'`);
  }
  return found;
}

export const MaturityRungSchema = z.object({
  level: z.number().int().min(1).max(5),
  label: z.string(),
  description: z.string(),
});
export type MaturityRung = z.infer<typeof MaturityRungSchema>;

/**
 * Trigger shape varies by trigger_type (per_layer vs. global vs.
 * indicator-aware). Deliberately permissive — interpreting the trigger
 * is the rule evaluator's job (usecases/regressionDiff.ts,
 * domain/scoringEngine.ts), not this schema's. z.record mirrors
 * Pydantic's model_config = {"extra": "allow"}.
 */
export const VerdictTriggerSchema = z.record(z.string(), z.unknown());
export type VerdictTrigger = z.infer<typeof VerdictTriggerSchema>;

export const CrossReferenceSchema = z.object({
  framework: z.string(),
  author: z.string(),
  node_referenced: z.string(),
  relationship: z.string(),
});
export type CrossReference = z.infer<typeof CrossReferenceSchema>;

export const VerdictRuleSchema = z.object({
  id: z.string(),
  name: z.string(),
  priority: z.number().int(),
  severity: SeveritySchema,
  trigger_type: z.string(),
  trigger: VerdictTriggerSchema,
  trigger_description: z.string(),
  description: z.string(),
  label_template: z.string().nullable().optional(),
  cross_reference: CrossReferenceSchema.nullable().optional(),
});
export type VerdictRule = z.infer<typeof VerdictRuleSchema>;

export const VanityMetricProbeSchema = z.object({
  id: z.string(),
  pattern: z.string(),
  why_it_fails: z.string(),
  redirect_to: z.array(z.string()),
});
export type VanityMetricProbe = z.infer<typeof VanityMetricProbeSchema>;

export const OverallScoreConfigSchema = z
  .object({
    formula: z.string(),
    weights: z.record(z.string(), z.number()),
    weights_extensibility: z.string(),
    range: z.tuple([z.number().int(), z.number().int()]),
    purpose: z.string(),
  })
  .superRefine((val, ctx) => {
    const total = Object.values(val.weights).reduce((sum, w) => sum + w, 0);
    if (Math.abs(total - 1.0) > 1e-6) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message: `overall_score.weights must sum to 1.0, got ${String(total)}`,
      });
    }
  });
export type OverallScoreConfig = z.infer<typeof OverallScoreConfigSchema>;

export const MaturityLevelConfigSchema = z.object({
  formula: z.string(),
  range: z.tuple([z.number().int(), z.number().int()]),
  purpose: z.string(),
});
export type MaturityLevelConfig = z.infer<typeof MaturityLevelConfigSchema>;

export const ScoringConfigSchema = z.object({
  layer_score_scale: z.string(),
  layer_score_method: z.string(),
  layer_score_note: z.string(),
  overall_score: OverallScoreConfigSchema,
  maturity_level: MaturityLevelConfigSchema,
});
export type ScoringConfig = z.infer<typeof ScoringConfigSchema>;

export const AggregationConfigSchema = z.object({
  applies_when: z.string(),
  product_maturity_level: z.record(z.string(), z.string()),
  product_overall_score: z.record(z.string(), z.string()),
  verdict_rollup: z.record(z.string(), z.string()),
});
export type AggregationConfig = z.infer<typeof AggregationConfigSchema>;

export const UnitOfAssessmentSchema = z.object({
  scopes: z.array(z.enum(["feature", "product"])),
  feature: z.string(),
  product: z.string(),
  industry_scope: z.string(),
});
export type UnitOfAssessment = z.infer<typeof UnitOfAssessmentSchema>;

export const FrameworkSchema = z
  .object({
    framework_id: z.string(),
    framework_name: z.string(),
    based_on_framework: z.string(),
    version: z.string(),
    schema_version: z.string(),
    author: z.string(),
    org: z.string(),
    license: z.string(),
    description: z.string(),
    implementation_notes: z.string(),
    unit_of_assessment: UnitOfAssessmentSchema,
    layers: z.array(LayerSchema),
    maturity_ladder: z.array(MaturityRungSchema),
    scoring: ScoringConfigSchema,
    aggregation: AggregationConfigSchema,
    verdicts: z.array(VerdictRuleSchema),
    vanity_metric_probes: z.array(VanityMetricProbeSchema),
    cross_references: z.array(CrossReferenceSchema),
  })
  .superRefine((val, ctx) => {
    const layerIds = new Set(val.layers.map((l) => l.id));
    const weightIds = new Set(Object.keys(val.scoring.overall_score.weights));
    const sameSize = layerIds.size === weightIds.size;
    const sameMembers = sameSize && [...layerIds].every((id) => weightIds.has(id));
    if (!sameMembers) {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        message:
          `scoring.overall_score.weights keys {${[...weightIds].sort().join(", ")}} ` +
          `don't match layer ids {${[...layerIds].sort().join(", ")}}`,
      });
    }
  });
export type Framework = z.infer<typeof FrameworkSchema>;

/** Mirrors Framework.layer() in entities.py. */
export function getLayer(fw: Framework, layerId: string): Layer {
  const found = fw.layers.find((l) => l.id === layerId);
  if (!found) throw new Error(`No layer '${layerId}'`);
  return found;
}

/** Mirrors Framework.maturity_label() in entities.py. */
export function getMaturityLabel(fw: Framework, level: number): string {
  const found = fw.maturity_ladder.find((r) => r.level === level);
  if (!found) throw new Error(`No maturity level ${String(level)}`);
  return found.label;
}

/** Mirrors Framework.verdict() in entities.py. */
export function getVerdictRule(fw: Framework, verdictId: string): VerdictRule {
  const found = fw.verdicts.find((v) => v.id === verdictId);
  if (!found) throw new Error(`No verdict '${verdictId}'`);
  return found;
}

// ─────────────────────────────────────────────────────────────────────────
// Runtime report concepts — what a triage run actually produces
// ─────────────────────────────────────────────────────────────────────────

export const IndicatorEvidenceSchema = z.object({
  indicator_id: z.string(),
  tracked: z.boolean(),
  value: z.number().nullable().optional(),
  unit: z.string().nullable().optional(),
  evidence_note: z.string().nullable().optional(),
  risk_threshold_exceeded: z.boolean().nullable().optional(),
});
export type IndicatorEvidence = z.infer<typeof IndicatorEvidenceSchema>;

export const LayerResultSchema = z.object({
  layer_id: LayerIdSchema,
  score: z.number().int().min(1).max(5),
  maturity_label: z.string(),
  indicators: z.array(IndicatorEvidenceSchema),
  evidence_summary: z.string(),
});
export type LayerResult = z.infer<typeof LayerResultSchema>;

export const VerdictResultSchema = z.object({
  verdict_id: z.string(),
  name: z.string(),
  severity: SeveritySchema,
  message: z.string(),
  // Deliberately string, not the narrower LayerId enum — populated by
  // scoringEngine.ts's generic rule evaluator, which doesn't hardcode
  // the specific 3 layer names. Same reasoning as entities.py.
  layer_id: z.string().nullable().optional(),
  feature_name: z.string().nullable().optional(),
});
export type VerdictResult = z.infer<typeof VerdictResultSchema>;

export const FeatureReportSchema = z.object({
  report_id: z.string(),
  framework_id: z.literal("ai-product-pulse"),
  framework_version: z.string(),
  unit_of_assessment: z.literal("feature"),
  subject_name: z.string(),
  subject_description: z.string().nullable().optional(),
  generated_at: z.string().datetime({ offset: true }).or(z.string()), // ISO string on the wire
  generated_by_harness: z.string().nullable().optional(),
  layers: z.array(LayerResultSchema),
  overall_score: z.number().min(1).max(5),
  maturity_level: z.number().int().min(1).max(5),
  verdicts: z.array(VerdictResultSchema),
  vanity_metric_flags: z.array(z.string()).default([]),
  recommendations: z.string().nullable().optional(),
});
export type FeatureReport = z.infer<typeof FeatureReportSchema>;

export const ProductReportSchema = z.object({
  report_id: z.string(),
  framework_id: z.literal("ai-product-pulse"),
  framework_version: z.string(),
  unit_of_assessment: z.literal("product"),
  subject_name: z.string(),
  subject_description: z.string().nullable().optional(),
  generated_at: z.string(),
  generated_by_harness: z.string().nullable().optional(),
  features: z.array(FeatureReportSchema),
  product_overall_score: z.number().min(1).max(5),
  product_maturity_level: z.number().int().min(1).max(5),
  verdict_rollup: z.array(VerdictResultSchema),
});
export type ProductReport = z.infer<typeof ProductReportSchema>;

export const LayerChangeSchema = z.object({
  layer_id: LayerIdSchema,
  previous_score: z.number().int().min(1).max(5),
  current_score: z.number().int().min(1).max(5),
  delta: z.number().int(),
  previous_maturity_label: z.string(),
  current_maturity_label: z.string(),
});
export type LayerChange = z.infer<typeof LayerChangeSchema>;

export const VerdictChangeSchema = z.object({
  verdict_id: z.string(),
  name: z.string(),
  severity: SeveritySchema,
  layer_id: z.string().nullable().optional(),
});
export type VerdictChange = z.infer<typeof VerdictChangeSchema>;

export const RegressionSummarySchema = z.enum(["improved", "regressed", "mixed", "unchanged"]);
export type RegressionSummary = z.infer<typeof RegressionSummarySchema>;

export const RegressionDiffResultSchema = z.object({
  subject_name: z.string(),
  framework_version: z.string(),
  previous_generated_at: z.string(),
  current_generated_at: z.string(),
  layer_changes: z.array(LayerChangeSchema),
  overall_score_delta: z.number(),
  maturity_level_delta: z.number().int(),
  verdicts_resolved: z.array(VerdictChangeSchema),
  verdicts_introduced: z.array(VerdictChangeSchema),
  verdicts_persisting: z.array(VerdictChangeSchema),
  summary: RegressionSummarySchema,
});
export type RegressionDiffResult = z.infer<typeof RegressionDiffResultSchema>;

export const ReportSchema = z.discriminatedUnion("unit_of_assessment", [
  FeatureReportSchema,
  ProductReportSchema,
]);
export type Report = z.infer<typeof ReportSchema>;

export function newReportId(): string {
  return randomUUID();
}

export function nowIso(): string {
  return new Date().toISOString();
}
