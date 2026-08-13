# Baraza PRD v1.2 — Amendments to v1.1

**Status:** Authoritative amendments. Where this document conflicts with PRD v1.1, this document wins. Integrate by merging into `docs/PRD.md` during session B0 (see §6), then run `make compliance` against the merged file; the merged file becomes the single authoritative v1.2.

**Recovery note (honest scope of this document):** v1.1 was recovered from the prior working session in partial form. Fully recovered and amended here where touched: §1.4 invariants, §2 compliance matrix, §3.1–3.3, BAR-001/002/004/006/020, BAR-301–308, BAR-320–323, BAR-330–336, BAR-338, BAR-340, BAR-410/411, BAR-501/505/506, BAR-601–604, and the v1.0→v1.1 changelog. **Not recovered:** §1.1–1.3 verbatim (market inversion framing), §7 cut list verbatim, BAR-101/102 full text, BAR-620–624 full text, BAR-605–608. Those sections are **not** re-specified here — they carry forward from v1.1 unchanged. Do not reconstruct them from memory; merge them from the v1.1 file.

---

## 1. Changelog v1.1 → v1.2

| # | Change | Reason |
|---|---|---|
| 1 | **BAR-020 resolved by evidence: ADK primary, GenAI SDK turn-loop as pre-committed fallback.** Compliance matrix framework cell rewritten to match. | The v1.1 branch ("decided no later than Aug 8") expired on the same day the Antigravity headless multi-agent assertion failed in verification. Dual-listing Antigravity in the matrix is now a claim the repo will not back. A framework name never appears in the matrix unless the code uses it — the same principle that pulled the Model Armor claim. |
| 2 | **Calendar recompressed to an Aug 12 evening start** (§5). Substrate gate Aug 19 → Aug 15. Scope gate unchanged at Aug 22. | v1.1's calendar assumed an Aug 5 start; the build begins the evening of Aug 12 with zero commits. |
| 3 | **New BAR-021: stub reconcile Job + Cloud Scheduler deployed by Aug 13.** BAR-410's AC strengthened from "≥2 nightly runs" to "≥10 nightly runs in execution history before recording." | v1.1 deployed the Scheduler in Phase 5, leaving ~2 nightly runs of history by recording day. Karani v1.2 already corrected this pattern (stub Scheduler on day 2); ported. Execution history is the cheapest honest autonomy evidence the project can accumulate, and it only accumulates in real time. |
| 4 | **New BAR-309: temporal normalization.** All temporal comparisons on epoch-normalized values; planted mixed-UTC-offset fixture; fold-order stability AC. | Direct port of a recurring defect class: an ISO-string sort in `resolve()` allowed a revoked grant to remain active under mixed UTC offsets while byte-stability tests passed. Baraza's fold ordering, interval-overlap gating (BAR-320), and a corpus mixing GroupMe epoch timestamps, scanned-PDF dates, and interview `ts` values reproduce those exact conditions. |
| 5 | **BAR-330 AC hardened against self-grading.** Adaptation metric computed by a standalone script over raw committed replay transcripts; judge-runnable; in-session change identified by turn ID. | A metric computed by the same codebase over its own configured personas is one step from the hardcoded-literal-displayed-as-real-count defect class. The claim converts from stated to verifiable by making the transcripts and the scorer independently inspectable. |
| 6 | **BAR-303 split into wiring (tonight, unattended) and measurement (supervised session).** Deterministic stub behind the real interface overnight; `metrics.json` carries `"not yet measured"` until the supervised run. | BAR-303's own text forbids leaving the Vertex Gemma endpoint up overnight, and an unattended agent must not block on model pulls or endpoint provisioning. A plausible survival rate is never written where a measured one belongs. |
| 7 | **BAR-323 choreography scheduled, not assumed** (§5): first genuine night-1 / artifact-drop / night-2 pass Aug 15→17; refreshed Aug 24→25 for recording-fresh evidence. | The differential ledger is the autonomy beat; its evidence requires real elapsed nights, which cannot be compressed retroactively. |
| 8 | **New §2.5: Unattended Execution Profile.** Machine-checkable green per phase gate; stop-don't-route-around as a named invariant with `STOPPED.md` semantics; deploy failures on a separate non-blocking lane. New BAR-007: `make compliance` script. | The build launches as an unattended overnight run. Every human gate converts to automated verification or the run improvises at the gates — and the documented failure modes of unattended agents at red gates are: widen the scope, hardcode the number, report the in-process timing. |
| 9 | Prize mapping refreshed (§4): Collaborative Partner $20,000 (1 winner); consolation tiers for an individual entry are Individual/Hobbyist ($10,000 × 2) and Best Multimodal UX ($5,000 × 2, only if BAR-336 survives the gate); one prize per project confirmed in the live rules. | Numbers verified against the live Devpost page Aug 12. |

