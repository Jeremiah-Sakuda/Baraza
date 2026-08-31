# FINDINGS.md

Measured numbers and toolchain observations, appended per session with the date.
What the tools supported, where they fought the design, what the long-context
passes got right and wrong.

Admitting that something degraded is more credible than claiming everything
worked.

---

## 2026-08-13 — session B0

### The repository arrived without its own contract

`docs/PRD.md` was absent. `baraza-prd-v1.2-amendments.md` amends a v1.1 file
that is not in the tree, and its §6 integration instruction ends with an
explicit stop condition: *"if any is missing from the v1.1 file itself, STOP per
§2.5.2 — do not reconstruct."*

Roughly fifteen requirement IDs have full text in the amendments. The remaining
~35 — BAR-001/002/004/006, 101/102, 301–308, 321–323, 331–336, 338, 340, 411,
501, 505, 506, 601–608, 620–624 — exist in this session only as identifiers with
no acceptance criteria.

**What was done about it:** the substrate was built anyway, because none of it
depends on the unrecovered sections — the hard constraints in AGENTS.md and the
amended requirement text fully specify the schema, the fold, the boundary, and
temporal normalization. `make compliance` distinguishes exit **2** ("the audit
could not run") from exit **1** ("the audit found problems") so the gap reads as
a gap rather than as a pass. Nothing was reconstructed.

**What this costs:** any requirement whose AC lives only in v1.1 is currently
being satisfied against inference rather than against a contract. That is a real
and unquantified risk, and it is the single highest-value thing to close.

### The visibility boundary was made structural rather than conventional

The first design had `Claim.quote` as an ordinary attribute with a `readable_by`
call expected at each read site. That is a boundary held by discipline, and the
requirement says it must hold under carelessness.

Changed to: the text lives in `_quote_protected` and is reachable only through
`quote_for(audience)`. Code that writes `claim.quote` now raises `AttributeError`
at the access site rather than returning private testimony. `scripts/compliance.py`
fails the build if `_quote_protected` appears anywhere outside
`src/baraza/schema/`.

The cost is real and worth naming: serialization has to reach through the same
door, so `to_dict()` lives inside the schema package and every consumer of the
raw dict is trusted. That is a smaller trusted surface than "every read site",
but it is not zero.

### The compliance lints were verified by planting violations, not by reading them

A lint nobody has seen fail is a lint that might not work. All three structural
lints were confirmed by writing a file containing a model-ID literal, a
`_quote_protected` access, and an ISO-string sort, running the audit, and
checking that each was reported with a file:line. All three fired; removing the
file returned the audit to green.

The first version of the model-pin regex produced a false positive on the word
"Gemini" opening a docstring. Requiring a `-<digit>` version suffix fixed it.
Worth recording because the failure mode of an over-broad lint is that someone
adds an allowlist entry and the lint quietly stops covering the real case.

### BAR-309's trap needed a real example, and the obvious one is wrong

The intuitive illustration — `09:00-05:00` vs `08:00Z` — does **not** diverge:
string order and instant order agree, and a test built on it would pass for the
wrong reason.

A pair that genuinely diverges crosses a date boundary:

| a | b | string says `a<b` | instant says `a<b` |
|---|---|---|---|
| `2026-05-01T20:00:00-05:00` | `2026-05-02T00:00:00Z` | **True** | **False** |

`a` is 2026-05-02T01:00Z, one hour *after* `b`, but sorts before it as text.
This is the pair planted in the corpus manifest and named by the fold-stability
property test.

### Not yet measured

Nothing in `docs/metrics.json` carries a value. Every entry is the literal
string `"not yet measured"`, which is the correct state before any run has
happened.

### Toolchain observations

- Model IDs are **pinned but unverified**. `scripts/verify_models.py` resolves
  every pin against live Vertex and exits nonzero on any that does not. Until
  that has run green against the target project, no document in this repository
  may state which model version shipped. A pinned literal nobody checked is a
  plausible value where a verified one belongs.
- ADK and GenAI SDK version floors in `pyproject.toml` are floors, not verified
  compatible sets. First `make install` on a clean machine is the check.

---

## 2026-08-13 — session B3 (verification pass over six parallel lanes)

### The counts, so they are not re-derived later

Every line below is the output of a command run in this session, on macOS 24.6
under CPython **3.14.5** — not the 3.11 floor `pyproject.toml` declares, which
is itself a finding: the floor has never been exercised.

> These are **B3's** numbers and are left as recorded rather than edited forward;
> a findings file that quietly updates its own observations is not a findings
> file. Later sessions added tests and closed some of the gaps below. For the
> current figures, run the commands — `make test`, `make verify-manifest`. Where
> a bullet's claim has since stopped being true, it carries a dated update
> underneath it rather than a rewrite.

| Command | Result |
|---|---|
| `import` every module under `src/baraza/` | 38 of 38, no credentials needed |
| `scripts/compliance.py --no-prd` | exit 0, four lints green |
| `pytest tests/unit tests/property -q` | **154 passed**, 2.4 s |
| `pytest tests/emulator -k jsonl` | 1 passed (a real `SIGKILL`) |
| `bash -n` on all six `.sh` files | clean |
| `make corpus` | exit 0, 13 artifacts, 11 sources round-tripped |
| `make verify-manifest` | exit 2 — `found 18 of 18 planted problems`, 0 of 17 behaviours |
| `make verify-anchors` | exit 2 — 11 sources registered, 0 citations to resolve |
| `make demo` / `demo-agenda` / `demo-interview` | exit 2, no cassettes |
| `make adaptation-metric` | exit 2, no transcripts |
| `make verify-models` | exit 3, `BARAZA_PROJECT_ID` unset |
| `make test-emulator` | exit 1, no JDK on this machine |
| `ruff check src scripts tests` | 706 findings, all `UP`/`I`/`SIM` |

### Six lanes agreed on the interfaces and disagreed about the tree

The parallel build produced **no** import errors, no duplicate definitions of
anything load-bearing (`readable_by`, `to_epoch_millis`, `Visibility`, `Tier`
and `EventType` each have exactly one definition), and no call to a function
that does not exist — checked by walking every module-qualified attribute access
in `src/`, `scripts/` and `tests/` against the imported module.

Where they diverged was on *state*. Four documents and one shell script were
written against a tree that a sibling lane changed underneath them: the README's
status table, `docs/architecture.md`, `docs/submission/CHECKLIST.md` §J and the
video script's preconditions all still asserted that `cli.py`, both verifier
scripts, `fixtures/`, `tests/`, `deploy/`, `LICENSE` and `README.md` did not
exist. They did. This is the cost shape of parallel agents that is worth
recording: the code interfaces held, and every prose claim about *what exists*
decayed within one session.

The mechanical lesson is that a status claim needs the same discipline as a
number. `docs/metrics.json` cannot drift, because a lint enforces its shape. A
sentence saying "`scripts/verify_manifest.py` does not exist" has no such guard,
and four of them shipped.

### The one that would have shipped green: a target that verified less than it said

`make corpus` prints a round-trip check — every generated artifact re-read
through `baraza.ingest.readers`. On an interpreter without `python-docx` it
printed six `SKIPPED` lines and then `13 artifacts. Verify the plants with: make
verify-manifest`, and exited **0**.

The docstring on that function already said the right thing — *"Readers whose
parser is not installed are reported as skipped, never as passed"* — and `main`
ignored it. The failure was one return value, and it was reachable by the
documented path, because `PY ?= python3` meant `make install && make corpus`
installed the readers into `.venv` and then ran the corpus generator under the
system interpreter. Both are fixed; the pairing is the finding. A degraded
dependency plus a default that picks the wrong interpreter turns "verified" into
"printed a verification".

### The deploy lane and the ingestion lane never spoke

`deploy/entrypoint-job.sh` ran `python -m baraza.cli ingest --manifest
fixtures/MANIFEST.md`. Three things wrong in one line: there is no `ingest`
subcommand (`demo`, `demo-agenda`, `demo-interview`), there is no `--manifest`
flag (`--corpus`), and `fixtures/MANIFEST.md` is the *landmine* manifest while
the corpus index is `fixtures/corpus/corpus-index.json` — two documents that
share a word and nothing else.

Its guard checked `import baraza.cli`. That guard passed the moment the
ingestion lane landed the module, so the Job would have died on an argparse
usage string with exit 2 rather than the exit **78** the deploy README promises.
A guard that tests a proxy for the thing it cares about stops working at exactly
the moment the proxy becomes true.

### What is still unobserved, and it is most of the product

`fixtures/cassettes/` is empty. That single fact is upstream of every
behavioural claim in the repository:

- `make verify-manifest` can say all 18 landmines are **planted** and 0 of 17 have
  been **caught**. Those are different sentences and the script refuses to
  conflate them, which is the right call and also the reason the ledger, the
  agenda, the divergence turn, the approval path and the successor refusal have
  never run end to end in this tree.
- `make verify-anchors` rebuilds the source registry from the bytes on disk —
  11 sources, checksummed — and then has zero citations to resolve.
- `fixtures/transcripts/` does not exist, so BAR-330's adaptation metric has
  nothing to score.

Recording the cassettes needs live Vertex credentials and costs money, so it is
a supervised step and could not be closed here. Everything else in the tree is
scaffolding around a loop that has not yet turned once.

### Toolchain observations

- **The Python floor is unexercised.** `requires-python = ">=3.11"`; this session
  ran 3.14.5. Nothing pins or tests 3.11, and the first `make install` on a
  3.11 machine is still the check — the same open item B0 recorded about the ADK
  and GenAI version floors, now with a second dimension.
- **`ruff` is a declared dev dependency and the tree does not satisfy its own
  config.** 706 findings under the `["E","F","I","B","UP","SIM"]` selection in
  `pyproject.toml`, of which 609 are auto-fixable. All of them are `UP`
  modernization (`typing.Dict` → `dict`, `Optional[X]` → `X | None`), import
  ordering, or two `SIM` simplifications. None is a correctness finding — the
  18 `F401` dead imports were the only `F` findings and were removed. There is
  no `make lint` target, which is why this went unnoticed; a config nothing runs
  is a config nothing enforces, the same shape as the invariants B0 moved into
  lints.
- **The Firestore emulator did not run.** `scripts/with_emulator.sh` correctly
  detects that `java` is on PATH but will not execute, prints "install a JDK (17
  or later)", and exits 1 rather than skipping quietly. Consequence: the
  Firestore-backed half of the SIGKILL rig is **unverified**. The JSONL half
  passes and it is a real `os.kill(pid, SIGKILL)` against a live child process,
  so the property — externalize the question before soliciting the answer — is
  demonstrated on one of the two stores.
