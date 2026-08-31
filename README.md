# Baraza — memory with due process

Every AI product is bolting on "memory," and every one of them is an opaque blob
the user can neither inspect nor correct. Baraza is a working partner whose every
belief about you is a **claim with a verbatim quote and a turn anchor**, appended
to a log that provably rejects edits. It catches you contradicting your own
guidance and makes you resolve it with both quotes on screen. It will not act on
any belief you have not ratified. Adaptation stops being a vibe and becomes due
process: you can open the file it keeps on you, see why every rule exists,
retract any of it — and the next session runs under the amended doctrine, with
every rule citing the claim that put it there.

The name is literal. A *baraza* is the council where disputes are heard on the
record. The dispute this one convenes is you-of-Tuesday versus you-of-Thursday.

---

## What it does

Six mechanisms, one substrate:

1. **It opens the session.** A scheduled reconcile pass ends by generating the
   agenda from open contradictions and stale beliefs, appends a
   `session.proposed` event honestly labelled `scheduled`, and notifies you. The
   session opens with the agent speaking first: a numbered plan, each item citing
   the ledger entry that spawned it. Initiation is proven by timestamps in an
   append-only log, not by a staged push.
2. **It takes notes you can audit.** Every preference, rule and judgment in your
   turns becomes a `Claim` — quote mandatory, anchor `turn:t-N`, fabricated
   anchor a stop condition — appended to a Firestore log whose deployed rules
   reject update and delete. Try the edit in the console; the rule refuses.
3. **It asks only earned questions.** A clarifying question exists because the
   disputed ledger says two of your own statements collide, or because a rule is
   too under-specified to compile. Both quotes render on the divergence card, and
   the agent refuses to silently overwrite the old rule until you adjudicate.
4. **It guides the work item by item.** The agenda state machine drives a real
   drafting session; a resolved contradiction retires its own agenda item, so
   session N+1 is shorter than session N and the retirement events link them in
   the log.
5. **Feedback is the approval gate.** No belief reaches `committed` — and
   therefore behavior — without you ratifying it through an approver that has no
   model. The Dossier view lists every belief with its quote and the moment it
   was learned; one click rejects, the retraction is itself an append-only
   event, and the same task reruns differently.
6. **It adapts on the record.** The doctrine compiler folds committed beliefs
   into the session's operating policy — same doctrine, every rule cited. The
   doctrine diff between epochs shows which belief changed which rule, by claim
   ID and quote.

---

## How it works

```
your turns ──► claims (quote + turn:t-N anchor)
                  │ append-only log (Firestore rules reject update/delete)
                  ▼
            fold over the log ──► disputed ledger ──► agenda
                  │                                     │
                  ▼                                     ▼
            DOCTRINE (committed beliefs only)     partner session
                  ▲                                     │
                  │        approval gate (no model) ◄───┘
                  └── claim.committed / claim.rejected
```

**Claims.** Extraction targets judgment shape — conditions, thresholds,
exceptions ("cite-first *unless* the recipient is internal") — not tone. A claim
without a resolvable anchor never enters the log; `make verify-anchors`
re-resolves every anchor against its registered source and fails on drift.

**The append-only log.** `create()` is the only write verb the store exposes,
and `deploy/firestore.rules` rejects update and delete at the database level —
verified live (`scripts/verify_append_only.sh`). Event IDs are content hashes,
so a retried job appends nothing twice. Fixing bad data means appending a
superseding event, never editing one. Every rendered state is a fold over that
log (`src/baraza/fold/graph.py`); there is no cache that can drift from it.

**Contradiction detection — on you, on write.** The same machinery that
reconciled an organization's records (`src/baraza/reconcile/detect.py`) now runs
with *you* as the subject. When a new claim lands, retrieval is exact-match
blocking on subject ∪ object entities ∪ `predicate_hint`, temporally gated on
epoch interval overlap, capped at `MAX_RETRIEVED = 20`, then adjudicated in one
bounded model call. The arithmetic is why: at the design assumption of ~3,000
claims, an all-pairs sweep is 3000 × 2999 / 2 = **4,498,500** comparisons —
a bill, not a system. On-write blocking makes it one bounded call per claim
written, and the cost per write does not grow with the corpus.

