# AGENTS.md — Baraza

Context file for agentic coding sessions. Read this before touching any file. If an instruction here conflicts with a request in a session prompt, **stop and say so** rather than resolving it silently.

---

## What this is

Baraza is succession intelligence. Overnight and unattended, it reads years of an organization's mess — chat exports, a skew-scanned constitution, headerless budget sheets, minutes — and asks the corpus what it disagrees with, producing a ranked ledger of contradictions and an interview agenda no human wrote. Then it conducts the exit interview: citation-grounded questions, clarifying follow-ups, and the moment that is the product — holding a departing officer's testimony against the documentary record and surfacing the divergence. Approved answers become committed memory with a visibility choice. The agent retires its own resolved questions, so the next interview is shorter than the last.

**Opening:** *Every May, thousands of organizations forget everything.* **Close:** *This September, mine won't.*

`docs/PRD.md` (v1.3 merged) is authoritative. Requirement IDs (`BAR-###`) and their acceptance criteria are the contract.

---

## Hard constraints — never violate, never "temporarily" bypass

1. **Runtime is Gemini, exclusively.** Gemini 3.5 Pro and Flash via Vertex AI, pinned model ID literals. No other model provider in any execution path.
2. **The visibility boundary is the product's headline property and it fails open if you are careless.** `visibility` **defaults to `private` at append time**, never unset. `readable_by(claim, audience)` is defined **once** and every read path routes through it — divergence detection, ledger, agenda, interviewer, graph view, successor mode. The reconciler **may count** an unreadable claim toward a contradiction's existence; it must **never** render that claim's text or quote into a question for a different audience. A reader that forgets the predicate must fail closed.
3. **`rejected` is a tier and it retracts.** A rejected claim leaves the retrieval pool, the ledger, and every future agenda, permanently.
4. **The log is append-only and the graph is a fold.** Deterministic event IDs, `create()`-only writes, Firestore rules rejecting update/delete. There is no mutable graph store; every rendered graph state is a fold over the event log. Fixing bad data means appending a superseding event, never editing one.
5. **Time comparisons are epoch, everywhere** (BAR-309). Integer epoch millis, UTC — fold ordering, interval overlap, turn ordering, recency ranking. ISO-8601 strings are serialization only. Sorting or comparing instants as strings is a known defect class in this portfolio (it kept a revoked grant active under mixed UTC offsets) and is prohibited outright.
6. **Citations are load-bearing.** `quote` is mandatory on every claim; anchors reference only real, registered source locations; a fabricated or unresolvable anchor is a stop condition, not a warning. Successor mode refuses uncited synthesis — the refusal is a feature with its own AC, not an error state to engineer away.
7. **No real member or person data anywhere** — repo, fixtures, video, hosted instance. No real company or person is ever named as a bad actor in fixtures, tests, comments, or copy. The corpus is synthetic, generated from `fixtures/corpus/BIBLE.md` against `fixtures/MANIFEST.md`.
8. **Framework is ADK, resolved by evidence** (BAR-020). The only permitted deviation is the pre-committed fallback — interview service to direct GenAI SDK calls — under BAR-020's bounded trigger, recorded in `docs/framework-decision.md`. The compliance matrix never names a framework the lockfile doesn't contain.

---

## Numbers discipline — each of these is a named defect class, observed in this portfolio, that recurs under deadline pressure

- **Never report an in-process timing as a deployed measurement.** Every recorded number states its provenance: measured in-process, measured deployed, or not yet measured.
- **Never display a hardcoded literal as a real count.** Every number on any surface (console, README, diagram, video overlay) traces to a query, a committed metrics entry, or a script a judge can run.
- **Never write a plausible number where a measured one belongs.** `"not yet measured"` is always the correct substitute. `docs/metrics.json` entries carry a run ID and date or the literal string `"not yet measured"` — nothing else.
- **Never count a scheduled job as organic activity.** Cloud Scheduler runs are labeled as such in any accounting.
- **Never widen a scope, key, or service-account permission to unblock anything.** A missing permission stops the session and gets reported, not routed around.

---

## Acceptance-criteria discipline

A requirement is done when its AC passes mechanically — not when the feature "works." ACs in this PRD are written as **properties, not events**: "the agent adapts" is proven by a computed metric over committed transcripts, not by a parameter having been passed; "state survives" is proven by a mid-stream kill, not by liveness; "the boundary holds" is proven off the demo path. When writing tests, test the property the AC names. When an AC seems impossible as written, stop and say so; do not quietly test a weaker property.

