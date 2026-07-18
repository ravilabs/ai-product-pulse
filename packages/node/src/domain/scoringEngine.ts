/**
 * Deterministic scoring and verdict evaluation. No file I/O, no LLM
 * calls — direct port of domain/scoring_engine.py in the Python
 * package. Kept structurally parallel to that file on purpose: anyone
 * debugging a cross-language parity mismatch should be able to read
 * the two side by side and find the divergence quickly.
 *
 * See scoring_engine.py's own docstring for why the "formula" strings
 * inside framework.json aren't parsed or evaluated here — that
 * reasoning applies identically in this port.
 */
import type { Framework, IndicatorEvidence, VerdictResult } from "./entities.js";

type Operator = "gte" | "lte" | "gt" | "lt" | "eq";

const OPERATORS: Record<Operator, (value: number, threshold: number) => boolean> = {
  gte: (value, threshold) => value >= threshold,
  lte: (value, threshold) => value <= threshold,
  gt: (value, threshold) => value > threshold,
  lt: (value, threshold) => value < threshold,
  eq: (value, threshold) => value === threshold,
};

export function applyRiskThresholds(
  fw: Framework,
  indicatorEvidence: Map<string, IndicatorEvidence>,
): void {
  const allIndicators = new Map(
    fw.layers.flatMap((layer) => layer.indicators.map((ind) => [ind.id, ind] as const)),
  );
  for (const [indicatorId, evidence] of indicatorEvidence) {
    const indicatorDef = allIndicators.get(indicatorId);
    if (!indicatorDef?.risk_threshold) continue;
    if (evidence.value === null || evidence.value === undefined) {
      evidence.risk_threshold_exceeded = null;
      continue;
    }
    const rt = indicatorDef.risk_threshold;
    evidence.risk_threshold_exceeded = OPERATORS[rt.operator](evidence.value, rt.value);
  }
}

/**
 * weighted_mean(layer_scores, weights) — see scoring.overall_score in
 * framework.json.
 *
 * Computed in integer milliunits (weight * 1000, rounded) through the
 * final rounding step, not naive float accumulation followed by
 * Math.round(). This is not defensive style — it fixes a real,
 * confirmed cross-language parity bug: CPython 3.12's built-in sum()
 * uses compensated (Neumaier) summation for floats, more numerically
 * precise than a naive `total += x` loop. For layer scores (4, 2, 1)
 * against this framework's weights, the true weighted sum lands
 * exactly on 2.335 — a binary-float knife's edge where Python's sum()
 * and this naive accumulator landed on opposite sides, producing 2.33
 * in Python and 2.34 here for identical input. Integer arithmetic up
 * to the single final IEEE-754 division (deterministic and
 * cross-platform identical by spec) removes the ambiguity. Rounds half
 * up explicitly, matching the same explicit choice made in
 * scoring_engine.py, rather than relying on whatever either language's
 * binary-float rounding happens to do at a tie.
 */
export function computeOverallScore(fw: Framework, layerScores: Map<string, number>): number {
  const weights = fw.scoring.overall_score.weights;
  let totalMilliunits = 0;
  for (const [layerId, weight] of Object.entries(weights)) {
    totalMilliunits += Math.round((layerScores.get(layerId) ?? 0) * weight * 1000);
  }
  const remainder = totalMilliunits % 10;
  const roundedMilliunits = totalMilliunits - remainder + (remainder >= 5 ? 10 : 0);
  return roundedMilliunits / 1000;
}

export function computeMaturityLevel(layerScores: Map<string, number>): number {
  return Math.min(...layerScores.values());
}

// ── verdict trigger handlers ────────────────────────────────────────────
// One function per trigger_type in framework.json. "Global" handlers
// return a bool. "Per-layer" handlers return the list of layer_ids that
// matched, since that trigger_type is evaluated once per layer.

interface HandlerArgs {
  layerScores: Map<string, number>;
  indicatorEvidence: Map<string, IndicatorEvidence>;
  trigger: Record<string, unknown>;
}

function allLayersGte({ layerScores, trigger }: HandlerArgs): boolean {
  const value = trigger.value as number;
  return [...layerScores.values()].every((score) => score >= value);
}

function layerEquals({ layerScores, trigger }: HandlerArgs): boolean {
  const layer = trigger.layer as string;
  const value = trigger.value as number;
  return layerScores.get(layer) === value;
}