**The divergence card.** "On turn t-14 you said 'never send before I've seen
it' [quote]. Just now: 'just send the routine ones' [quote]. Which governs, and
what is 'routine'?" The agent will not pick a side for you. Adjudication often
splits the collision into a conditional — a judgment-shaped belief, not a
preference — and that belief goes through the gate like any other.

**The approval gate.** `claim.committed` is constructed in exactly one module,
`src/baraza/interview/approval.py`. The approver is deliberately **not** an
agent and has no model — promotion is the one operation that must never be a
model's judgment call. Approvals batch at session end. Rejection retracts
permanently: out of retrieval, out of the ledger, out of every future agenda.

**The doctrine.** The compiler folds committed beliefs into the session's
operating policy with a rule ← claim provenance map. Compilation is
deterministic — replaying the fold reproduces the doctrine byte for byte, under
permuted UTC offsets — and that claim is confined to compilation. Whether the
model then complies with a cited rule is measured, not asserted: the compliance
battery reports its number with provenance, imperfect if imperfect
(`docs/metrics.json`).

**Time is integers.** Every temporal comparison runs on integer epoch millis,
UTC (`src/baraza/schema/temporal.py`). ISO-8601 is serialization only; comparing
instants as strings is a defect class observed in a sibling project (it kept a
revoked grant active under mixed UTC offsets) and `make compliance` lints for it.

Full detail with the diagram: **[`docs/architecture.md`](docs/architecture.md)**.

---

## Spin up

Offline, no credentials, no GCP project:

```bash
git clone https://github.com/Jeremiah-Sakuda/Baraza.git baraza
cd baraza
make install     # creates .venv, installs from requirements.lock
make demo        # ingest -> agenda -> replay session -> dossier query
```

`make demo` runs entirely on your machine: a local append-only JSONL event log,
with model responses replayed from **recorded cassettes** — real captured Vertex
responses replayed by prompt hash, never hand-authored text. If a cassette is
missing, the offline client raises rather than inventing a response.

> **Honest precondition:** until recorded cassettes are committed under
> `fixtures/cassettes/`, `make demo`, `make demo-agenda` and `make demo-interview`
> exit **2** before doing any work and say why. Recording them
> (`python3 scripts/record_cassettes.py --yes`) runs once against live Vertex and
> costs money, which makes it a supervised step. The status of every target is
> observed and dated below; **[`docs/BUILD-LOG.md`](docs/BUILD-LOG.md) is the
> authority on what has landed since.**

Deployed:

```bash
export BARAZA_PROJECT_ID=your-project-id
gcloud auth application-default login
make bootstrap   # APIs, Firestore + rules, per-stage service accounts, Jobs, Scheduler
make verify-models
make teardown    # removes everything bootstrap created; needs CONFIRM=--yes-destroy
```

`make bootstrap` provisions least-privilege service accounts per stage; only the
approval path promotes a claim. `make verify-models` resolves every pinned model
ID against live Vertex and exits nonzero on any that does not.

### Status — observed on this tree, 2026-08-31 (post-integration pass)

Each row is the exit code produced by running the command, not an inference.
This snapshot was taken after the pivot's workstreams landed and were
integrated; re-run any row before quoting it. `make gate` chains the
compliance, lint, test, and verification targets; today it stops at
`verify-anchors` for the same stated reason as the rows below — no cassettes,
so no event log to verify against.

| Command | Observed |
|---|---|
| `python3 scripts/compliance.py --no-prd` | **exit 0** — all four invariant lints green |
| `make compliance` | **exit 0** — BAR-007 PRD audit plus the lints, green |
| `make test` | **exit 0** — unit, property and integration suites pass; run it for the current count |
| `make demo` / `demo-agenda` / `demo-interview` | **exit 2** — refuses to start: `fixtures/cassettes/` holds no recordings, and the offline client will not invent one |
| `make verify-manifest` | **exit 2** — every plant present, zero behaviour observed: no event log exists yet |
| `make verify-anchors` | **exit 2** — sources re-register from bytes on disk; no citations to verify until an ingest run happens |
| `make adaptation-metric` | **red on purpose** (the scorer exits 1; `make` reports that as exit 2) — it names each missing input (the determinism replay and the battery outputs `make battery-run` must record) and the exact command that produces it, instead of printing a zero |