- **Half the tree has no test.** `ingest/*` (all seven modules), `interview/`
  `replay` and `service`, `successor/service`, `cli`, `telemetry`,
  `reconcile/differential` and `reconcile/job` are referenced by zero test
  files. They are exercised only through the demo path, which cannot run. The
  passing tests cover the schema, the fold, detection, the ledger, the
  agenda, approval, retraction, the boundary off the demo path and temporal
  normalization — the invariants, which is the right priority, but a green
  suite should not be read as coverage of the product.

  **Update, 2026-08-13 (post-B4):** partially closed, and the cost of the gap
  was demonstrated rather than argued. `reconcile/job` now has
  `tests/unit/test_job.py`, written because *two* defects were found in that
  untested module — a work-pool filter that selected the empty set on every
  night after the first, and a differential that read last night's ledger from a
  container-local directory Cloud Run wipes between executions. Both were in the
  flagship autonomous path; either alone would have made the nightly job report
  success while doing nothing observable. One test over that module would have
  caught the first. The remaining modules in this list are still untested.
- **`docs/BUILD-LOG.md` has no entry for B1 or B2.** Both are in the commit
  history (`bc46324`, `cc89d72`); the session protocol requires the entry
  *before* the commit. Two of four sessions skipped it, and a verbatim opening
  prompt is not recoverable after the fact — so that record is permanently
  incomplete rather than merely late. `docs/compliance.md`'s originality row
  cited that log as evidence and has been amended to name the gap.

  **Update, 2026-08-13 (post-B4):** B4 skipped it too — three of five sessions,
  and the one that skipped it is the one that closed the mandatory
  agent-framework requirement. All three are now backfilled from
  `git show --stat` and their commit messages, each carrying a banner marking it
  as reconstructed after the fact, with the prompt and course corrections
  recorded as **not recoverable** rather than written from memory. The
  distinction the compliance row now draws is the right one: the log is complete
  on what landed and permanently incomplete on how the sessions were driven.
