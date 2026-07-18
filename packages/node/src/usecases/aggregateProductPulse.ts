/**
 * aggregateProductPulse — rolls up two or more feature-level
 * FeatureReports into one ProductReport. Direct port of
 * usecases/aggregate_product_pulse.py.
 *
 * Like the Python version, this stays a single file rather than
 * growing a separate domain/ engine — the comparison logic here is a
 * handful of set operations and score arithmetic, not a rule-dispatch
 * system like scoringEngine.ts's verdict evaluation.
 */
import {
  newReportId,
  nowIso,
  type FeatureReport,
  type Framework,
  type ProductReport,
  type VerdictResult,
} from "../domain/entities.js";
import { framework as defaultFramework } from "../domain/loader.js";

export interface AggregateProductPulseOptions {
  subjectName: string;
  features: FeatureReport[];
  subjectDescription?: string | undefined;
  generatedByHarness?: string | undefined;
  fw?: Framework;
}

function rejectFewerThanTwoFeatures(features: FeatureReport[]): void {
  if (features.length < 2) {
    throw new Error(
      `aggregate_product_pulse() requires at least two FeatureReports (got ${String(features.length)}). ` +
        "A single feature doesn't need product-level rollup — use its FeatureReport directly. " +
        "See framework.json's aggregation.applies_when.",
    );
  }
}

function rejectMismatchedFrameworkVersions(features: FeatureReport[]): void {
  const versions = new Set(features.map((f) => f.framework_version));
  if (versions.size > 1) {
    throw new Error(
      `All features must share the same framework_version to aggregate; got ${JSON.stringify([...versions].sort())}. ` +
        "Re-run triage() for the outdated features against the current framework.json first.",
    );
  }
}

function rejectDuplicateSubjectNames(features: FeatureReport[]): void {
  const names = features.map((f) => f.subject_name);
  if (new Set(names).size !== names.length) {
    const duplicates = [...new Set(names.filter((n) => names.filter((n2) => n2 === n).length > 1))].sort();
    throw new Error(
      `Feature subject_name values must be unique within a product rollup — duplicated: ${JSON.stringify(duplicates)}. ` +
        "Verdict attribution in the rollup depends on the name being unambiguous.",
    );
  }
}

export function aggregateProductPulse(options: AggregateProductPulseOptions): ProductReport {
  const fw = options.fw ?? defaultFramework();
  const { features } = options;

  rejectFewerThanTwoFeatures(features);
  rejectMismatchedFrameworkVersions(features);
  rejectDuplicateSubjectNames(features);

  // product_maturity_level: min(feature_maturity_levels) — same weakest-
  // link principle as layer-level maturity_level. See framework.json's
  // aggregation.product_maturity_level.rationale.
  const productMaturityLevel = Math.min(...features.map((f) => f.maturity_level));

  // product_overall_score: mean(feature_overall_scores), flat and equal —
  // confirmed decision, see aggregation.product_overall_score in framework.json.
  const productOverallScore =
    Math.round((features.reduce((sum, f) => sum + f.overall_score, 0) / features.length) * 100) / 100;

  // verdict_rollup: every verdict from every feature, attributed, never
  // blended away. See aggregation.verdict_rollup.rule.
  const verdictRollup: VerdictResult[] = features.flatMap((feature) =>
    feature.verdicts.map((verdict) => ({ ...verdict, feature_name: feature.subject_name })),
  );

  const report: ProductReport = {
    report_id: newReportId(),
    framework_id: "ai-product-pulse",
    framework_version: fw.version,
    unit_of_assessment: "product",
    subject_name: options.subjectName,
    subject_description: options.subjectDescription ?? null,
    generated_at: nowIso(),
    generated_by_harness: options.generatedByHarness ?? null,
    features,
    product_overall_score: productOverallScore,
    product_maturity_level: productMaturityLevel,
    verdict_rollup: verdictRollup,
  };

  return report;
}