A README that told you `make demo` works when it does not is the exact failure
this project spends a compliance script preventing.

---

## The seven targets

These seven are the contract. Everything else in the Makefile is scaffolding.

| Target | What it proves |
|---|---|
| `make compliance` | The invariants are machine-checked, not remembered: PRD ID audit plus lints for a protected-quote read outside the schema package, a model-ID literal outside the pin module, an ISO-string instant comparison, and a metrics entry without provenance — each failing with a `file:line`. |
| `make demo` | The whole loop runs on a laptop with no credentials, so a judge can check any claim in this README themselves. |
| `make demo-agenda` | The agenda is generated, not authored. Nobody types the questions; they fall out of what the record disagrees with. |
| `make demo-interview` | The session is agenda-led and names a divergence with both citations; `REPLAY=1` feeds canned answers on a timer. |
| `make verify-manifest` | Detection is scored against a known-answer set and **prints its misses** — a detector that only reports hits cannot be scored. |
| `make verify-anchors` | No citation is fabricated. An anchor that does not resolve, or whose source checksum drifted, fails rather than warns. |
| `make adaptation-metric` | The adaptation claim is independently checkable: a standalone script with no application imports computes the two honest numbers — the doctrine determinism replay and the rule-compliance battery — so the system never grades its own homework. |

Supporting targets: `install`, `test`, `test-emulator`, `test-all`,
`verify-models`, `corpus`, `battery-run`, `bootstrap`, `teardown`, `gate`. Run
`make help`.

---

## Google Cloud

The mandatory stack: at least one Google agent framework and at least one Google
Cloud service. The full mapping with requirement IDs is in
**[`docs/compliance.md`](docs/compliance.md)**.

| Service | Where it is used |
|---|---|
| **Vertex AI** | Every model call, through `src/baraza/llm.py`. Reasoning role: `gemini-3.7-flash`. Fast role: `gemini-3.5-flash`. Location: `global`. These three were **live-verified 2026-08-31** against project `baraza-2026` — the same resolution `make verify-models` performs — after the original pins turned out to name a model that does not exist in the catalog. That is why model IDs appear in this table and nowhere else in this file: the pins live in `src/baraza/schema/models.py`, everything resolves through `models.resolve(role)`, and `make compliance` fails the build on a literal written anywhere else in the source tree. |
| **Agent Development Kit (ADK)** | `src/baraza/agents.py` builds the extractor, reconciler and interviewer as `google.adk.agents.LlmAgent` instances with per-agent tool isolation and transfer disabled. The extractor runs on the live ingestion path through an ADK `Runner`. The approver is deliberately not an agent and has no model. The offline replay path is direct by design, so a replay is never mis-narrated as a live agent loop. |
| **Firestore** | The append-only event log. Create-only writes; `deploy/firestore.rules` rejects update and delete at the database level — **deployed and verified live** (`scripts/verify_append_only.sh`). |
| **Cloud Run** | Three surfaces: the private session service (`src/baraza/interview/service.py`, reads as owner), the public dossier surface (`src/baraza/dossier/service.py` — a logged-out judge sees only claims committed **and** readable by `Audience.PUBLIC`), and `baraza-trigger` — the OIDC-guarded hop that lets Scheduler start the reconcile Job after the direct Scheduler→Jobs-API path 403'd (root cause and fix recorded in `STOPPED-DEPLOY.md`). Plus the ingestion and reconcile Cloud Run Jobs, retry-safe because event IDs are content hashes. |
| **Cloud Scheduler** | The scheduled initiation trigger. Every event a scheduled run appends is labelled `scheduled=True` and is never counted as organic activity, anywhere — including the video. |
| **Artifact Registry, Cloud Build** | Container images for the Jobs and services, built and pushed by `make bootstrap` / `deploy/cloudbuild.yaml`. |

---

## Negative decisions

Things deliberately not built. Each was live, and each was refused for a stated
reason rather than a schedule.

**No silent belief overwrite.** When two committed rules conflict, the doctrine
compiler refuses to pick between them. The conflict becomes a divergence card
and an agenda item; only your adjudication — an append-only event — resolves it.
A partner that silently absorbs your latest contradiction isn't adapting to you;
it's erasing you.

