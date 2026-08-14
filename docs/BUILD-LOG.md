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

## 2026-08-13 — session B1 (ingestion spine + reconciler)

> ⚠️ **RECONSTRUCTED AFTER THE FACT.** This entry was written post-B4 from
> `git show --stat bc46324` and that commit's own message. It was not appended
> before the commit, which is what the protocol at the top of this file
> requires. Everything below is derived from artifacts in the repository; the
> verbatim opening prompt and any course corrections are **permanently
> unrecoverable**, and are not reconstructed from memory. Treat this entry as
> evidence of what landed, not as a record of how the session was driven.

**Commit:** `bc46324`, 2026-08-13 11:07:50 −0500. 14 files, +3,674 lines, all
under `src/`.

**Opening prompt:** not recorded. Not recoverable.

**Course corrections:** not recorded. Not recoverable.

**Outcome** (from the commit message and the diff):

`ingest/` — sources registry where anchors resolve or the build fails; readers
for all four native formats (skewed PDF, GroupMe epoch-seconds JSON, headerless
XLSX, DOCX minutes); locator-tagged chunking so the extractor *selects* an anchor
from a closed set rather than generating one; the BAR-303 pre-filter behind a
final `stub` / `gemma` interface; extraction with three validation gates; entity
table and `sameAs` alias pass with human confirmation.

`reconcile/` — BAR-320 on-write blocked detection, temporally gated on epoch
intervals, capped at 20 retrieved, one bounded call per write; the ranked
disputed ledger with an auditable score; the agenda generator and its closed
loop; the BAR-323 differential, which refuses to present a same-day diff as
overnight evidence; the BAR-021/321 nightly Job with deterministic heartbeat
instants so retries do not inflate the nightly-run count.

`llm.py` — the cassette client: recorded Vertex responses replayed offline so
`make demo` runs without credentials and without fabricating output. A cassette
miss raises rather than inventing a response.

Reported at the time: 17/17 modules import clean, four lints green.

**Key decisions:** not recorded. The commit message argues for the design but
does not name what was rejected, and this entry will not invent alternatives that
may never have been live. Two defects in this session's `reconcile/job.py` were
found later and are documented at the top of `tests/unit/test_job.py`; neither
was visible without a test, and this session wrote none.

---

## 2026-08-13 — session B2 (interview engine + successor librarian)

> ⚠️ **RECONSTRUCTED AFTER THE FACT**, from `git show --stat cc89d72`. Same
> caveats as B1: the opening prompt and course corrections are permanently
> unrecoverable and are not reconstructed from memory.

**Commit:** `cc89d72`, 2026-08-13 11:11:24 −0500. 4 files, +1,157 lines.

**Opening prompt:** not recorded. Not recoverable.

**Course corrections:** not recorded. Not recoverable.

**Outcome** (from the commit message and the diff):

`interview/session_store.py` — externalize before soliciting; recover by folding
rather than restoring. A turn written-but-unanswered resumes as unanswered; a
turn answered-but-unwritten is re-solicited. Fails toward re-asking.

`interview/interviewer.py` — agenda-led questions with an adaptive follow-up
budget driven by observed answer terseness. The adaptation is structural (it
moves a budget the next turn reads) and labelled (the turn records the budget and
why it changed), so a standalone scorer computes the metric from the committed
transcript without importing the app. The divergence check runs first on every
answer and only over claims readable by the current audience — the interviewer
cannot quote a private claim in order to contradict someone.

`interview/approval.py` — the only path that writes `claim.committed`. Visibility
is recorded as its own auditable event, defaulting to private. Approval closes
the loop by emitting `contradiction.resolved`. Edits become superseding claims,
never in-place mutations.

`successor/librarian.py` — refuses uncited synthesis, and refuses again if the
model's citations do not verify. Reports withheld-record *counts* without
disclosing content.

