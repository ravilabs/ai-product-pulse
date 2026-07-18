---
name: ai-product-pulse
description: "Score AI product features against the AI Product Pulse framework across three layers - Model Performance, Product Behaviour, Business Outcome - to find blind spots, vanity metrics, and trust-failure risk before they surface in a business review. Use when the user asks to audit AI feature metrics, review what a team is tracking for an AI product, evaluate AI product health, or asks something like 'what should we be measuring for this AI feature' or 'are we tracking the right things.'"
license: MIT
metadata:
  author: Ravi Bheesetty
  version: "0.1.0"
allowed-tools: Bash Read
---

# AI Product Pulse

Deterministic triage for AI product features. You assign the judgment (a 1-5 score per layer, from evidence); the tool computes everything downstream — maturity labels, overall score, maturity level, and which verdicts fire. Don't recompute those by hand once you have them back from the tool.

## Find the tool first

Check your available MCP tools for `triage` and `aggregate_product_pulse`. If connected, call them directly — their own descriptions cover the exact input shape.

If not connected, use the CLI instead, same two operations:

```
ai-product-pulse triage --input evidence.json
ai-product-pulse aggregate --input features.json
```

If neither is available, tell the user the AI Product Pulse MCP server isn't configured or the package isn't installed, and stop — don't attempt to reimplement the scoring logic yourself. The verdict math is deliberately not something to reproduce from memory; framework.json is the source of truth.

## The three layers

| Layer | Question | Indicator IDs |
|---|---|---|
| `model_performance` | Is the AI doing what it was built to do? | `task_success_rate`, `confidence_calibration`, `hallucination_rate`, `grounding_coverage` |
| `product_behaviour` | Are users interacting with AI output the way you designed for? | `adoption_rate`, `override_rate`, `repeat_use_rate`, `escalation_rate` |
| `business_outcome` | Is the AI feature moving the metric it was funded to move? | `attributed_business_impact`, `cost_to_serve_delta`, `time_to_value`, `retention_or_renewal_impact` |

Full indicator descriptions and units live in framework.json — read it if you need more than the ID to map evidence correctly. Don't guess at an indicator ID; an unrecognized one is rejected, not silently ignored.

## Scoring each layer (1-5)

This is the one judgment call in the whole pipeline. Read whatever evidence the user gives you and match it against these anchors:

1. **No Tracking** — no defined metric, no owner, nothing logged.
2. **Ad Hoc** — informally observed, not systematic.
3. **Instrumented** — logged with a target, but review is irregular.
4. **Operationalized** — reviewed on a cadence, has influenced a real decision.
5. **Closed-Loop** — feeds an actual feedback mechanism (an experiment, a retraining trigger, a roadmap call) with evidence it's fired at least once.

If the user hasn't given you evidence for a layer at all, that's a 1 — don't infer a higher score from silence, and don't ask a clarifying question before scoring if you already have enough to know it's untracked.

## Calling triage (one feature)

Requires exactly the three layers above, each with a score, a short evidence_summary, and any indicator evidence you have:

```json
{
  "subject_name": "AI Search Assistant",
  "layers": [
    {"layer_id": "model_performance", "score": 4, "evidence_summary": "...", "indicators": [
      {"indicator_id": "task_success_rate", "tracked": true, "value": 91.2, "unit": "percentage"}
    ]},
    {"layer_id": "product_behaviour", "score": 2, "evidence_summary": "...", "indicators": []},
    {"layer_id": "business_outcome", "score": 1, "evidence_summary": "...", "indicators": []}
  ]
}
```

Untracked indicators still get an entry — `{"indicator_id": "...", "tracked": false}` — rather than being omitted.

## Multiple AI features in one product

Run `triage` once per feature, hold onto each resulting report, then pass all of them (two or more — a single feature doesn't need this step) into `aggregate_product_pulse`. It requires every feature to share the same `framework_version` and have a unique `subject_name`. The product-level maturity is the *minimum* across features, not an average — one untracked feature caps the whole product's maturity level, deliberately.

## Reading the verdicts back to the user

Translate these into plain language rather than pasting raw verdict IDs:

- **Balanced** — every layer is at least Instrumented. A floor cleared, not a ceiling.
- **Business-Outcome Orphaned** — no business metric defined at all for this feature. The single most common and most expensive gap.
- **Trust Failure Signal** — the model measures well internally, but users are overriding it enough to predict abandonment before it shows up as churn.
- **Vanity-Metric Risk** — Business Outcome is tracked, but shallowly, next to layers that are heavily instrumented. There's a metric; it's decorative.
- **Blind Spot: [layer]** — a generic flag for Model Performance or Product Behaviour going untracked while the team clearly has the capability to instrument, evidenced by another layer being solid.

A feature can get more than one verdict at once — that's not a bug, it means more than one thing is true.