**No output-causality claims.** The demo artifact is a *doctrine diff* — honest,
because the compiler emits rule ← claim provenance — plus before/after output
pairs on a fixed task. No line of model output is ever annotated with the belief
that "caused" it, because that causal chain is not observable and asserting it
would be a fabricated number wearing prose.

**No O(n²) contradiction sweep.** The arithmetic is above: 4,498,500 comparisons
at the design assumption, versus one bounded call per write. Named as a refusal
because the sweep is the obvious implementation and it demos fine on fifty
claims.

**No vector database — and no embeddings either.** Retrieval is exact-match
blocking with alias edges resolved at query time; typical block size is single
digits. An earlier revision pinned an embedding model that nothing called; the
pin and every claim resting on it were removed rather than retrofitted.

**No real entity matcher, no destructive merges.** `sameAs` edges only, human
confirmed, resolved at query time. A wrong merge in a mutable store is
unrecoverable; a wrong edge is one superseding event from undone.

**No voice, no TTS.** Cut unconditionally, even though a multimodal prize
category exists — the honest reason to build it would have been the prize.

**No enterprise deployment claims.** One user, one dossier, stated plainly
below.

---

## What is measured and what is not

Every number displayed anywhere — this README, the diagram, console output, the
video overlay — traces to **[`docs/metrics.json`](docs/metrics.json)**, a live
query, or a script you can run. An entry there is either an object carrying
`value`, `provenance`, `run_id` and `date`, or the literal string
`"not yet measured"`. There is no third form and no placeholder estimate; an
in-process timing is never reported as a deployed measurement.

As of this tree, **every metrics entry reads `not yet measured` and the `runs`
array is empty** — including doctrine-replay determinism, the rule-compliance
delta, claim counts, contradiction precision against the planted manifest, and
the scheduled-run count. `not yet measured` means exactly that: not a
conservative estimate, not a value awaiting confirmation.

Numbers in this README that are *not* measurements: **3,000 claims** is a design
assumption stated as such; **4,498,500** and the cap of **20** are arithmetic
and a code constant (`MAX_RETRIEVED`, `src/baraza/reconcile/detect.py`), both
checkable without running anything.

---

## Disclosures

**Built with AI coding assistance,** which the hackathon rules expressly permit.
The majority of the code was written by an agentic coding assistant under the
session protocol in `AGENTS.md`: unattended sessions against mechanical gates,
supervised review between them. Every session's opening prompt, verbatim course
corrections, outcome and key decisions are in
[`docs/BUILD-LOG.md`](docs/BUILD-LOG.md); toolchain observations, including what
degraded, are in [`docs/FINDINGS.md`](docs/FINDINGS.md). The design decisions,
invariants and refusals are the author's; the typing was largely not.

**This project began as succession intelligence** — the same engine pointed at
an organization's records instead of a person's guidance. The pivot to the
dossier is recorded, with its reasoning, in
[`docs/pivot/DECISION-dossier.md`](docs/pivot/DECISION-dossier.md); the corpus
readers, the manifest verifier and the multi-audience visibility tests from that
phase remain in the tree as an eval harness.

**Several defect-class guards are ported from a sibling project** and are not
presented as novel: epoch normalization (an ISO-string sort there kept a revoked
grant active under mixed UTC offsets while tests stayed green), and the numbers
discipline above, where each rule was observed rather than theorized. What is
new here is enforcement — the guards are build-failing lints in
`scripts/compliance.py`, verified by planting each violation and watching it
fire with a `file:line`.

**The agent framework was chosen without a published comparison.** The negative
finding that once justified the choice failed verification and was deleted
rather than paraphrased from memory; `docs/framework-decision.md` says so at
length. ADK is used, genuinely imported and driven; the reason it beat
alternatives is not documented.

**Offline demo output is replayed, not live.** Cassettes are real Vertex
responses captured with model ID, run ID and UTC date. Nothing in this
repository fabricates model output; a replayed number says it is replayed
wherever it appears.

**No real people, organizations or data.** The eval corpus is fully synthetic,
generated from `fixtures/corpus/BIBLE.md` against `fixtures/MANIFEST.md`. The
dogfooding subject is the builder himself, and no real person or company is
named anywhere in this repository, its fixtures, its tests or its video — least
of all as a bad actor.

---

## License

Apache-2.0. See [`LICENSE`](LICENSE).
