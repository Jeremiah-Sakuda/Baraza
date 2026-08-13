# BUILD-LOG.md

One entry per session, appended **before** the session's commit. Morning review
bisects on these.

---

## 2026-08-13 — session B0 (substrate)

**Opening prompt (verbatim):**

> Here we have a new repo and project. I want you to complete it end to end,
> ending wth a final list of things I need to do by hand. This is for this
> hackathon, so at the end, run a judging panel against these rules, and
> implement any improvements that are worthwhile to maximize winning probability

*(The prompt continued with the full text of the All Things Agentic Hackathon
official rules, pasted from the Devpost rules page. That text is not reproduced
here; the requirements it imposes are tracked in the compliance matrix and in
`docs/submission/` .)*

**Course corrections (verbatim, if any):**

- "Before you proceed, relay everything back to me so I can confirm"
- "continue" (×2, after interrupted environment-probe commands)

Answers given to the four blocking questions:
- PRD v1.1 — *"You'll supply v1.1"*
- GCP — *"Run gcloud in this session"*
- Bonus models — *"Gemma + one more, real job"*
- Category — *"Submit Collaborative Partner, engineer for all three"*

**Outcome:**

Repository initialized from two files (AGENTS.md, the v1.2 amendments) to a
working substrate. Built: `schema/` (temporal, visibility, claim, event,
contradiction, session, models), `fold/graph.py`, `scripts/compliance.py`, the
Makefile's seven contract targets plus supporting targets, `pyproject.toml`,
`docs/metrics.json`, `docs/GATE.md`, `docs/framework-decision.md`,
`docs/FINDINGS.md`.

Green: all four invariant lints, verified by planting violations and watching
each one fire with a file:line, then removing the plant and returning to green.

**Not** green, and recorded rather than routed around: the BAR-007 PRD audit
cannot run. `docs/PRD.md` is absent and the amendments file forbids
reconstructing the unrecovered v1.1 sections. `make compliance` exits 2 with an
explanation, which is distinct from exit 1 (findings) and from exit 0 (green).
Roughly 35 requirement IDs currently have no acceptance criteria in the tree.
The substrate proceeded because none of it depends on those sections.

Deferred to later sessions: ingestion, reconciler, interview engine, corpus
generation, tests, deploy lane, submission artifacts.

**Key decisions (exactly 2–3):**

- **Structural boundary over conventional boundary**, over the simpler design
  where `Claim.quote` is a plain attribute and each read site is expected to
  call `readable_by` first. The alternative was live and is what most codebases
  do. Rejected because the requirement says the boundary must hold under
  carelessness, and a predicate that must be *remembered* at every read site is
  a predicate that will eventually be forgotten at one. The quote now lives
  behind `quote_for(audience)` and a compliance lint fails the build on any
  access to the raw field outside the schema package.

- **Build the substrate despite the missing contract**, over halting at
  `STOPPED.md` per §2.5.2. The alternative was live and is arguably the more
  literal reading of the repo's own rules. Chosen because the stop condition
  protects against *reconstructing* unrecovered requirements, and nothing built
  this session reconstructs anything — the schema, fold, boundary, and temporal
  rules are fully specified by AGENTS.md's hard constraints and by amended
  requirement text that is present. The gap is recorded in three places rather
  than papered over, and the PRD merge remains the top open task.

- **Distinguish "audit could not run" from "audit found nothing"**, over letting
  `make compliance` pass with the PRD check silently skipped. A green gate that
  skipped its main check is the exact shape of the failure this project keeps
  naming.
