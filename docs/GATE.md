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

**Status:** green as of session B0 (lints; PRD audit blocked — see below).

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

---

## G3 — Reconciler (BAR-320–323)

| Assertion | Where |
|---|---|
| Detection is blocked, not O(n²) | retrieved-claim count ≤ 20 per write, asserted in test |
| FY-pair false positive does **not** fire | `tests/unit/test_detection.py`, under permuted offsets |
| Rejected claim leaves ledger and every future agenda | `tests/unit/test_retraction.py` |
| Unreadable claim can be counted but never quoted | `tests/unit/test_boundary_offpath.py` |

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