**Considered and not adopted:** feeding approval/edit deltas into the style profile as a second adaptation mechanism. Literal track-fit language ("captures feedback… constantly adapts"), but it adds no new verifiable property beyond BAR-330's measured metric and in-session change. Recorded here so it lands in the README's `## Negative decisions` (BAR-501) rather than in scope.

---

## 2. Amended and new requirement text

Each entry below is full replacement text for the cited ID (or a new ID). Untouched requirements carry forward from v1.1 verbatim.

### BAR-007 (new, Phase 0) — Compliance script
`scripts/compliance.py` implementing `make compliance`: extract every `BAR-###` from `docs/PRD.md` §4, diff against the IDs cited in §2's matrix AND against IDs referenced anywhere in the PRD prose; exit nonzero on any orphan ID, any dangling reference, or any range notation in a matrix cell (cells enumerate IDs, never ranges — v1.1 ruling #6 stands).
*AC:* runs green on the merged v1.2 before any feature commit; a deliberately planted orphan fails the run.

### BAR-020 (amended) — Agent framework, resolved by evidence
**Resolved, not re-verified:** ADK is the runtime framework for the interviewer, reconciler, and extractor agents. Basis: the Aug 8 finding — the Antigravity SDK's headless multi-agent boolean assertion failed during verification (`docs/antigravity/decision.md`, copied into this repo verbatim with an attribution header). No day-1 Antigravity verification is run for Baraza; the evidence already exists.
**Pre-committed fallback, scoped to one surface:** if ADK's token-streaming path cannot satisfy BAR-330's first-token AC, or its session surface cannot satisfy BAR-334's per-turn externalization, within **one bounded attempt of ≤3 hours**, drop the interview service (only) to direct GenAI SDK calls with our own turn loop. The reconciler and extractor remain on ADK regardless — their surfaces are batch, not streaming, and carry no equivalent risk. The decision and its trigger are recorded in `docs/framework-decision.md` whichever way it falls.
*AC:* the compliance matrix names only frameworks present in `go.mod`/`requirements.txt`/lockfile; `docs/framework-decision.md` exists and states which branch was taken and why.

### BAR-021 (new, Phase 0/1 boundary) — Early scheduler deploy
Stub `baraza-reconcile` Cloud Run Job + nightly Cloud Scheduler trigger deployed by end of Aug 13. The stub may no-op beyond writing a heartbeat event to the log; it is replaced in place when BAR-321 lands. Purpose: real execution history accumulates from day 2.
*AC:* Scheduler execution history shows a run for every night from Aug 14 onward; BAR-410's history AC (≥10 nightly runs before recording) becomes satisfiable arithmetic, not hope. Scheduler runs are labeled as such in any traffic or run accounting — a scheduled job is never counted as organic activity (defect class: Cloud Scheduler jobs miscounted as third-party traffic).

### BAR-303 (amended) — Gemma relevance pre-filter, split
**Wiring (unattended, night 1):** the filter interface is real and final — `filter(chunk) -> keep|drop` sits in the ingestion path exactly where the production call goes, selected by flag: `stub` (deterministic keyword heuristic, committed, disclosed as a stub in its docstring and in `metrics.json`) or `gemma` (local Ollama or Vertex endpoint). Night-1 ingestion runs `stub`. No rewiring is required later; only the flag flips.
**Measurement (supervised session, Aug 19–21):** run the full corpus through `gemma` mode, log the survival rate to `/docs/metrics.json`, capture the rate for the architecture diagram. Vertex endpoint scripted up/down inside the session; never left running.
*AC:* `metrics.json` contains either a measured rate with a run ID and date, or the literal string `"not yet measured"` — never an estimated or placeholder number. The diagram (BAR-505) may only display the measured value.