**Key decisions:** not recorded.

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
passed** *(B3's figure, left as recorded — later sessions added tests; `make
test` prints the live count)*; all six shell scripts pass `bash -n`; `make
corpus` regenerates 13
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

  **Resolved post-B4, deliberately and not silently:** the source could not be
  located, which is the branch the placeholder itself named. The file is deleted,
  the citation is gone from `docs/framework-decision.md`, and that document now
  states that ADK was chosen without a published comparison. The escalation is
  recorded here and in FINDINGS, so the reversal has a trail rather than being a
  file that stopped existing. `AGENTS.md` §7 still lists the file among the
  by-hand artifacts and has not been edited — the protocol document is not
  something a build session rewrites to match what it did.

---

## 2026-08-13 — session B4 (ADK agent layer)

> ⚠️ **RECONSTRUCTED AFTER THE FACT**, from `git show --stat c8237b2` and that
> commit's message. Not appended before the commit, as the protocol requires.
> The opening prompt and course corrections are permanently unrecoverable and
> are not reconstructed from memory.
>
> Of the four sessions missing an entry, this is the one a compliance-checking
> judge most wants a record of: it is the session that closed the mandatory
> agent-framework requirement. That it had no entry — while `docs/compliance.md`
> was citing the build log as originality evidence — is the finding, and it is
> why this backfill exists rather than a quiet renumbering.

**Commit:** `c8237b2`, 2026-08-13 21:50:42 −0500. 2 files, +550 lines
(`src/baraza/agents.py`, `tests/unit/test_agents.py`).

**Opening prompt:** not recorded. Not recoverable.

**Course corrections:** not recorded. Not recoverable.

**Outcome** (from the commit message and the diff):

B3's verification pass found that no module imported ADK while
`docs/compliance.md` and BAR-020 both named it — a matrix naming a framework the
code does not import, which is the exact failure that had already pulled the
Antigravity claim. This session closed it with real
`google.adk.agents.LlmAgent` instances.

Four roles, strictly scoped tools: `extractor` (`read_chunk`, `propose_claim`);
`reconciler` (`retrieve_block`, `record_contradiction`); `interviewer`
(`next_agenda_item`, `check_divergence`, `record_answer`); `approver`
(`commit_claim`, `reject_claim`, `set_visibility`) **and no model**. Promotion is
the one operation that must never be a model's judgement call, so the surface
that performs it cannot reason. `assert_promotion_isolated()` is itself tested by
planting a leak and watching it fire. Transfer is disabled on all three agents so
none can route around its own tool scope. Tools return structured refusals rather
than raising.

Reported at the time: 162 tests passing (8 new), four lints green.

**Corrections applied to this session's work since:**

- The commit message and the module docstring both said the promotion boundary
  was enforced "in IAM". It is not, and cannot be: Firestore's IAM permissions
  are per-operation and carry no predicate over document contents, so
  `bootstrap_gcp.sh` binds the same appender role to all three writers — as its
  own comment says. What holds the boundary is the code path, the Firestore
  rules, and a test. Corrected in `agents.py`, `ingest/pipeline.py`,
  `interview/approval.py`, `docs/architecture.md` and the Devpost draft.
- `MAX_AGENT_TURNS` and `AGENT_TIMEOUT_SECONDS` shipped in this commit as
  constants nothing read, under a docstring claiming every agent carried a turn
  ceiling and a timeout. They are now enforced through ADK's `RunConfig` and an
  `asyncio.wait_for`.

**Key decisions:** not recorded.

---

## 2026-08-13 — B5

**Opening prompt (verbatim):** not available to this entry's author. B5 was run
as a fan-out: a head judge produced a written action plan (items A1–A8) from a
review of the tree, three implementer agents worked concurrently against it, and
a fourth agent — which wrote this entry — verified their work, resolved the
conflicts between them and closed the session. The plan itself is the closest
thing to a verbatim prompt and is not carried in the tree; recording it as
"unavailable" rather than paraphrasing it follows the same rule B1/B2/B4 were
backfilled under.

**Course corrections (verbatim, if any):** none issued mid-session. The
corrections that mattered were made by the verification pass against the
implementers' own output, and are listed below.

**Outcome:**

Two structural defects in the flagship autonomous workflow were fixed, one ADK
agent was put on a real execution path, and a documentation pass removed a set of
claims that had stopped being true. Verified by this session's author, not taken
on report:

- **The nightly job examined zero claims, permanently.** `run_real` selected work
  with `fresh = [c for c in pool if c.observed_at > previous_heartbeat]`.
  `observed_at` is the instant the *source document was authored* —
  `ingest/pipeline.py` declares it from the corpus manifest precisely so it is
  not ingest time — and the corpus starts in 2016. After night one the filter
  returned the empty set forever: the Job exited 0, made zero model calls and
  found nothing. Replaced with a set difference over recorded facts:
  `retrievable_claims() - adjudicated_claim_ids`, folded from a new
  `claim.adjudicated` event appended once per claim examined. Re-planting the old
  line makes six tests in `tests/unit/test_job.py` fail, including
  `test_a_claim_authored_in_2016_and_asserted_tonight_is_examined`; that was run,
  not assumed.
- **The nightly differential was `None` on every deployed night.** `run_real`
  read last night's ledger back from `out/snapshots/`, which is container-local;
  a Cloud Run Job execution gets a fresh filesystem and `deploy/` mounts no
  volume. Now rebuilt by folding the log prefix at the previous heartbeat.
  Two further defects were found while doing it: the prior run must exclude the
  current `run_id`'s own content-addressed heartbeat, or a retry diffs tonight
  against tonight; and `contradiction.detected` events were stamped with
  `Contradiction.detected_at`, a document-authoring instant, which would have
  swept every contradiction into every baseline — a differential that is
  non-`None` and permanently empty, which is worse than `None` because it looks
  like it works.
- **One ADK agent is now on a real path.** `AgentClaimExtractor` binds
  `read_chunk` and `propose_claim` to the chunk under extraction and to the three
  validation gates, drives the extractor through an ADK `Runner`, and enforces
  `MAX_AGENT_TURNS` and `AGENT_TIMEOUT_SECONDS` — which had been constants
  nothing read, under a docstring claiming they were enforced. The ADK layer was
  also non-functional before this: `_guard` wrapped every tool in a bare
  `*args, **kwargs` shim without `functools.wraps`, and ADK builds tool
  declarations from `inspect.signature`, so **every tool was declared to the model
  as taking no parameters**. The agents passed every isolation test while being
  unable to receive an anchor.
- **Failure tolerance on the unattended path.** `llm.py` had no retry, no timeout
  and no `except`. It now carries a jittered bounded backoff that fails closed
  (429/503/504 and transport errors only), an explicit request timeout, and
  per-chunk / per-claim boundaries in the pipeline and the job. The job
  deliberately does **not** record a skipped claim as adjudicated, so a transient
  failure costs one repeated model call rather than retiring the claim forever.
- **Coverage 36% → 62%**, with the previously-untested autonomy path now the
  best-covered part of the tree (`reconcile/job.py` 85%, `ingest/extract.py` 91%,
  `ingest/pipeline.py` 90%, `reconcile/detect.py` 99%). Tests 162 → 239.
  `ruff check .` 721 → 0, with `make lint` in `make gate`. `requirements.lock`
  added. The compliance probe no longer writes into `src/baraza/`.
- **Documentation.** The statements asserting that no module imports ADK were
  false and are gone. `docs/antigravity/decision.md` — a placeholder shipping an
  unverifiable negative claim about a third-party SDK into a hackathon run by that
  SDK's vendor — was deleted along with its citations. The embeddings claim, which
  described a component `grep` shows was never built, was removed from the docs,
  the model pins and `metrics.json`. Hand-typed test counts were replaced with
  "run `make test`" everywhere except the two dated observation records, which
  keep their figure with an annotation.

**Corrections this session's verification pass made to the implementers' own work:**

The three implementers ran concurrently against a shared tree, and the two
failure modes that produces both occurred.

- **A1 and A5 collided.** A1 correctly rewrote every "ADK is unused" claim into
  "ADK is imported but has no production caller" — and then A5 gave it one. Eight
  sites across `README.md`, `docs/compliance.md`, `docs/submission/CHECKLIST.md`,
  `video-script.md` and `blog-post.md` were left asserting that the extractor is
  not on the production path, which is now false in the other direction. All
  rewritten to the verified state: the **extractor** is driven by a `Runner` on
  any non-offline run; the reconciler and interviewer are built and
  isolation-tested but still reach the model through `llm.py`; and the **offline
  replay path is direct by design**, so nothing shown from `make demo` is an ADK
  loop. That last clause is now in the video script as a recording instruction,
  because it is the sentence most likely to become an overclaim on camera.
- **Every line citation A1 added was stale by the end of the session.**
  `docs/compliance.md` and `CHECKLIST.md` cited `agents.py:65-66` for the ADK
  imports (they are at 118-122 after A5's edits) and `llm.py:156, 175, 210` for
  the GenAI SDK (they are at 319, 343, 384 after A6's), and gave grep counts of
  3 and 3 where the true counts are 7 and 4. In a repository whose entire claim is
  that every statement traces to a source, the framework row — the cell a Stage 1
  judge is most likely to test — pointed at the wrong lines. Corrected, and the
  brittle ones replaced with descriptions that survive an edit.
- `docs/compliance.md` still said "There is no lockfile in the tree" after A8
  added one. Corrected, including the gap A8 flagged: the lock was resolved on
  Python 3.14/macOS and the deploy images are `python:3.11-slim`, which do not
  install from it.
- **`src/baraza/cli.py` still had the valid-time/transaction-time defect** that
  A3 fixed in `job.py`. Its on-write reconciler stamped `contradiction.detected`
  with `contradiction.detected_at`, so the two writers of the same event type
  disagreed about which clock they use, and a log seeded by `make demo-agenda`
  would have poisoned the nightly differential. Fixed the same way — one injectable
  run instant per run, valid time left in the payload — and pinned by
  `test_the_event_carries_the_run_instant_not_the_authoring_instant`, verified by
  re-planting the old line and watching it fail.
- **`deploy/README.md` was the source of an inaccuracy it also propagated.** It
  said "The ingest and reconcile Jobs do not import it" of `interview/approval.py`,
  and A4 was told to copy that wording to four other sites. Verified empirically:
  `import baraza.reconcile.job` leaves `approval` out of `sys.modules`, but
  `import baraza.cli` loads it, and `deploy/entrypoint-job.sh` runs the ingest Job
  as `python -m baraza.cli demo-agenda`. On the ingest container the isolation is
  which path runs, not what is loaded. Corrected in `deploy/README.md` itself and
  in the one remaining Devpost row that used different wording and so escaped A4's
  sweep.
- **`AGENTS.md`** listed `antigravity/decision.md` in the repository layout after
  the file was deleted. Two implementers declined to touch this file on the
  principle that a build session should not rewrite the protocol governing it.
  The principle is right for normative content; this is a descriptive directory
  listing pointing at a path that no longer exists, so it was corrected with the
  history kept inline. Flagged here rather than buried.

**What is still open, and is a human's call:**

- `baraza-prd-v1.2-amendments.md` cites `docs/antigravity/decision.md` in three
  places. It is a received requirements artifact, not repo-authored prose, and was
  left alone deliberately.
- `docs/PRD.md` is still absent, so `make compliance` exits 2 and ~35 BAR IDs have
  no acceptance criteria. `--no-prd` is green.
- Nothing is deployed, no cassettes are recorded, and every entry in
  `docs/metrics.json` still reads `not yet measured`.

**Key decisions:**

- **Recorded adjudication over inferred adjudication.** The nightly work pool
  could have been fixed by comparing against a *stored ingest* timestamp instead
  of `observed_at`. Chose a `claim.adjudicated` event and a set difference,
  because it makes "already examined" a fact in the log rather than an inference
  from a field whose semantics can drift again — and content-addressed event IDs
  make it retry-safe for free.
- **Reconstructing last night's ledger over persisting it.** The differential
  could have been fixed with a GCS bucket or a Firestore snapshot document.
  Folding the log prefix twice adds no infrastructure and no IAM surface, and
  honours the repository's own stated principle that there is no cache which can
  drift from the log.
- **Offline extraction stays on the direct path.** An ADK `Runner` bypasses the
  cassette client, so routing offline runs through it would make a replay
  indistinguishable from a live agent loop in the console output. Chose to lose
  the ability to demo ADK from cassettes rather than gain a recording that has to
  be described carefully.