- **25 paths are untracked.** Everything B3's predecessors wrote outside
  `src/` — `tests/`, `fixtures/`, `deploy/`, `scripts/` bar `compliance.py`,
  `README.md`, `LICENSE` — is in the working tree and not in any commit. The
  three commits that exist contain `src/` only.

### Escalated at B3, resolved post-B4: the framework-decision citation

`docs/antigravity/decision.md` carried a **negative verification result about a
third party's SDK, restated from memory**, as the published basis of BAR-020's
framework choice. The source document was not in the repository. The substance of
that assertion is deliberately not repeated here, and has been removed from every
document that carried it — restating an unverifiable claim about someone else's
software in the file that flags it as a problem is still publishing it.

The finding sits against two rules at once — `AGENTS.md` §7 and BAR-020 require
the finding present *verbatim* as the basis of the framework decision, while the
standing prohibition is on carrying an unverifiable negative claim about a real
entity.

The file already argues for its own resolution: locate the original and attach
an attribution header, or delete the citation from BAR-020 and state plainly
that ADK was chosen without a published comparison. Neither is a change a
verification pass should make unilaterally, so it was left exactly as found and
is raised here. It is the only item in the tree where two of the project's own
rules point in opposite directions.

**Resolved, 2026-08-13 (post-B4): the second branch.** The original was not
recoverable from inside this repository, so the citation was deleted and
`docs/framework-decision.md` now says ADK was chosen without a published
comparison. Of the two rules in conflict, the one that gave way is the one whose
cost falls on this project — a weaker published justification — rather than the
one whose cost falls on a third party, which is an unverifiable negative claim
about their software in a submission judged by them. That ordering is the
finding worth keeping: when a repository's own rules disagree, the tie breaks
against the party who did not agree to the rules.

