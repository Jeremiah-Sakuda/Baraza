# Baraza

> **Every May, thousands of organizations forget everything.**

Baraza is succession intelligence: it reads years of an organization's accumulated
mess — chat exports, a skew-scanned constitution, headerless budget sheets, meeting
minutes — and asks the corpus what it disagrees with itself about. It turns those
disagreements into a ranked ledger and an interview agenda no human wrote, then
conducts the exit interview with the departing officer, holding their testimony
against the documentary record and naming the divergence in the moment it appears.
Approved answers become committed memory with an explicit visibility choice, and a
resolved question retires itself, so the next interview is shorter than the last.

---

## The friction

Officer turnover is annual and total. The handover is a document written at 1 a.m.
by someone who has already mentally left, and it contains the things that were easy
to write down.

What it does not contain is where the institution actually lives:

- The chat thread with four years of decisions in it, which nobody has ever exported.
- The constitution, scanned crooked in some prior year, amended twice since in
  minutes that were never folded back into it.
- The budget workbook whose header row was deleted at some point and never restored,
  so column `B` means something only to a person who no longer answers email.
- The three separate answers to "who can sign for the account", each of which was
  true at a different time, none of which is dated in the place you would look.

The incoming officer inherits an account and a calendar and no way to tell a settled
fact from a contested one. The failure is not that the records are missing. It is
that they disagree, nobody has ever compared them, and the one person who could
reconcile them leaves in May.

Baraza does the comparison before that person leaves, and asks them about the
specific places the record fights itself — with citations on both sides.

---

## How it works

### The append-only log, the fold, the graph

There is no mutable graph store. Every write is an event appended to a log —
`claim.asserted`, `claim.adjudicated`, `contradiction.detected`, `claim.committed`,
`claim.rejected`, `claim.visibility_set`, `entity.alias_linked`, `session.turn`,
`heartbeat`. Event IDs are content hashes, so a Cloud Run Job that dies halfway and
is retried appends nothing twice.

`claim.adjudicated` is the nightly reconciler recording which claims it has already
examined, and it is worth a sentence because of what it replaced. The job used to
work out its own backlog by comparing `claim.observed_at` against the previous
heartbeat — but `observed_at` is the instant the *source document was authored*, not
the instant the claim was written, and the corpus starts in 2016. Every claim was
older than every heartbeat, so once one night had run the filter selected the empty
set on every night after it: the job exited 0, made zero model calls, and found
nothing, forever. The fix was not a better timestamp. It was to stop inferring and
let the log carry the fact, which is what the rest of the system already does.

Every rendered graph state is a **fold** over that log (`src/baraza/fold/graph.py`).
There is no cache that can drift from the log and no code path that mutates a graph
state in place. If a graph looks wrong, the log is the truth and the fold is the bug.
Fixing bad data means appending a superseding event, never editing one. In
production, `create()` is the only write verb the store exposes and the Firestore
security rules reject update and delete at the database level, so an application bug
cannot mutate history even if it tries.

The fold is deterministic because events are ordered by `(occurred_at_millis,
event_id)` — integers, never strings. That is the whole reason a permutation test on
serialized UTC offsets can assert a byte-identical graph.

### Contradiction detection on write, and the arithmetic that forces it

A decade of a student organization's records yields on the order of **3,000 claims**.
That is the design assumption; the measured count for this corpus is `not yet
measured` (`docs/metrics.json`, key `claims_extracted_total`).

An all-pairs contradiction sweep over 3,000 claims is

```
3000 × 2999 / 2  =  4,498,500 comparisons
```

At one model call per comparison, that is not a system, it is a bill. Batching does
not save it either — it changes the constant, not the 4.5 million.

So detection is **on write and blocked** (`src/baraza/reconcile/detect.py`):

1. A claim is asserted.
2. Retrieve only claims sharing its **blocking key** — subject entity ∪ object
   entities ∪ `predicate_hint`, with alias edges resolved at query time. Typical
   block size in this corpus is single digits.
3. **Temporally gate** the block on epoch interval overlap. Two claims about
   consecutive fiscal years cannot contradict each other; this gate removes the
   largest single source of false positives before any model sees them.
