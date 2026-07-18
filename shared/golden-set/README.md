# Golden Set

## What's actually here right now

`example-cases.json` is synthetic. Every case in it is a constructed
illustration, not a real (anonymized or otherwise) product metrics
scenario. It exists to prove `golden_set_calibrate()` works mechanically
— the harness runs, the comparison logic is correct, the pass/fail
math is right. It is not calibration evidence. Nothing in this repo,
in `docs/`, or in anything derived from a `golden_set_calibrate()` run
against this file should ever be cited as if the scoring logic has been
validated against real cases. It hasn't, yet.

This distinction matters enough to repeat: a pass rate computed against
`example-cases.json` proves the code correctly checks its own answer
key. It does not prove the answer key is right about the real world.
Only real cases can do that.

## Format

```json
{
  "cases": [
    {
      "case_id": "unique-slug",
      "description": "Anonymized context — what the feature does, not who the client is.",
      "layers": [
        { "layer_id": "model_performance", "score": 1-5, "evidence_summary": "...", "indicators": [...] },
        { "layer_id": "product_behaviour", "score": 1-5, "evidence_summary": "...", "indicators": [...] },
        { "layer_id": "business_outcome", "score": 1-5, "evidence_summary": "...", "indicators": [...] }
      ],
      "expected_verdict_ids": ["business_outcome_orphaned"],
      "expected_maturity_level": 1
    }
  ]
}
```

`layers` uses the exact same shape `triage()`'s CLI/MCP input does —
see `examples/sample-input.json` at the repo root for a full worked
example. `expected_verdict_ids` and `expected_maturity_level` are what
a correct `triage()` run should produce for that input; leave
`expected_maturity_level` out if you're not confident enough in the
number to assert it, since a wrong assertion is worse than an absent
one — `golden_set_calibrate()` treats a missing expectation as "don't
check this," not as "expect the default."

## Contributing real cases

This is where a contribution actually moves the needle on whether this
framework's scoring can be trusted, more than almost anything else in
the repo — see CONTRIBUTING.md's Golden-set section. A real case needs:

- **Real evidence**, anonymized to remove client-identifying detail but
  not softened or idealized. A messy, ambiguous real case is more
  valuable than a clean synthetic one — the scoring logic needs to be
  checked against the actual shape of real evidence, not against cases
  written to be easy.
- **An expected answer you're confident in**, ideally one you or
  someone else arrived at independently of running `triage()` — a case
  where the expected verdicts were reverse-engineered from what the
  tool already outputs doesn't calibrate anything, it just checks that
  the code agrees with itself.
- **A case_id and description with no client-identifying information** —
  no company names, no personally identifying details, nothing that
  would let someone reconstruct which engagement this came from.

When real cases exist, `example-cases.json` should either be replaced
outright or split into a clearly separate `illustrative/` subfolder so
the two are never confused in a report or a pass-rate number quoted
externally.
