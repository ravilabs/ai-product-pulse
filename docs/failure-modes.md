# Failure Modes

What can actually go wrong when using AI Product Pulse, and what is and isn't done about each. Written for someone deciding how much to trust a report, not as a compliance checklist.

## Harness-invariance: the same evidence can score differently in different sessions

Layer scoring is the one place in the pipeline that isn't deterministic — it's the calling agent's judgment, reading evidence and matching it against the maturity ladder in `framework.json`. Run the identical evidence through a Claude Code session and a Cursor session and there's no guarantee both land on the same 1-to-5 score for every layer. A borderline case — evidence that could plausibly read as either Ad Hoc (2) or Instrumented (3) — is exactly where this shows up.

**What's not done about this yet:** there's no built-in harness-invariance check — no mechanism that runs the same input through multiple sessions and flags disagreement. If this matters for a given use (comparing scores across a team using different tools, for instance), that comparison currently has to be done by hand.

## The tool can't verify evidence is true

`triage()` trusts whatever `IndicatorEvidence` it's given. If an agent reports `override_rate: 12%` because a user said so, the tool has no way to check that against an actual analytics dashboard — it scores the claim, not the underlying reality. This is true of the framework by design (it's a triage tool, not an instrumentation platform), but it means a report is only as reliable as the evidence-gathering conversation that produced it.

## Vanity-metric probes catch known patterns, not novel ones

The four probes in `framework.json` (`activity_masquerading_as_behaviour`, `internal_eval_as_business_outcome`, `output_volume_as_progress`, `sentiment_without_behaviour`) are fixed, named anti-patterns. Matching evidence against them is a semantic judgment made by the calling agent, not a deterministic check — the same category of judgment call as layer scoring, and it inherits the same harness-invariance risk. A genuinely new kind of vanity metric, one that doesn't resemble any of the four, won't be caught until someone adds a fifth probe.

## Aggregation treats features as independent

`aggregate_product_pulse()` rolls up features with `min()` for maturity level and a flat `mean()` for overall score, deliberately, per `framework.json`'s `aggregation` section. What it doesn't model: interaction effects between features. A product where Feature A's poor Trust Failure Signal is actively suppressing adoption of an otherwise-solid Feature B reads, in the current design, as two independent scores — not as one feature's failure dragging down another's real-world performance. The rollup is a portfolio snapshot, not a causal model.

## Framework-version mismatches block aggregation entirely, on purpose

If two features were scored against different versions of `framework.json`, `aggregate_product_pulse()` refuses to combine them rather than silently averaging across scoring epochs that may not mean the same thing. This is deliberately strict rather than deliberately convenient — the alternative (aggregating anyway) risks a number that looks precise and isn't comparable.

## No built-in way to track change over time, yet

There's currently no `regression_diff`-style operation comparing this quarter's triage to last quarter's for the same feature. "Did the team fix the blind spot flagged last time" is not something the tool answers on its own right now — it has to be tracked externally, by re-running `triage()` and comparing reports by hand.

## Self-grading circularity does not apply here, and it's worth knowing why

A category of AI evaluation tool has a specific known problem: the same model grades its own output, with no independent check. That doesn't apply to this tool's core use case — the agent is scoring a *third party's* product metrics, not its own output. This is a real structural advantage over self-evaluation tools, not a claim requiring a caveat.

Where something adjacent to that risk does apply: if this tool is ever used to have an AI-built feature evaluate *itself* (an AI feature's own team using it to self-assess, with no outside evidence review), the harness-invariance and evidence-verification limits above compound — there's no external check on either the evidence or the judgment applied to it.