function layerGteAndIndicatorRiskThreshold({ layerScores, indicatorEvidence, trigger }: HandlerArgs): boolean {
  const layer = trigger.layer as string;
  const layerMinValue = trigger.layer_min_value as number;
  const indicatorId = trigger.indicator as string;
  if ((layerScores.get(layer) ?? -Infinity) < layerMinValue) return false;
  const evidence = indicatorEvidence.get(indicatorId);
  return Boolean(evidence?.risk_threshold_exceeded);
}

function layerEqualsAndOtherGte({ layerScores, trigger }: HandlerArgs): boolean {
  const layer = trigger.layer as string;
  const value = trigger.value as number;
  if (layerScores.get(layer) !== value) return false;
  const others = [...layerScores.entries()].filter(([id]) => id !== layer).map(([, s]) => s);
  const threshold = trigger.other_layers_min_value as number;
  const mode = (trigger.other_layers_mode as string | undefined) ?? "any";
  if (mode === "any") return others.some((s) => s >= threshold);
  if (mode === "all") return others.every((s) => s >= threshold);
  throw new Error(`Unknown other_layers_mode: '${mode}'`);
}

function perLayerEqualsWithOtherGte({ layerScores, trigger }: HandlerArgs): string[] {
  const excluded = new Set((trigger.excluded_layers as string[] | undefined) ?? []);
  const thisValue = trigger.this_layer_value as number;
  const otherMin = trigger.other_layer_min_value as number;
  const matches: string[] = [];
  for (const [layerId, score] of layerScores) {
    if (excluded.has(layerId) || score !== thisValue) continue;
    const others = [...layerScores.entries()].filter(([id]) => id !== layerId).map(([, s]) => s);
    if (others.some((s) => s >= otherMin)) matches.push(layerId);
  }
  return matches;
}

const GLOBAL_HANDLERS: Record<string, (args: HandlerArgs) => boolean> = {
  all_layers_gte: allLayersGte,
  layer_equals: layerEquals,
  layer_gte_and_indicator_risk_threshold: layerGteAndIndicatorRiskThreshold,
  layer_equals_and_other_gte: layerEqualsAndOtherGte,
};
const PER_LAYER_HANDLERS: Record<string, (args: HandlerArgs) => string[]> = {
  per_layer_equals_with_other_gte: perLayerEqualsWithOtherGte,
};

export function evaluateVerdicts(
  fw: Framework,
  layerScores: Map<string, number>,
  indicatorEvidence: Map<string, IndicatorEvidence>,
): VerdictResult[] {
  // Deliberately Map<string, string>, not Map<LayerId, string> — this
  // module doesn't hardcode the specific 3 layer literals, matching the
  // same widening decision already made for VerdictResult.layer_id.
  const layerNames = new Map<string, string>(fw.layers.map((layer) => [layer.id, layer.name]));
  const results: VerdictResult[] = [];

  const sortedVerdicts = [...fw.verdicts].sort((a, b) => a.priority - b.priority);

  for (const rule of sortedVerdicts) {
    const trigger = rule.trigger;
    const args: HandlerArgs = { layerScores, indicatorEvidence, trigger };

    const perLayerHandler = PER_LAYER_HANDLERS[rule.trigger_type];
    const globalHandler = GLOBAL_HANDLERS[rule.trigger_type];

    if (perLayerHandler) {
      for (const layerId of perLayerHandler(args)) {
        const message = rule.label_template
          ? rule.label_template.replace("{layer_name}", layerNames.get(layerId) ?? layerId)
          : rule.description;
        results.push({
          verdict_id: rule.id,
          name: rule.name,
          severity: rule.severity,
          layer_id: layerId,
          message,
        });
      }
    } else if (globalHandler) {
      if (globalHandler(args)) {
        results.push({
          verdict_id: rule.id,
          name: rule.name,
          severity: rule.severity,
          message: rule.description,
        });
      }
    } else {
      const known = [...Object.keys(GLOBAL_HANDLERS), ...Object.keys(PER_LAYER_HANDLERS)].sort();
      throw new Error(
        `No handler registered for trigger_type '${rule.trigger_type}' (verdict '${rule.id}'). Known: ${known.join(", ")}`,
      );
    }
  }

  return results;
}