---

## Non-goals — do not build these, do not "improve" toward them

- No real entity matcher — canonical entity table + alias pass, human-confirmed; `sameAs` edges only; the cardinality doesn't justify ML.
- No destructive identity merges — resolve at query time.
- No O(n²) contradiction sweep — detection is on-write, blocked on subject ∪ object ∪ `predicate_hint`, temporally gated.
- No vector database — embed claims, never the corpus; brute-force top-k in memory; state the arithmetic.
- No voice, no TTS — cut unconditionally; the README notes it as a scope decision.
- No enterprise deployment claims — market framing generalizes; demo claims stay chapter-scoped.
- No LMS-style integrations, no multi-org features, nothing September-scoped (PRD §7 records September so it isn't relitigated here).

---

## Repository layout

```
src/
  ingest/        chunking, Gemma pre-filter interface (stub|gemma), extraction, entity pass
  reconcile/     contradiction detection, disputed ledger, agenda generator, closed loop
  interview/     interviewer service, session store, approval flow, replay harness
  successor/     librarian service (committed ∧ readable_by(successor) only)
  schema/        claim, event, session, contradiction_event models (authoritative)
  fold/          event-log fold → graph states; the only graph renderer
scripts/         compliance.py, adaptation_metric.py, bootstrap_gcp.sh, teardown.sh
fixtures/
  corpus/        BIBLE.md + generated artifacts in native formats
  interviews/    replay transcripts (canned answers, per persona)
  transcripts/   generated persona run transcripts (raw JSON, never hand-edited)
  MANIFEST.md    every planted landmine, with expected behavior
  golden-log.jsonl
docs/            PRD.md, GATE.md, BUILD-LOG.md, FINDINGS.md, compliance.md, metrics.json,
                 antigravity/decision.md, framework-decision.md
tests/           unit, emulator, and property tests (fold stability, boundary, temporal)
```

## Make targets (seven; all exit 1 with "not implemented" until real)

| Target | Does |
|---|---|
| `make compliance` | BAR-007: PRD ID audit; nonzero on orphans, dangling refs, range notation |
| `make demo` | Offline path end-to-end: ingest → agenda → replay interview → successor query (emulator + local corpus) |
| `make demo-agenda` | Cold ingest → ledger + agenda, unattended |
| `make demo-interview` | Interview loop; `--replay` feeds canned answers on a timer |
| `make verify-manifest` | Prints "found N of N planted problems" AND the misses |
| `make verify-anchors` | Resolves every anchor in CI |
| `make adaptation-metric` | Standalone scorer over `fixtures/transcripts/`; no application imports |

---

## Session protocol

1. **Read `docs/PRD.md` and this file in full before any session's first action.**
2. **Supervised sessions:** for anything larger than an hour, produce an implementation plan first, wait for correction, then execute.
3. **Unattended sessions** run under PRD §2.5: proceed session by session in playbook order; at each gate, verify mechanically (tests + `make compliance` + the named ACs); on red, write `STOPPED.md` (failing gate, exact error, working-tree state, what was NOT attempted), commit it, halt. Deploy/cloud failures go to `STOPPED-DEPLOY.md` and the run continues local-only. Never proceed past a gate that cannot be mechanically verified.
4. **Commit per session**, session ID in the message. The build-log entry is appended **before** the commit.
5. **Session close (every session, no exceptions):** append to `docs/BUILD-LOG.md` using the template below, then append any measured numbers or toolchain observations to `docs/FINDINGS.md` with today's date — what ADK's surfaces supported, where they fought the design, what the long-context passes got right and wrong. Admitting that something degraded is more credible than claiming everything worked.

### BUILD-LOG.md entry template

```
## <date> — <session id>

**Opening prompt (verbatim):**
<the session's opening prompt, unparaphrased>

**Course corrections (verbatim, if any):**
- <exact wording>

**Outcome:** what was built; which ACs now pass; what failed or was deferred; anything surprising.

**Key decisions (exactly 2–3, or "No forks this session"):**
- <chosen> over <rejected>, because <reason>. A decision is a fork where the alternative was live; routine implementation choices don't qualify.
```