4. Cap the survivors at `MAX_RETRIEVED = 20`, ranked by recency and confidence.
5. Make **one** call — roughly 3k tokens — asking which of the retrieved claims
   actually conflict with the new one.

That is **one bounded call per claim written**, not one per pair. Three thousand
claims cost three thousand bounded calls instead of four and a half million, and the
cost per write does not grow with corpus size — it is capped at 20 retrieved claims
by construction, not by hoping the blocks stay small.

The sweep is not an optimization we skipped. It is a design we refused.

### The visibility boundary

This is the headline property, and it is the one that fails open if you are careless.
So it is structural, not conventional.

- `visibility` is set at append time and is never unset. A claim built without one is
  `private` — the tier that leaks nothing.
- `readable_by(claim, audience)` is defined **once**, in
  `src/baraza/schema/visibility.py`. Divergence detection, the ledger, the agenda,
  the interviewer's question renderer, the graph view and successor mode all route
  through that one predicate.
- A claim's quote is **not a readable attribute**. It lives behind
  `claim.quote_for(audience)`. Code that writes `claim.quote` raises `AttributeError`
  at the access site instead of quietly rendering private testimony to the wrong
  reader. `scripts/compliance.py` fails the build if anything outside
  `src/baraza/schema/` so much as mentions the protected field.
- The predicate **fails closed on bad input** — an unknown audience, an unknown
  visibility, a missing attribute all return `False` rather than raising, because a
  boundary that raises can be caught and swallowed by a caller trying to be robust,
  and the swallowed exception path is where leaks live.

The reconciler is allowed to **count** a claim the reader cannot see toward a
contradiction's existence. It is never allowed to render that claim's text into a
question for that reader. Those are two different operations, and `RedactedClaim`
is the only thing that crosses between them: structural coordinates, no quote, no
object literal, no anchor text.

An agenda item whose sides the interviewee cannot read is **downgraded, not
dropped** — it survives as an open-ended prompt with no quotes attached. Dropping it
would let the boundary silently shrink the agenda, which would make the visibility
choice look free when it is not.

### Epoch temporal normalization

Every temporal comparison in the system operates on integer epoch milliseconds, UTC
(`src/baraza/schema/temporal.py`). ISO-8601 is a serialization format and is never a
comparison key. Sorting or comparing instants as strings is prohibited outright, and
`make compliance` lints for the pattern.

This is a ported defect class, not a style preference. In a sibling project an
ISO-string sort inside a `resolve()` function let a revoked grant stay active under
mixed UTC offsets while byte-stability tests stayed green. The pair that actually
diverges has to cross a date boundary:

| a | b | string order says | instant order says |
|---|---|---|---|
| `2026-05-01T20:00:00-05:00` | `2026-05-02T00:00:00Z` | `a < b` | `a > b` |

`a` is 2026-05-02T01:00Z — one hour *after* `b` — but sorts before it as text. The
corpus plants exactly this pair, the manifest lists it, and the fold-stability
property test names it.

Naive datetimes and offsetless ISO strings are rejected loudly at the parse site
rather than guessed at. A wrong instant is a silent correctness defect; a raised
error is a loud one.

Full detail, with a rendered diagram: **[`docs/architecture.md`](docs/architecture.md)**.

---

## Spin up

### Offline, no credentials, no GCP project

```bash
git clone <repo-url> baraza
cd baraza
make install     # creates .venv, installs the package with dev extras
make demo        # ingest -> agenda -> replay interview -> successor query
```

`make demo` runs entirely on your machine. The event log is a local append-only
JSONL file (`JsonlEventStore`), and model responses come from **recorded cassettes**
in `fixtures/cassettes/` — real captured Vertex responses replayed by prompt hash,
not hand-authored text. If a cassette is missing for a prompt, the offline client
raises rather than inventing a response, and it does not silently fall back to a
stub. Nothing in the offline path touches the network.

