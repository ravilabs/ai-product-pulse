# MCP Tools

GENERATED FILE — DO NOT EDIT DIRECTLY. Produced by `scripts/sync_mcp_docs.py`
directly from the live tool registry (`mcp.list_tools()`), the same call a
real harness makes on connection. Edit the tool functions or their
docstrings in `packages/python/src/ai_product_pulse/adapters/inbound/mcp_server.py`,
then rerun the script.

Both tools call the identical use-case functions the CLI does —
`ai_product_pulse.usecases.triage.triage` and
`ai_product_pulse.usecases.aggregate_product_pulse.aggregate_product_pulse`.
Nothing described here is MCP-specific logic; this is a translation layer.


## `aggregate_product_pulse`

Roll up two or more feature-level triage() results into one
product-level pulse.

Pass in the full FeatureReport objects triage() returned — this tool
holds no state between calls, so it needs all of them at once. Verdicts
are never blended: every verdict from every feature survives in the
rollup, attributed to the feature that triggered it.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `subject_name` | string | Yes | Name of the product these features belong to, e.g. 'Core AI Suite'. |
| `features` | array[FeatureReport] | Yes | Two or more FeatureReport objects, each previously returned by triage(). Must share the same framework_version and have unique subject_name values. |
| `subject_description` | string | No | Optional free-text context about the product. |
| `generated_by_harness` | string | No | Which harness produced this rollup, e.g. 'claude-code'. |


## `calibrate`

Runs each case through triage() and reports pass/fail per case
plus an overall pass rate — checks the scoring logic against known
answers, rather than trusting it by inspection.

Important: a high pass rate here only means the code agrees with
the expectations it was given. It's calibration evidence only if
those expectations came from real, independently-verified cases —
see shared/golden-set/README.md before treating any number this
returns as validation.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `cases` | array[GoldenSetCase] | Yes | Known cases with expected verdicts/maturity_level. See shared/golden-set/README.md for the format. |


## `explain`

Renders a triage report as prose: the arithmetic behind
overall_score, why maturity_level is capped where it is, and
per-verdict investigative questions to guide follow-up.

Deterministic — a rendering of data that already exists in the
report and in framework.json, not a new judgment call or new
computation. Useful when the audience is a human who wants a
readable summary rather than the raw JSON report.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `report` | FeatureReport | Yes | A FeatureReport previously returned by triage(). |


## `regression_diff`

Compares two triage() reports for the same feature over time —
answers whether a previously flagged gap actually got fixed.

Both reports must share subject_name and framework_version. Returns
which verdicts resolved, which are newly introduced, which persist,
the per-layer score deltas, and an overall improved/regressed/mixed/
unchanged classification.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `previous` | FeatureReport | Yes | The earlier FeatureReport, previously returned by triage(). |
| `current` | FeatureReport | Yes | The later FeatureReport for the same feature, previously returned by triage(). Must be chronologically after previous. |


## `triage`

Score one AI feature against the AI Product Pulse framework.

Requires exactly three LayerInput entries — model_performance,
product_behaviour, business_outcome — each with a 1-5 score you assign
by reading the maturity_ladder in framework.json and matching it
against whatever evidence the user gave you. Everything past that
score (maturity labels, overall_score, maturity_level, which verdicts
fire) is computed deterministically, not re-judged by you.

**Parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `subject_name` | string | Yes | Name of the AI feature being scored, e.g. 'AI Search Assistant'. |
| `layers` | array[LayerInput] | Yes | Exactly three entries, one each for model_performance, product_behaviour, and business_outcome. |
| `subject_description` | string | No | Optional free-text context about the feature. |
| `generated_by_harness` | string | No | Which harness produced this report, e.g. 'claude-code'. Used for harness-invariance comparisons. |
| `vanity_metric_flags` | array[string] | No | IDs of any vanity_metric_probes from framework.json that matched the evidence — see framework.json's vanity_metric_probes list for valid IDs. |
| `recommendations` | string | No | Optional free-text next-step recommendations, not part of the deterministic scoring. |