### BAR-309 (new, Phase 2) — Temporal normalization
All temporal comparisons anywhere in the system — fold ordering over the claim-event log, `valid_from`/`valid_until` interval overlap (BAR-320), session turn ordering, ledger recency ranking — operate on epoch-normalized values (integer epoch millis, UTC). ISO-8601 strings are a serialization format, never a comparison key. The fixture corpus plants a mixed-offset trap: at least one GroupMe export segment with a non-UTC offset and one interview turn whose ISO representation sorts differently as a string than as an instant.
*AC:* a property test permutes serialized offsets across the golden log and asserts the fold produces an identical graph; the planted trap is listed in the corpus manifest and the test names it. (Defect-class port: ISO-string sort allowed a revoked grant to remain active under mixed UTC offsets while byte-stability tests passed.)

### BAR-320 (amended, one clause) — Contradiction detection
As v1.1 (on-write, blocked on subject ∪ object entities ∪ `predicate_hint`, temporally gated on interval overlap, ≤20 retrieved claims, one ~3k-token call), with the gating clause now explicitly dependent on BAR-309: interval overlap is computed on epoch values.
*AC:* unchanged from v1.1, plus the FY-pair false-positive fixture passes under permuted serialized offsets.

### BAR-330 (amended AC) — Interviewer adaptation, independently scored
Requirement text as v1.1 (agenda-led; clarifying follow-ups; token streaming with first visible token <1s on the replay path; adaptation structural, labelled, measured, and in-session).
*AC (hardened):*
1. The two persona replay transcripts are **generated by actual replay runs** and committed as raw JSON under `fixtures/transcripts/` — never authored or edited by hand.
2. The adaptation metric (mean follow-up depth per persona) is computed by `scripts/adaptation_metric.py`, a standalone script with no imports from the application package, runnable by a judge as `make adaptation-metric` against the committed transcripts.
3. The in-session adaptation moment is identified in the transcript by turn ID and referenced by that ID in the README and shot list — "see turn t-14" — so a judge can locate the exact exchange.
4. The metric printed anywhere (README, diagram, video overlay) is the script's output for the committed transcripts, reproducible to the digit.

### BAR-410 (amended, one clause) — Deploy
As v1.1 (ingest + reconcile Jobs, Scheduler, interview + successor services, per-stage least-privilege SAs; extractor cannot write `committed`; only the approval path promotes), with the history clause strengthened per BAR-021.
*AC:* Scheduler execution history shows **≥10 nightly reconcile runs** before recording day, with the stub-to-real replacement date identifiable in the history.

### §2.5 (new section) — Unattended Execution Profile
The build executes as unattended overnight sessions driven by a coding agent, with supervised sessions interleaved by day. This profile governs every unattended session:

1. **Green is machine-checkable.** Each phase exit in §5 lists its gate as commands and assertions (tests, `make compliance`, named ACs), not as judgment calls. A session may not proceed past a gate it cannot mechanically verify.
2. **Stop, never route around** (named invariant, joins §1.4): on any failed AC, missing permission, or conflict with an invariant, the session writes `STOPPED.md` — failing gate, exact error, state of the working tree, what was NOT attempted — commits it, and halts. The historically observed alternatives (widen the scope, hardcode the number, report the in-process timing, weaken the rule) are each individually prohibited and individually named in AGENTS.md.
3. **Two lanes.** Local build failures stop the run (lane 1). Deploy/cloud failures log to `STOPPED-DEPLOY.md` and drop the run to local-only continuation (lane 2) — a missing API enablement at 2 a.m. must not zero out a night of local progress, and must also never be "fixed" by widening a scope or key.
4. **Commit per session** with the session ID in the message; the S0 build-log entry appends before the commit. Morning review bisects on these.
5. **Numbers discipline:** any number produced overnight (timing, count, rate) is written with its provenance (measured in-process / measured deployed / not yet measured). In-process timings are never reported as deployed measurements.
6. **No real student, member, or person data**; no real company or person named as a bad actor; both carried from the standing instructions, restated here because unattended sessions generate fixtures.

---

## 3. Compliance matrix — touched rows only

| Rule requirement | How Baraza satisfies it | Req IDs |
|---|---|---|
| ≥1 Google Agent Framework | **Google ADK** (interviewer, reconciler, extractor). Fallback branch, if taken, moves the interview service to direct GenAI SDK calls and is documented in `docs/framework-decision.md`; the matrix is updated to match whichever branch ships. Antigravity is not claimed; the Aug 8 negative finding is published in `docs/antigravity/decision.md`. | BAR-020 |
| ≥1 Google Cloud infra service | Cloud Run (ingestion + reconcile Jobs, interview + successor services), Firestore (claim-event log, sessions, entities), Cloud Scheduler (nightly reconciliation, live since Aug 13) | BAR-021, BAR-410 |