> **Precondition, and it is not met yet:** `fixtures/cassettes/` holds no recordings
> in the current tree, so `make demo` stops before doing any work and tells you so
> with the reason. Recording the
> cassettes runs the whole demo once against live Vertex
> (`python3 scripts/record_cassettes.py --yes`) and costs money, which makes it a
> supervised step rather than an overnight one. Until those recordings are committed,
> the offline path does not run on a clean clone. See the status table below.

`make demo-agenda` and `make demo-interview` run offline under the same conditions;
all three targets pass `--offline`. Add `REPLAY=1` to feed the interview canned
answers on a timer, and `PERSONA=terse` (or `expansive`) to pick a fixture.

### Deployed

```bash
export BARAZA_PROJECT_ID=your-project-id
gcloud auth application-default login
make bootstrap   # APIs, Firestore + rules, per-stage service accounts, Jobs, Scheduler
make verify-models
make teardown    # removes everything bootstrap created; safe to run repeatedly
```

`make bootstrap` provisions least-privilege service accounts per stage. The
extraction stage's account **cannot** write a `claim.committed` event — not by
convention, by IAM. Only the approval path promotes a claim.

`make verify-models` resolves every pinned model ID against live Vertex and exits
nonzero on any that does not resolve. Until it has run green against the target
project, **no document in this repository states which model version shipped** —
including this one. That is why you will not find a model ID in this README or in the
architecture diagram: the pins live in `src/baraza/schema/models.py` and nowhere
else, and `make compliance` fails the build on a model-ID literal written anywhere
else in the tree.

### Status — every target run and observed, 2026-08-13

**Nothing below is inferred.** Each row is the exit code and message produced by
running that command against this working tree. The build proceeds in overnight
sessions, so this is a dated snapshot rather than a promise — **the last entry in
[`docs/BUILD-LOG.md`](docs/BUILD-LOG.md) is the authority on what has landed**, and
every target that is not yet wired exits nonzero rather than exiting 0 having done
nothing.

| Command | Observed |
|---|---|
| `python3 scripts/compliance.py --no-prd` | **exit 0, green.** All four invariant lints pass. |
| `make compliance` | **exit 2** — the audit could not run. `docs/PRD.md` is absent, and the amendments file forbids reconstructing it (see Disclosures). Exit 2 is deliberately distinct from exit 1, "found problems", and from exit 0. Because `make gate` runs this first, **the composite gate target is red too.** |
| `make test` | **exit 0, all green** — `tests/unit/` plus `tests/property/` (the fold-stability permutation test). Needs `make install` first; pytest lives in `.venv`. The count is deliberately not written here: this repository's whole claim is that nothing is typed into a document by hand, and a hand-maintained test count goes stale on the next commit. Run the target for the number. |
| `make corpus` | **exit 0** — 13 artifacts regenerated from `BIBLE.md`, every one re-read through `baraza.ingest.readers`. Exits 1 if any artifact fails or skips that round trip, so a missing reader dependency cannot pass as green. |
| `make verify-manifest` | **exit 2** — prints `found 18 of 18 planted problems`, then stops: no event log exists, so 0 of 17 behaviour probes could be observed. Plants present is not the same as plants caught, and the script refuses to conflate them. |
| `make verify-anchors` | **exit 2** — rebuilds the source registry from the bytes on disk (11 sources resolve) and then reports that there are no citations to verify, because no ingest run has happened. |
| `make demo`, `make demo-agenda`, `make demo-interview` | **exit 2** — refuses to start: `fixtures/cassettes/` holds no recordings. The message names the recorder and says why the offline client will not invent a response. **This is the single gap between here and a working clean-clone demo, and it is what blocks the two rows above from observing any behaviour.** |
| `make adaptation-metric` | **exit 1** — `fixtures/transcripts/` does not exist, so the scorer has nothing to score and says so instead of printing a zero. Transcripts come from replay runs and are never hand-authored, so this unblocks when the demo does. |
| `make verify-models` | **exit 3** — could not run: `BARAZA_PROJECT_ID` is unset and is deliberately not defaulted. No pinned model ID has been resolved against live Vertex. |
| `make test-emulator` | **exit 1** on this machine — no JDK, and the Firestore emulator is a JVM process. The script reports that rather than skipping quietly. The JSONL half of the SIGKILL rig does run without it: `pytest tests/emulator -k jsonl` → **1 passed**. |
| Agent framework (BAR-020) | **imported, instantiated, and driven by a `Runner` on the live ingestion path.** `src/baraza/agents.py` imports `LlmAgent`, `RunConfig`, `InMemoryRunner` and `FunctionTool` from `google.adk` (v2.6.2) and builds three real ADK agents with per-agent tool isolation; `tests/unit/test_agents.py` asserts `isinstance` against the genuine ADK class. `baraza.ingest.extract.AgentClaimExtractor` drives the extractor through an ADK `Runner` with `read_chunk` / `propose_claim` bound to the real validation gates, and `IngestionPipeline` selects it on any non-offline run — which is what `deploy/entrypoint-job.sh` invokes. What is *not* true: the reconciler and interviewer agents are built and isolation-tested but still reach the model through `src/baraza/llm.py`; and the **offline replay path is direct by design**, because an ADK `Runner` bypasses the cassette client and a replay must never be mis-narrated as a live agent loop. So `make demo` does not exercise ADK; `--no-offline` does. |

