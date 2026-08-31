# GATE.md — mechanical phase gates

Every phase exit in the PRD §5 calendar is a set of commands and assertions, not
a judgment call. A session may not proceed past a gate it cannot mechanically
verify (PRD §2.5.1).

On red: write `STOPPED.md` — failing gate, exact error, state of the working
tree, what was **not** attempted — commit it, halt. Deploy and cloud failures go
to `STOPPED-DEPLOY.md` instead and the run continues local-only (lane 2).

The four documented failure modes of an unattended agent at a red gate are each
individually prohibited:

- widen a scope, key, or service-account permission to unblock
- hardcode a number where a measured one belongs
- report an in-process timing as a deployed measurement
- weaken the rule the gate was testing

---

## Status refresh — 2026-08-31 (DOSSIER pivot)

Observed by running the commands on this tree, not inferred. The per-gate
sections below are kept as the dated history they are; where a section
disagrees with this table, this table is newer. `docs/BUILD-LOG.md` remains the
authority on what has landed since.

| Check | Observed 2026-08-31 |
|---|---|
| `make compliance` | **exit 0** — `docs/PRD.md` was restored in session B6, so the BAR-007 audit runs; all four invariant lints green. The G0 warning below is retained as history and is resolved. |
| `python3 scripts/compliance.py --no-prd` | **exit 0** |
| `make test` | **exit 0** — unit, property and integration suites green in full (the gate asserts *all green*, not a count) |
| `make demo` / `demo-agenda` / `demo-interview` | **exit 2** — `fixtures/cassettes/` still holds no recordings; the offline client refuses to invent one |
| `make verify-manifest` | **exit 2** — 18 of 18 plants present, 0 behaviour probes observed: no event log yet |
| `make verify-anchors` | **exit 2** — no citations to verify until an ingest run happens |
| `make adaptation-metric` | **red on purpose** (the scorer exits 1; `make` reports that as exit 2) — it names each missing input (determinism replay, battery outputs from `make battery-run`) and the command that produces it, rather than printing a zero |
| Model pins | **live-verified 2026-08-31** against project `baraza-2026` (the resolution `make verify-models` performs); pins in `src/baraza/schema/models.py` only |
| Deploy | Firestore append-only rules deployed and verified; Cloud Run Jobs and services live; the Scheduler 403 is root-caused with the `baraza-trigger` OIDC-hop fix recorded in `docs/deploy-postmortem.md`; `scheduler_nightly_runs_completed` remains `not yet measured` |

The pivot (`docs/pivot/DECISION-dossier.md`, PRD §6) adds workstream
obligations — scheduled initiation, turn-level belief extraction, the doctrine
compiler and diff, the rewritten adaptation scorer, the web face. Each lands
under the same discipline: green means the named tests plus `make compliance`
pass mechanically, and no gate below is weakened to admit it.

The calendar gates below (Aug 15/22/25/28) are kept as written; the ones whose
dates have passed record what was true at the time, and the reproducibility and
recording gates remain the bar for the submission artifacts.

---

## G0 — Substrate (B0)

```bash
make compliance          # BAR-007, must be green
make test                # unit + property
```

| Assertion | Where |
|---|---|
| `readable_by` has exactly one definition | `grep -rn "def readable_by" src/` returns 1 |
| A claim built with no visibility is `private` | `tests/unit/test_visibility.py` |
| `Claim.quote` does not exist as an attribute | `tests/unit/test_visibility.py` |
| Compliance lints bite on planted violations | `tests/unit/test_compliance_lints.py` |
| Fold is stable under permuted UTC offsets | `tests/property/test_fold_stability.py` |
| Consecutive FY terms do not overlap | `tests/unit/test_temporal.py` |

**Status:** green as of session B0, re-verified 2026-08-13 (B3): `readable_by`
returns exactly one definition, and `pytest tests/unit tests/property` is green
in full. (This gate asserts *all green*, not a count. The count changes with
every session; the property does not, and a gate that tracked the count would
have to be re-edited to stay true.) The PRD audit is still blocked — see below.

