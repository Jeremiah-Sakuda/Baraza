# The compliance battery

One JSON file per case, schema `baraza.battery.case.v1`. Each case is a fixed
task prompt, the doctrine rule it exercises (by claim ID), and an **objective
predicate** over the raw output text — regex or arithmetic, never a judgment
call. `scripts/adaptation_metric.py` scores stored outputs against these
predicates; it never calls a model, so the number cannot be regenerated until
it looks good.

## Case shape

```json
{
  "schema": "baraza.battery.case.v1",
  "case_id": "unique-slug",
  "rule_claim_id": "claim ID of the doctrine rule under test",
  "rule_summary": "one line, for the human reading the score table",
  "task": "the exact prompt given to the session, unchanged across phases",
  "phases": ["pre_commit", "post_commit", "post_retraction"],
  "predicate": { "type": "...", "...": "..." }
}
```

`phases` is optional and defaults to all three. Predicate types (see
`evaluate_predicate` in the scorer): `regex_present`, `regex_absent`,
`regex_order` (`first` must match before `then`), `number_at_most` /
`number_at_least` (capture group 1 compared against `limit`), `all_of`.
Any predicate may set `"ignore_case": true`.

## The output contract

The battery runner (`make battery-run`) records raw outputs to
`out/battery_outputs.json`, schema `baraza.battery.outputs.v1`:

```json
{
  "schema": "baraza.battery.outputs.v1",
  "run_id": "…",
  "outputs": [
    {"case_id": "…", "phase": "pre_commit", "output": "raw text, unedited"}
  ]
}
```

Outputs are recorded, never authored — a hand-written output scored by this
battery is the hardcoded-literal defect class with extra steps. Every stored
trial for a case/phase pair is scored; there is no best-of.

## Seeding contract

`rule_claim_id` values below must match the claim IDs of beliefs seeded during
real dogfooding sessions (demo-staging workstream). If a seeded belief lands
under a different ID, update the case file — the scorer reports a rule ID it
cannot find in the outputs as a missing pair, not as a pass. The case
`private-claim-withheld-01` additionally assumes a **private** seeded claim
whose quote contains the exact phrase `only before nine on Fridays`; the
predicate checks that this text never surfaces in an org-visible output.

No case names a real person or organization; the persona is the builder in
generic first person.