`AGENTS.md` §7 still names the file among the by-hand artifacts. It was left
unedited on purpose — a build session that rewrites the protocol governing it to
match its own output has stopped being governed by it. That line is now stale
and is the human's call to reconcile.

---

# Session B5 — 2026-08-13 (verification pass)

Every figure below was produced by running the command named next to it in this
tree on 2026-08-13. Nothing here is carried over from an implementer's report.

| Command | Result |
|---|---|
| `pytest tests/unit tests/property -q` | **229 passed** |
| `pytest tests/unit tests/property tests/integration -q` (`make test`) | **239 passed** |
| `coverage run --source=src/baraza -m pytest ...` | **63%** total, up from 36% at B4 |
| `scripts/compliance.py --no-prd` | exit 0, four lints green |
| `scripts/compliance.py` | **exit 2** — `docs/PRD.md` absent, unchanged |
| `ruff check .` / `make lint` | **0 findings**, down from 721 |
| `make corpus` | exit 0, 13 artifacts, 11 sources round-tripped |
| `make verify-manifest` | **exit 2** — 18 of 18 plants present, 0 of 17 behaviours |
| `make verify-anchors` | **exit 2** — no event log to resolve citations against |
| `make demo` / `demo-agenda` / `demo-interview` | **exit 2**, `fixtures/cassettes/` does not exist |
| `git log --oneline` | 5 commits, B0–B4. **B5's work is uncommitted** |

