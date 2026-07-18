/**
 * regressionDiff — compares two FeatureReport instances for the same
 * feature, taken at different points in time. Direct port of
 * usecases/regression_diff.py, including the severity-aware
 * classification logic: a verdict with severity "none" (i.e.
 * "balanced") newly firing is good news, not a second, symmetric kind
 * of "something changed" — that distinction was a real bug caught while
 * building the Python version, and this port has it correct from the
 * start rather than needing to rediscover it.
 */
import {
  LayerChangeSchema,
  VerdictChangeSchema,
  type FeatureReport,
  type LayerChange,
  type RegressionDiffResult,
  type RegressionSummary,
  type VerdictChange,
} from "../domain/entities.js";

export interface RegressionDiffOptions {
  previous: FeatureReport;
  current: FeatureReport;
}

function rejectMismatchedSubject(previous: FeatureReport, current: FeatureReport): void {
  if (previous.subject_name !== current.subject_name) {
    throw new Error(
      "regression_diff() compares the same feature over time — got subject_name " +
        `'${previous.subject_name}' vs '${current.subject_name}'. Comparing different features isn't ` +
        "a regression diff; that's what aggregate_product_pulse() is for.",
    );
  }
}

function rejectMismatchedFrameworkVersion(previous: FeatureReport, current: FeatureReport): void {
  if (previous.framework_version !== current.framework_version) {
    throw new Error(
      "Both reports must share the same framework_version to diff — got " +
        `'${previous.framework_version}' vs '${current.framework_version}'. ` +
        "Re-run triage() for the outdated report against the current framework.json first.",
    );
  }
}

function rejectOutOfOrderTimestamps(previous: FeatureReport, current: FeatureReport): void {
  if (new Date(current.generated_at).getTime() < new Date(previous.generated_at).getTime()) {
    throw new Error(
      `'current' (${current.generated_at}) is earlier than 'previous' (${previous.generated_at}) — ` +
        "check the argument order, regression_diff(previous, current) expects them chronologically.",
    );
  }
}

function diffLayers(previous: FeatureReport, current: FeatureReport): LayerChange[] {
  const currentById = new Map(current.layers.map((l) => [l.layer_id, l] as const));
  return previous.layers.map((prevLayer) => {
    const curLayer = currentById.get(prevLayer.layer_id);
    if (!curLayer) {
      throw new Error(`current report is missing layer '${prevLayer.layer_id}' present in previous`);
    }
    return LayerChangeSchema.parse({
      layer_id: prevLayer.layer_id,
      previous_score: prevLayer.score,
      current_score: curLayer.score,
      delta: curLayer.score - prevLayer.score,
      previous_maturity_label: prevLayer.maturity_label,
      current_maturity_label: curLayer.maturity_label,
    });
  });
}

/** Two verdicts are "the same" for diffing purposes if they share a
 * verdict_id AND a layer_id — Blind Spot: Model Performance resolving
 * while Blind Spot: Product Behaviour is newly introduced are two
 * different things, not one verdict "persisting". */
function verdictIdentity(v: VerdictChange): string {
  return `${v.verdict_id}::${v.layer_id ?? "-"}`;
}

function diffVerdicts(
  previous: FeatureReport,
  current: FeatureReport,
): { resolved: VerdictChange[]; introduced: VerdictChange[]; persisting: VerdictChange[] } {
  const previousChanges = previous.verdicts.map((v) =>
    VerdictChangeSchema.parse({ verdict_id: v.verdict_id, name: v.name, severity: v.severity, layer_id: v.layer_id }),
  );
  const currentChanges = current.verdicts.map((v) =>
    VerdictChangeSchema.parse({ verdict_id: v.verdict_id, name: v.name, severity: v.severity, layer_id: v.layer_id }),
  );

  const previousByIdentity = new Map(previousChanges.map((v) => [verdictIdentity(v), v] as const));
  const currentByIdentity = new Map(currentChanges.map((v) => [verdictIdentity(v), v] as const));

  const resolved = [...previousByIdentity.entries()]
    .filter(([id]) => !currentByIdentity.has(id))
    .map(([, v]) => v);
  const introduced = [...currentByIdentity.entries()]
    .filter(([id]) => !previousByIdentity.has(id))
    .map(([, v]) => v);
  const persisting = [...currentByIdentity.entries()]
    .filter(([id]) => previousByIdentity.has(id))
    .map(([, v]) => v);

  return { resolved, introduced, persisting };
}

/**
 * Only verdicts with real severity count as "bad news" appearing or
 * disappearing. 'balanced' (severity 'none') newly firing is good news,
 * not a second, symmetric kind of change.
 */
function classify(
  overallScoreDelta: number,
  maturityLevelDelta: number,
  resolved: VerdictChange[],
  introduced: VerdictChange[],
): RegressionSummary {
  const negativeResolved = resolved.filter((v) => v.severity !== "none");
  const negativeIntroduced = introduced.filter((v) => v.severity !== "none");

  if (negativeIntroduced.length > 0 && negativeResolved.length === 0) return "regressed";
  if (negativeResolved.length > 0 && negativeIntroduced.length === 0) return "improved";
  if (negativeResolved.length > 0 && negativeIntroduced.length > 0) return "mixed";
  if (maturityLevelDelta > 0 || overallScoreDelta > 0) return "improved";
  if (maturityLevelDelta < 0 || overallScoreDelta < 0) return "regressed";
  return "unchanged";
}

export function regressionDiff(options: RegressionDiffOptions): RegressionDiffResult {
  const { previous, current } = options;

  rejectMismatchedSubject(previous, current);
  rejectMismatchedFrameworkVersion(previous, current);
  rejectOutOfOrderTimestamps(previous, current);

  const layerChanges = diffLayers(previous, current);
  const overallScoreDelta = Math.round((current.overall_score - previous.overall_score) * 100) / 100;
  const maturityLevelDelta = current.maturity_level - previous.maturity_level;
  const { resolved, introduced, persisting } = diffVerdicts(previous, current);

  return {
    subject_name: current.subject_name,
    framework_version: current.framework_version,
    previous_generated_at: previous.generated_at,
    current_generated_at: current.generated_at,
    layer_changes: layerChanges,
    overall_score_delta: overallScoreDelta,
    maturity_level_delta: maturityLevelDelta,
    verdicts_resolved: resolved,
    verdicts_introduced: introduced,
    verdicts_persisting: persisting,
    summary: classify(overallScoreDelta, maturityLevelDelta, resolved, introduced),
  };
}