All other rows carry forward from v1.1 unchanged.

---

## 4. Prize position (refreshed Aug 12 against the live Devpost page)

Primary: **The Collaborative Partner — $20,000 + $2,000 credits, 1 winner.** Consolation tiers for an individual entry: **Individual/Hobbyist ($10,000 + $1,000 credits, 2 winners)**; **Best Multimodal UX ($5,000 + $1,000 credits, 2 winners)** — eligible only if BAR-336 (voice) survives the Aug 22 gate, and per v1.1 it is a consolation path, never an addition to scope. One prize per project (standard Devpost clause, confirmed). Baraza is an individual entry; Startup Excellence belongs to Karani's ladder, not this one.

---

## 5. Recompressed calendar (v1.2 — authoritative)

| Window | Work | Gate |
|---|---|---|
| **Aug 12 (evening) → Aug 13** | Unattended night 1: B0 bootstrap (BAR-001/002/004/006/007, GATE.md, stubs) → B1 crude loop + `--replay` harness + emulator + BAR-334 kill-test rig → B2 ingestion spine (BAR-301–309; Gemma in `stub` mode; corpus generated per manifest) → B3 reconciler (BAR-320–322) as far as gates stay green. Deploy lane: `bootstrap_gcp.sh`, stub Job + Scheduler (BAR-021). Hard boundary: interview service skeleton (routes + session store) may stand up; no BAR-330 conversational work unattended. | Per-session mechanical gates; `STOPPED.md` on red |
| **Aug 13 (day)** | Morning review: `STOPPED*.md` → build log vs commits → defect-class audit (any timing, any displayed count, any scope-touching diff). Corrections. First real nightly reconcile run tonight. | — |
| **Aug 14–15** | Ingestion completion, entity scorecard, contradiction detection green on planted pairs | **Aug 15 — Substrate gate** (was Aug 19): full corpus ingested; scorecard ≥83% as a rate; ledger + agenda generate unattended from cold ingest. Red → interview drops to terminal-only permanently, graph to static-diff permanently, Aug 16–18 goes to deploy and docs |
| **Aug 15–18** | Interview engine, approval, successor (BAR-330–335, 338, 340). Differential-ledger choreography, first genuine pass: night 1 run Aug 15→16, April minutes land Aug 16, night 2 run Aug 16→17, diff verified Aug 17 (BAR-323) | — |
| **Aug 19–21** | Supervised sessions: Gemma survival-rate measurement (BAR-303); adaptation-metric replay runs and scoring (BAR-330); voice build/cut decision staged for the gate (BAR-336) | — |
| **Aug 22** | **Scope gate (unchanged, shared with Karani):** ingest + reconciler + interview (terminal ok) + approval + graph + successor all green on `--replay`. Behind → §7 cuts activate; both entries still submit | Hard |
| **Aug 23–25** | Deploy hardening (BAR-410/411), README (BAR-501), diagram (BAR-505), bootstrap/teardown (BAR-506). Differential evidence refreshed Aug 24→25 for recording | Aug 25 — clean-clone `make demo` on a different machine |
| **Aug 26–28** | Recording (BAR-601–608): agenda + replay centerpiece, contradiction catch, approval with visibility choice, static graph diff, Scheduler history frame (~13 nightly runs visible) | Aug 28 — video cut ≤4:00, verified logged-out |
| **Aug 29** | Blog + social posts (BAR-620–624), created-for-this-hackathon language, hashtag | — |
| **Aug 30** | Devpost submission checklist walk (category; hosted URL logged-out; description with §1.3 order; repo + README; both diagrams; video; bonus URLs) | Submit |
| **Aug 31** | Buffer. Deadline 5:00 PM PDT | — |

---

## 6. Integration instruction (session B0, first action)

1. Place the v1.1 PRD file (downloaded from the prior session) at `docs/PRD.md`.
2. Apply this amendments file: replace each touched requirement's text in full; insert new requirements in ID order; replace §5 calendar and the two matrix rows; append the v1.1→v1.2 changelog; add §2.5.
3. Delete this amendments file from the working tree after merge (its content now lives in `docs/PRD.md`; the merge commit preserves provenance).
4. Run `make compliance` (BAR-007) against the merged file. Green is the precondition for any further work.
5. Commit as `B0: PRD v1.2 merged — amendments authoritative`.

Sections listed as **not recovered** in the header carry forward from the v1.1 file byte-for-byte; if any is missing from the v1.1 file itself, STOP per §2.5.2 — do not reconstruct.