What is built: the schema (claim, event, session, contradiction, visibility, temporal,
model pins), the fold, the append-only store, the ingestion spine with all four
format readers, the reconciler, the interview engine, the approval flow, the successor
librarian and the CLI that wires them together — `find src -name '*.py' -print0 |
xargs -0 wc -l` for the current count. Also present: the generated synthetic corpus
and its manifest under `fixtures/`, the unit, property and emulator test suites under
`tests/`, the deploy manifests and Firestore rules under `deploy/`, and the bootstrap,
teardown, corpus-generation, manifest- and anchor-verification, cassette-recording,
model-verification and adaptation-scoring scripts under `scripts/`.

What is missing is what the table says is missing: the recorded cassettes that make
the offline demo run — and, downstream of them, every behavioural observation the
manifest and anchor verifiers exist to make — the generated transcripts, the merged
PRD, an ADK agent on the production call path, and any deployment at all.

A README that told you `make demo` works when it does not is the exact failure this
project spends a compliance script preventing. The reproducibility gate for the
offline path is 2026-08-25 (`docs/GATE.md`), on a clean clone on a different machine.

---

## The seven targets

These seven are the contract. Everything else in the Makefile is scaffolding.

| Target | What it does | What it proves |
|---|---|---|
| `make compliance` | BAR-007 PRD ID audit plus four invariant lints | That the invariants are machine-checked, not remembered. Orphan requirement IDs, dangling references, range notation in a matrix cell, a model-ID literal outside the pin module, a read of protected quote text outside the schema package, an ISO-string comparison, or a number in `metrics.json` without provenance each fail the build with a `file:line`. |
| `make demo` | Offline end to end: ingest, agenda, replay interview, successor query | That the whole system runs on a laptop with no credentials — and therefore that a judge can check any claim in this README themselves. |
| `make demo-agenda` | Cold ingest to disputed ledger and interview agenda, unattended | That the agenda is generated, not authored. Nobody types the questions; they fall out of what the corpus disagrees with. |
| `make demo-interview` | The interview loop; `REPLAY=1` feeds canned answers on a timer | That the interviewer is agenda-led, asks clarifying follow-ups, and names a divergence between testimony and record with both citations. |
| `make verify-manifest` | Prints `found N of N planted problems` **and the misses** | That detection is measured against a known-answer set rather than demoed on its best case. Printing the misses is the point; a detector that only reports its hits is a detector nobody can score. |
| `make verify-anchors` | Re-resolves every citation anchor against its registered source | That no citation is fabricated. An anchor that does not resolve, or whose source checksum has drifted, is a failure and not a warning. |
| `make adaptation-metric` | Standalone scorer over `fixtures/transcripts/`, no application imports | That the adaptation claim is independently checkable. The application emits labelled transcripts; a separate script computes the number, so the system never grades its own homework. |

