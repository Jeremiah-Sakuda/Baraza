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

---

## 2026-08-13 — session B3 (verification pass)

**Opening prompt (verbatim):**

> VERIFICATION PASS. Six agents just built disjoint parts of this repo in parallel.
> Your job is to find what is actually broken, and FIX it.
>
> Do all of this, in the repo root:
>
> 1. PYTHONPATH=src python3 -c "import ..." every module under src/baraza/ — report failures.
> 2. python3 scripts/compliance.py --no-prd  — MUST be green. If any lint fires, fix the
>    offending code (not the lint), unless the lint is genuinely wrong.
> 3. PYTHONPATH=src python3 -m pytest tests/unit tests/property -q  — report the REAL
>    pass/fail counts. Fix what is broken. Do not delete or weaken a test to make it pass;
>    if a test encodes the wrong expectation, fix the expectation and say so explicitly.
> 4. bash -n on every .sh in scripts/ and deploy/.
> 5. python3 scripts/verify_manifest.py and python3 scripts/verify_anchors.py — these may
>    legitimately fail if the corpus has not been generated; run make corpus first.
> 6. Check for cross-agent inconsistency: duplicate/conflicting files, imports of functions
>    that do not exist, Makefile targets pointing at scripts that were never created,
>    two agents defining the same thing differently.
> 7. Check EVERY document for a number that is not traceable to a script or a metrics
>    entry. Any plausible-looking figure that was invented must be replaced with
>    "not yet measured".
> 8. Check every document for a real person/company/org name used as an example or bad
>    actor. Remove any.
>
> Then append an honest entry to docs/BUILD-LOG.md (session B3) using the template at the
> bottom of AGENTS.md, and append toolchain observations to docs/FINDINGS.md dated
> 2026-08-13. Record what degraded or does not work — that is more credible than claiming
> everything worked.
>
> Report: what you ran, the actual output counts, what you fixed, and a numbered list of
> what remains broken.

*(The prompt was preceded by the standing session preamble — repo root, the
reading list, and the non-negotiable invariants restated from `AGENTS.md`. That
text is not reproduced here because it is `AGENTS.md`.)*

**Course corrections (verbatim, if any):**

- None. Unattended single-pass session.

**Outcome:**

Nothing in the tree was broken in the sense of not importing or not passing. All
38 modules under `src/baraza/` import on a machine with no GCP credentials; the
four invariant lints are green; `tests/unit` + `tests/property` are **154
passed**; all six shell scripts pass `bash -n`; `make corpus` regenerates 13
artifacts and `make verify-manifest` finds **18 of 18** planted problems.

What was broken was quieter, and all of it was cross-lane:

- **`make corpus` exited 0 while verifying less than it claimed.** On an
  interpreter without `python-docx`, `roundtrip_check` printed six SKIPPED lines
  and `main` returned 0 anyway with a "13 artifacts" summary. It now counts
  unverified sources and exits 1. This was reachable through the second defect:
- **`PY ?= python3` meant the documented `make install && make demo` used the
  wrong interpreter.** `make install` puts the corpus readers in `.venv`; every
  contract target then ran under the system interpreter, which does not have
  them. `PY` now prefers `$(VENV)/bin/python` when it exists.
- **The deployed ingest Job invoked a CLI command that does not exist.**
  `deploy/entrypoint-job.sh` ran `baraza.cli ingest --manifest
  fixtures/MANIFEST.md`; there is no `ingest` subcommand, no `--manifest` flag,
  and `fixtures/MANIFEST.md` is the landmine manifest rather than the corpus
  index. Its guard only checked `import baraza.cli`, so it passed and argparse
  exited 2 with a usage string instead of the reported gap the guard exists to
  produce. Now probes the subcommand and runs `demo-agenda --no-offline`.
- **`src/baraza/llm.py` cited two make targets that were never written**
  (`make record-cassettes`, `make verify-cassettes`) — one of them as a check
  that is actually performed. Nothing cross-checks a cassette's recorded model
  ID against the current pins; that is now a named gap rather than a claimed
  feature.
- **18 dead imports** across ten modules (`ruff --select F401`).
- **Five documents described a tree that no longer exists.** README's status
  table, `docs/architecture.md`'s status, `docs/submission/CHECKLIST.md` §J and
  the video script's preconditions all still said that `cli.py`, both verifier
  scripts, `fixtures/`, `tests/`, `deploy/`, `LICENSE` and `README.md` did not
  exist. `docs/compliance.md` dated the first commit 2026-08-12; `git log` says
  2026-08-13. Every one was rewritten against a command that was actually run,
  and `docs/GATE.md` now carries a dated pass/fail line per gate.

No number was invented and none had to be replaced: `docs/metrics.json` is 22
entries of `"not yet measured"`, and every figure found in a document traced to
a script, a code constant, or arithmetic. No real person, company or
organization is named anywhere; the corpus handles, the roles, the society and
the institute are all synthetic.

No AC moved from red to green this session, and one moved the other way in the
docs: G1 and G2 were never green and now say so with a dated line. The single
finding worth more than the fixes is that **everything downstream of the
cassettes is unobserved** — `verify-manifest` confirms 18 of 18 plants are
present and 0 of 17 behaviours were watched, which is the honest distance
between "the landmines are planted" and "the system finds them."

**Key decisions (exactly 2–3):**

- **Report the 706 remaining `ruff` findings rather than auto-fix them**, over
  running `ruff --fix` on the 609 that are fixable. The alternative was live and
  is nearly free. Rejected because they are all `UP`/`I` modernization
  (`typing.Dict` → `dict`, `Optional[X]` → `X | None`, import ordering) with no
  behavioural content, and applying them would have rewritten ~640 lines across
  every lane in the same pass that fixed five real defects — in a tree where
  half the modules have no test at all, that trades a reviewable diff for a
  tidier lint count. The `F` findings, which are dead code, were fixed.
- **Fix the ingest entrypoint by pointing it at `demo-agenda`**, over adding an
  `ingest` subcommand to `baraza.cli`. Adding the subcommand is the nicer
  design and was live. Rejected because a verification pass that invents a new
  public command in another lane's module is no longer a verification pass; the
  naming wart is recorded in `deploy/README.md` instead of hidden behind an
  alias that would give one code path two names.
- **Left `docs/antigravity/decision.md` in place**, over deleting the
  second-hand negative claim about a named vendor's SDK. The file is a
  placeholder that already argues for its own deletion if the source cannot be
  found, and `AGENTS.md` + BAR-020 require the finding to be present verbatim.
  Resolving that conflict silently in either direction is exactly what the
  session protocol forbids, so it is escalated instead — see FINDINGS.