> ⚠️ **The BAR-007 PRD audit cannot run.** `docs/PRD.md` is absent, and the
> amendments file §6 forbids reconstructing the unrecovered v1.1 sections from
> memory. `make compliance` exits **2** (audit could not run), distinct from
> exit 1 (findings). The lints run standalone via `--no-prd` and are green.
> This is a stop condition on the PRD contract only; the substrate proceeded
> because none of it depends on the unrecovered sections. Recorded rather than
> routed around.

---

## G1 — Crude loop

```bash
make demo-agenda REPLAY=1
make test-emulator
```

| Assertion | Where |
|---|---|
| Cold ingest → ledger → agenda with no human input | `make demo-agenda` exit 0 |
| Session survives SIGKILL mid-turn and resumes at the same turn | `tests/emulator/test_kill_survival.py` |
| Replay harness feeds canned answers on a timer | `make demo-interview REPLAY=1` |

**Status 2026-08-13 (B3): red, on the first and third rows only.** `make
demo-agenda` and `make demo-interview` exit 2 — `fixtures/cassettes/` holds no
recordings and the offline client will not invent one. The SIGKILL row is
**green on the JSONL backend**: `pytest tests/emulator -k jsonl` is 1 passed, a
real `os.kill(pid, SIGKILL)` against a live child process. The Firestore variant
of that same test could not be run here — `make test-emulator` exits 1 because
the Firestore emulator is a JVM process and this machine has no JDK.

---

## G2 — Ingestion spine (BAR-301–309)

```bash
make corpus
make demo-agenda
make verify-anchors
make verify-manifest
```

| Assertion | Where |
|---|---|
| Every anchor resolves to a registered source location | `make verify-anchors` exit 0 |
| Planted problems found, and the **misses named** | `make verify-manifest` |
| Gemma filter selected by flag; night-1 runs `stub` | `metrics.json` records the mode |
| No naive datetime reaches a comparison | `make compliance` temporal lint |

**Status 2026-08-13 (B3): red, blocked behind G1.** `make corpus` is exit 0 (13
artifacts, every one round-tripped through `baraza.ingest.readers`) and the
temporal lint is green. `make verify-manifest` prints `found 18 of 18 planted
problems` — but that is the *plants*, not the *catches*: it also reports 0 of 17
behaviour probes observed, and exits 2, because no ingest run has produced an
event log. `make verify-anchors` exits 2 for the same reason: 11 sources
re-register from the bytes on disk and there are zero citations to resolve.
Neither row can go green until the cassettes exist.

---

## G3 — Reconciler (BAR-320–323)

| Assertion | Where |
|---|---|
| Detection is blocked, not O(n²) | retrieved-claim count ≤ 20 per write, asserted in test |
| FY-pair false positive does **not** fire | `tests/unit/test_detection.py`, under permuted offsets |
| Rejected claim leaves ledger and every future agenda | `tests/unit/test_retraction.py` |
| Unreadable claim can be counted but never quoted | `tests/unit/test_boundary_offpath.py` |

**Status 2026-08-13 (B3): green as unit properties.** All four rows are covered
by tests inside the passing suite. Every one is an in-process assertion over
constructed claims; none has yet been observed over a real ingest, because G1 is
red. Landmine **L-15** (the BAR-323 differential across two nights) is marked
`delegated` by `make verify-manifest` and cannot be closed here at all — it needs
two genuinely separated nightly runs.

---

## Substrate gate — Aug 15 (PRD §5, was Aug 19)

Full corpus ingested; entity scorecard ≥83% **as a measured rate**; ledger and
agenda generate unattended from a cold ingest.

**Red →** interview drops to terminal-only permanently, graph to static-diff
permanently, and Aug 16–18 is reassigned to deploy and docs.

---

## Scope gate — Aug 22 (hard, shared with Karani)

Ingest + reconciler + interview (terminal acceptable) + approval + graph +
successor all green on `--replay`.

**Behind →** PRD §7 cuts activate. Both entries still submit.

---

## Aug 25 — reproducibility gate

Clean clone on a **different machine**, `make install && make demo` green with
no network access to anything but Vertex.

---

## Aug 28 — recording gate

Video cut ≤ 4:00, verified while logged out, Google Cloud console proof frames
present (Cloud Run dashboard, Vertex logs, Scheduler execution history).