Supporting targets: `install`, `test`, `test-emulator`, `test-all`, `verify-models`,
`corpus`, `bootstrap`, `teardown`, `gate`. Run `make help` for the split.

---

## Google Cloud

The hackathon's mandatory stack requires at least one Google agent framework and at
least one Google Cloud infrastructure service. Baraza uses several; the full mapping
with requirement IDs is in **[`docs/compliance.md`](docs/compliance.md)**.

| Service | Where it is used | State |
|---|---|---|
| **Agent Development Kit (ADK)** | `src/baraza/agents.py` builds the extractor, reconciler and interviewer as `google.adk.agents.LlmAgent` instances, each holding only the tools its role requires, with peer and parent transfer disabled so no reasoning agent can hand work to the approver. The approver is deliberately **not** an agent and has no model. `src/baraza/ingest/extract.py` drives the extractor through an ADK `Runner` with turn and wall-clock ceilings. | Imported, instantiated and **running the live extraction path** (`google-adk` 2.6.2); asserted by `tests/unit/test_agents.py` and `tests/unit/test_agent_extraction.py`. Reconciler and interviewer are built but still reach the model through `llm.py`; offline replay is direct by design |
| **Vertex AI** | Every model call in the system, through `src/baraza/llm.py`. Reasoning role: contradiction adjudication, agenda synthesis, the divergence turn, successor synthesis. Fast role: claim extraction over corpus chunks, entity alias proposals, interviewer follow-ups where first-token latency binds. | Implemented. Pins unverified until `make verify-models` runs green, and no response has been recorded yet |
| **Vertex AI (Gemma)** | The BAR-303 ingestion relevance pre-filter, keep-or-drop per chunk before any Gemini call, behind a `stub` / `gemma` flag. Unattended ingestion runs `stub`, disclosed as a stub in its docstring, in `metrics.json` and in the console output of any run that used it. | **Interface final; Gemma has never run.** The `gemma` branch calls `generate_content` while the pin declares `surface="vertex-endpoint"`, and `GemmaFilter.endpoint` is assigned and never read — a live run would fail open on every chunk. That is now stated rather than hidden: `FilterReport.failed_open` counts undecided keeps, a degraded pass prints `DEGRADED — the filter never ran` instead of `100.0%`, and `metrics_entry` returns `not yet measured`. The additional-model bonus is **not claimed** |
| **Firestore** | The append-only claim-event log, sessions and entities. Create-only writes; `deploy/firestore.rules` rejects update and delete at the database level. | Implemented, rules written; not yet deployed |
| **Cloud Run Jobs** | The ingestion Job and the nightly `baraza-reconcile` Job. Retry-safe because event IDs are content hashes. | Implemented and containerized (`deploy/Dockerfile.job`); not yet deployed |
| **Cloud Run services** | `src/baraza/interview/service.py` reads as `Audience.OWNER` and is not public. `src/baraza/successor/service.py` is the public surface a logged-out judge visits, and reads only claims that are committed **and** readable by `Audience.PUBLIC`. | Implemented, one image for both (`deploy/service-*.yaml`); not yet deployed |
| **Cloud Scheduler** | Nightly trigger for the reconcile Job (BAR-021), stood up early so execution history accumulates in real time. | Manifest written (`deploy/scheduler.yaml`); not yet deployed. `scheduler_nightly_runs_completed` is `not yet measured` |
| **Cloud Trace** | OpenTelemetry spans over the reasoning chain, from `src/baraza/telemetry.py`. A span carries a claim's `digest()` and never its quote — a trace backend is a second copy of everything you put in it, with its own retention and its own export path, and none of those route through `readable_by`. | Implemented; no deployed trace exists yet |
| **Cloud Storage** | Intended for corpus artifact staging for the deployed ingestion Job. | Declared in `pyproject.toml` and **not called from any code path**, so nothing in this repository claims it as used |

**Scheduled runs are labelled as scheduled.** Every event the nightly Job appends is
marked `scheduled=True`, and a Cloud Scheduler run is never counted as organic
activity in any accounting, anywhere — including the video and the submission
write-up.