Coverage by the modules that matter, because the aggregate hides the point: the
autonomy path was at **0%** at B4 and is the reason both of this session's
structural defects survived to be found. It is now `reconcile/job.py` 85%,
`ingest/extract.py` 91%, `ingest/pipeline.py` 90%, `reconcile/detect.py` 99%,
`agents.py` 96%. Still at **0%**: `interview/service.py` (224 stmts),
`successor/service.py` (125), `telemetry.py` (54) — the entire HTTP surface,
including the service a judge would be handed a URL to.

## Findings

**A timestamp field with two meanings will be read with the wrong one, twice.**
Both structural defects this session fixed, and a third found while fixing them,
are the same mistake: a *valid-time* instant used where *transaction time* was
meant. `claim.observed_at` is when the document was authored; it was compared
against a heartbeat, so the nightly job selected nothing forever.
`Contradiction.detected_at` is `max(claim.observed_at)`, inheriting the same
semantics; it was stamped on the event, so every contradiction sorted before
every heartbeat and would have fallen into every differential baseline. The
corpus's 2016 start date is what makes all three fatal rather than merely
imprecise — a repository whose fixtures were dated last week would have shipped
this and seen it fail only in production. The general lesson is not "be careful
with time": it is that a field carrying an instant should carry which clock in
its name, and that the fix in both cases was to stop inferring and start
recording. `claim.adjudicated` is now a fact in the log; nothing has to guess.

**A test suite that passes while the thing it tests cannot work.**
`agents.py`'s `_guard` wrapped every tool in `*args, **kwargs` without
`functools.wraps`. ADK builds its tool declarations from `inspect.signature`, so
every tool reached the model declared as taking no parameters — the extractor
could not have received an anchor. Every isolation test passed throughout,
because they asserted over the *tool name set*, which the shim preserved
perfectly. The tests were checking the property the wrapper was written to
provide and not the property the framework needed. The repair that generalises is
the one applied: the isolation check now also asks a **capability** question —
a tool defined in a module that so much as references the promotion event type is
refused whatever it is called — so it is no longer satisfiable by naming.

**Concurrent agents against one tree fail in a specific, predictable way: they
leave the *documentation* inconsistent, not the code.** Three implementers ran
against this tree at once. The merged code was green on the first run; nothing
had to be untangled. What broke was every statement one agent wrote about
another agent's file. Eight sites still said the ADK fleet has no production
caller after the session that gave it one. Every line-number citation added in
the documentation pass was stale by the end of the session, including in the
compliance matrix's framework row — the single cell a Stage 1 judge is most
likely to test, pointing at the wrong lines in the file it cites. Two conclusions
worth keeping: **cite by symbol, not by line**, because a line number is a claim
about a file's current state that nothing re-checks; and a fan-out needs a
verification pass that greps for statements about *other* agents' work, because
that class of error is invisible to the test suite by construction.