---

## Negative decisions

Things deliberately not built. Each of these was live, and each was refused for a
reason that is arithmetic or a stated principle rather than a schedule.

**No vector database — and, in the end, no embeddings either.** Retrieval for
contradiction detection is exact-match blocking: subject entity ∪ object entities ∪
`predicate_hint`, with alias edges resolved at query time, then a temporal gate, then
a cap of 20 (`src/baraza/reconcile/detect.py`). Typical block size in this corpus is
single digits. A managed vector index would add a service, a schema, a sync path that
can drift from the log, and a new failure mode; an index earns its keep somewhere
north of a million vectors, and this is a few thousand claims.

The honest part of this entry is the second half. An embedding model *was* pinned in
`src/baraza/schema/models.py`, for "blocking-key expansion", and three documents
described it as a shipped component — while `grep -rn embed src/` returned only the
pin itself. It was never built and nothing called it. The pin and every claim
resting on it have been removed rather than retrofitted, because a repository whose
argument is that documented invariants must be mechanically checkable does not get
to describe a component it did not write. Embedding-based expansion of the blocking
key remains a reasonable thing to build; it is not in here.

**No real entity matcher.** A student organization has on the order of a hundred
distinct entities across a decade — officers, roles, accounts, vendors, events. The
alias problem is a few thousand candidate pairs, nearly all of which fall to
normalized string rules, leaving a residue small enough for one model call plus human
confirmation. The cardinality does not justify ML, and a learned matcher's failures
are the kind you cannot explain to the person whose institutional memory is at stake.
Unconfirmed proposals do not become edges.

**No destructive identity merges.** `sameAs` edges only; identity resolves at query
time through the fold's alias map. Both IDs stay in the log and in every claim that
used them. A wrong merge in a mutable store is unrecoverable; a wrong `sameAs` edge is
one superseding event away from being undone.

**No O(n²) contradiction sweep.** The arithmetic is above: 4,498,500 comparisons at
the design assumption, versus one bounded call per write. This one is worth naming as
a *refusal* rather than an optimization, because the sweep is the obvious
implementation and it demos fine on fifty claims.

**No voice, no TTS.** Cut unconditionally, and it stays cut even though a multimodal
prize category exists. It would have added a recording surface, a latency budget and a
failure mode to a product whose value is in what the text says, and the honest reason
to build it would have been the prize rather than the user.

**No enterprise deployment claims.** The market framing generalizes; the demo claims
stay scoped to a single organization's corpus. Baraza has not been run against an
enterprise records estate and this repository will not imply that it has.

**Considered and not adopted: feeding approval and edit deltas into the style profile
as a second adaptation mechanism.** It matches the literal language of the track
("captures feedback… constantly adapts") and it would have been straightforward to
build. It was rejected because it adds no verifiable property beyond the measured
metric that already exists: adaptation is already structural, already labelled per
turn, and already scored by a standalone script over committed transcripts. A second
mechanism that cannot be independently measured makes the claim louder and not truer.

---

## What is measured and what is not

Every number Baraza displays anywhere — this README, the architecture diagram,
console output, the video overlay — traces to an entry in
**[`docs/metrics.json`](docs/metrics.json)**, to a live query, or to a script you can
run. Nothing is typed into a document by hand.

An entry in that file is either the literal string `"not yet measured"` or an object
carrying `value`, `provenance`, `run_id` and `date`. There is no third form and no
placeholder estimate. `provenance` is one of `measured in-process`, `measured
deployed`, or `not yet measured` — an in-process timing is never reported as a
deployed measurement. `make compliance` fails the build on any entry that breaks that
shape.

**All 20 entries in `docs/metrics.json` currently read `not yet measured`, and the
`runs` array is empty.** That includes the corpus counts, the Gemma pre-filter
survival rate, the entity scorecard, contradiction precision against the planted
manifest, first-token latency, the adaptation depths per persona, and the Scheduler
run count. Nothing has been measured because nothing has been run end to end yet.
Entries reading `not yet measured` **have not been measured** — they are not
conservative estimates, rounded figures, or values awaiting confirmation. Check it
with `python3 -c "import json;print(json.load(open('docs/metrics.json'))['metrics'])"`.

Numbers that appear in this README and are *not* measurements:

- **3,000 claims** is a design assumption about corpus size, stated as such, used to
  derive the detection arithmetic. The actual count for this corpus is `not yet
  measured`.
- **4,498,500** and the 20-claim cap are arithmetic and a code constant
  (`MAX_RETRIEVED` in `src/baraza/reconcile/detect.py`). Both are checkable without
  running anything.
- **"thousands of organizations"** in the opening line is rhetoric. It is the only
  sentence in this file that asserts a quantity nothing in this repository counted,
  and it is flagged here rather than left to look like a finding.

---

## Disclosures

**Built with AI coding assistance.** This project was built with an agentic coding
assistant, which the hackathon rules explicitly permit. The assistant wrote the
majority of the code in this repository under a session protocol recorded in
`AGENTS.md`: overnight unattended sessions against mechanical phase gates, with
supervised review between them. Every session's opening prompt, verbatim course
corrections, outcome and key decisions are logged in
[`docs/BUILD-LOG.md`](docs/BUILD-LOG.md), and the toolchain observations — including
what degraded — are in [`docs/FINDINGS.md`](docs/FINDINGS.md). The design decisions,
the invariants and the refusals in this document are the author's; the typing was
largely not.

**The agent framework was chosen without a published comparison.** BAR-020
originally resolved the question by *citing* an Aug 8 negative finding from a sibling
project — a headless multi-agent assertion about another vendor's SDK that failed
verification. The source document was never copied into this repository, and what
stood in for it was a placeholder describing the finding from memory. That
placeholder has been deleted rather than filled in from memory or left standing: a
remembered paraphrase of evidence is not evidence, and an unverifiable negative claim
about a named vendor's product is not something this repository will publish just
because it would make a decision look better justified. So there is no framework
comparison here. ADK is used, it is genuinely imported and driven
(`src/baraza/agents.py`, `src/baraza/ingest/extract.py`), and the reason it was
picked over alternatives is not documented. `docs/framework-decision.md` says the
same thing at length. No framework is claimed anywhere in this repository that the
code does not import.

**Several defect-class guards are ported from a sibling project.** They are not
novel work and are not presented as such. The epoch-normalization rule (BAR-309)
exists because an ISO-string sort in that project's `resolve()` kept a revoked grant
active under mixed UTC offsets while byte-stability tests stayed green. The numbers
discipline — never a plausible number where a measured one belongs, never an
in-process timing reported as a deployed measurement, never a scheduled job counted
as organic traffic — is ported from the same place, where each of those was observed
rather than theorized. The early-Scheduler pattern (BAR-021) is ported too. What is
new here is the enforcement: the guards are lints in `scripts/compliance.py` that
fail the build, and they were verified by planting each violation and watching it
fire with a `file:line` before removing the plant.

**The PRD contract is incomplete.** `docs/PRD.md` is absent from this repository.
The amendments file carries full text for roughly fifteen requirement IDs; the
remaining approximately thirty-five exist only as identifiers with no acceptance
criteria, and the amendments file forbids reconstructing them. `make compliance`
exits **2** ("the audit could not run") rather than 0, so the gap reads as a gap
rather than as a pass. Any requirement whose acceptance criteria live only in the
unrecovered file is currently being satisfied against inference rather than against
a contract.

**Model output in the offline demo is replayed, not live.** `make demo` uses recorded
cassettes — real Vertex responses captured to `fixtures/cassettes/` with the model ID,
run ID and UTC date of the recording. Nothing in this repository fabricates model
output. A number derived from a cassette replay is a replayed measurement and says so
wherever it appears.

**No real people, organizations or data.** The corpus is fully synthetic, generated
from `fixtures/corpus/BIBLE.md` against `fixtures/MANIFEST.md`. No real person,
student, member, company or organization is named anywhere in this repository, its
fixtures, its tests or its video — and none is named as a bad actor.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).

---

*This September, mine won't.*