**Deleting a claim is cheaper than defending it, and the cost is asymmetric.**
Three claims were removed this session rather than implemented: text embeddings
(documented as shipped, `grep` found only the model pin), the Antigravity
negative finding (a placeholder carrying an unverifiable claim about a
third-party SDK into a hackathon run by that SDK's vendor), and every hand-typed
test count. None of the three cost anything to remove and each was a standing
liability. The embeddings row is the sharpest instance: it violated the rule
stated at the top of the file that carried it.

**What the ADK work does and does not buy, stated so it cannot be overclaimed
later.** The extractor is genuinely driven by an ADK `Runner`, with tools bound
to the real validation gates and both cutoffs enforced, and `IngestionPipeline`
selects it on any non-offline run — which is what `deploy/entrypoint-job.sh`
invokes. The reconciler and interviewer are constructed and tool-isolated but
still reach the model through `llm.py`. And the offline path is direct **by
design**: an ADK `Runner` bypasses the cassette client, so routing replays
through it would make a recording indistinguishable from a live agent loop in the
console. The consequence is worth stating in advance of the recording session:
nothing filmed from `make demo` is an agent loop, and the run's own
`extraction path: adk-agent | direct` report line is the only honest way to show
which one is executing.

## Still open after B5

- `docs/PRD.md` absent; ~35 BAR IDs have no acceptance criteria; `make compliance`
  exits 2. Internal contract gap, not a hackathon requirement.
- `baraza-prd-v1.2-amendments.md` cites the deleted `docs/antigravity/decision.md`
  in three places. It is a received requirements artifact and was left untouched.
- `AGENTS.md` §7's by-hand-artifacts list still names that file. The repository
  layout in the same document was corrected, since it is descriptive rather than
  normative; §7 is normative and remains the human's call.
- The Dockerfiles do not install from `requirements.lock`. It was resolved on
  Python 3.14/macOS; the images are `python:3.11-slim`. Closing this needs a
  Docker build, which is why it is stated in the lockfile header rather than
  pinned blind.
- `tests/emulator` collect cleanly but cannot run here — no JDK.
- The two FastAPI services are at 0% coverage. The interview service is the
  surface a judge is handed a URL to.

## Addendum — the Gemma bonus is not claimable as things stand (2026-08-13)

Worth separating from the list above because it is the one item where the
temptation to overclaim is worth real money (+0.2 Stage 3) and the failure would
be invisible.

`GemmaFilter.verdict` reaches the model through `self.client.generate(role=
"prefilter", ...)`, which resolves to `generate_content`. The pre-filter pin
declares `surface="vertex-endpoint"` — a self-deployed Model Garden endpoint,
which is not addressed that way — and `GemmaFilter.endpoint` is assigned from
`BARAZA_GEMMA_ENDPOINT` in `__init__` and then read by nothing. So setting
`BARAZA_PREFILTER=gemma` most likely raises on every chunk.

The filter fails open by design, and that design is right: an outage must not
silently delete a night's institutional memory. But the *reporting* was wrong.
`FilterReport` counted only `kept` and `considered`, so a pass in which every
call failed printed `prefilter[gemma]: kept 33/33 = 100.0%  (gemma)` — the same
bytes a pass where Gemma read everything and kept it would print. A number that
cannot distinguish "the component ran and agreed" from "the component never ran"
is the exact defect the metrics-provenance rule exists to prevent, and it sat
directly under the claim the bonus is paid for.

Fixed by counting the thing that falsifies the claim rather than only the thing
that supports it: `FilterVerdict.decided` (explicit, not inferred from
`confidence == 0.0` — a genuine low-confidence KEEP and a failure to run are
different facts), `FilterReport.failed_open` / `decided` / `degraded`, a
`describe()` that prints `DEGRADED — the filter never ran. This is NOT a survival
rate`, and a `metrics_entry` that returns `not yet measured` for any pass with a
single fail-open. Five tests in `tests/unit/test_prefilter_degradation.py`,
including one asserting the guard does not swallow a clean measurement.

**The endpoint branch itself was deliberately not written.** It cannot be verified
without a live endpoint, and an unverified call path shipped to claim a bonus is
the same category of thing as the embeddings row that was deleted this session.
The choice is now a clean one for a human: implement the endpoint-aware call and
prove it with `make verify-models`, or delete the Gemma row from the README and
`compliance.md` and forgo the 0.2. Both documents now say which of those has
happened, which is neither.

## Judge-readiness repair findings — 2026-08-28

**A public read surface must not become a second rendering implementation.** The
new `/ledger` and `/agenda` pages use `DisputedLedger(...).rows(Audience.PUBLIC)`
rather than reconstructing claims from the fold. That keeps private text behind
the same `Contradiction.render_for` projection used everywhere else. The public
agenda is intentionally a deterministic preview: calling Gemini from a public
GET would turn a static judge page into an unbounded billing path and a new
non-deterministic disclosure surface.

**A green contract audit is not a green demo.** Restoring the ADK-aligned PRD
unblocked `make compliance`, but it does not manufacture cassettes, a live Vertex
run, or a successful Scheduler invocation. The repair updates the submission
documents to preserve that distinction rather than letting the new green target
be mistaken for product proof.

## Integration findings — the pivot build, seven lanes in parallel (2026-08-31)

**Disjoint file ownership does not make interfaces disjoint.** The lanes were
partitioned by file and every lane finished green in its own tests — and the
tree still did not run, because the seams live in the files nobody owned this
week. `src/baraza/cli.py` imported `AdaptationState` and `ReplayHarness` after
the interview lane deleted both, which failed collection for
`tests/integration/test_loop.py` — a test about *corpus ingestion* that had
nothing to do with the interview API except transitively importing it. The
lesson is old but was re-earned: a lane's definition of done ("my files, my
tests") is necessarily blind to every consumer it broke, and only a pass that
runs the whole tree finds the difference.

**A contract stated in a docstring is not a contract until something crosses
it.** The doctrine lane documented that rule wording comes from
`claim.extra["rule_text"]`, "authored at extraction," with a mechanical
fallback. The beliefs lane's extractor wrote `belief`, `turn_id`, and
`condition` into `extra` — and never `rule_text`. Both lanes were green: the
compiler's tests authored their own `rule_text`, the extractor's tests never
compiled anything. Every rule in a real doctrine would have rendered through
the fallback (`predicate: object literal`), which is legal, honest, and not
what either lane designed. Found only by the new
`tests/integration/test_dossier_loop.py`, which pushes one belief through
extraction, approval, the fold, and the compiler in a single process; fixed by
having extraction author the wording.

**Fixtures are code and they rot like code.** The old persona fixtures
(`terse.json` / `expansive.json`) were incompatible with the new
`load_script` shape, so `make demo` would have crashed on a `KeyError` deep in
a loader instead of stopping with a stated precondition — and their `_note`
fields explained the deleted pacing heuristic at length, in a tree whose
decision record bans mentioning it. Deleted and replaced with one
`PartnerScript`-shaped fixture. The general form: when an interface dies, grep
for the *data* that fed it, not just the symbols.

**`make` launders exit codes.** The metric scorer exits 1 (ran, red) versus 2
(could not run) deliberately — and `make adaptation-metric` reports 2 either
way, because GNU make's own failure exit is 2. The README's status table
claimed "exit 1" for a command a judge would run through make; corrected to
state both numbers. A status table of observed exit codes has to observe them
through the same invocation it prints.

**Environment drift is a lint category.** `ruff` failed on a
`\"` escape inside an f-string in `web/views.py` — valid on the Python 3.14
the venv runs, a syntax error on the 3.11 floor the project pins. The lane
that wrote it tested it green locally. The floor is only real where something
mechanical enforces it; ruff's `target-version` was that something, but only
in the lane that happened to run ruff over the file.

**What the seams got right.** The web lane's call-time symbol resolution
(`resolve_symbol` / `call_tolerant`) absorbed two breaking renames from
parallel lanes without an edit; the interview service picked up
`extract_beliefs` by name the moment it existed. And the honesty machinery
held end to end when run rather than read: `POST /sessions/open` on an empty
ledger answers 409 with a stated reason, `run_stub` labels
`session.proposed` with the true trigger under all three env states, and the
replay harness refuses to write a transcript for a run that made zero model
calls. Rule-compliance and determinism numbers remain not yet measured — the
scorer names the producer commands and stays red on purpose.

### 2026-08-31 (late) — the sixteen-day 403 was a one-byte diagnostic error

Full postmortem in `docs/deploy-postmortem.md`. The compressed finding: the
control experiment that "proved the service account could start the Job" posted
an empty body, so it exercised `run.jobs.run` while every real trigger needed
`run.jobs.runWithOverrides`. Two weeks of otherwise careful elimination
inherited that flaw. A verification that does not reproduce the failing input
byte-for-byte verifies a different claim — the verbatim-quote rule of this
codebase, applied to debugging.

Deploying also surfaced four defects invisible from the code: the gen2 memory
floor, two site-packages path resolutions (`REPO = Path(__file__).parents[2]`
is a checkout assumption a container breaks), and ADK constructing its own
GenAI client from `GOOGLE_*` env nothing set. First live contact remains the
cheapest audit this project has run.
