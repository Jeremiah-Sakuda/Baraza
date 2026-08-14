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
| `make adaptation-metric` | exit 1, no transcripts |
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
  154 passing tests cover the schema, the fold, detection, the ledger, the
  agenda, approval, retraction, the boundary off the demo path and temporal
  normalization — the invariants, which is the right priority, but "154 passed"
  should not be read as coverage of the product.
- **`docs/BUILD-LOG.md` has no entry for B1 or B2.** Both are in the commit
  history (`bc46324`, `cc89d72`); the session protocol requires the entry
  *before* the commit. Two of four sessions skipped it, and a verbatim opening
  prompt is not recoverable after the fact — so that record is permanently
  incomplete rather than merely late. `docs/compliance.md`'s originality row
  cited that log as evidence and has been amended to name the gap.
- **25 paths are untracked.** Everything B3's predecessors wrote outside
  `src/` — `tests/`, `fixtures/`, `deploy/`, `scripts/` bar `compliance.py`,
  `README.md`, `LICENSE` — is in the working tree and not in any commit. The
  three commits that exist contain `src/` only.

### Escalated rather than resolved: the Antigravity file

`docs/antigravity/decision.md` states, second-hand and explicitly marked as
such, that a named vendor's SDK failed a headless multi-agent assertion during
verification on Aug 8. The source document is not in the repository. This sits
against two rules at once — `AGENTS.md` §7 and BAR-020 require the finding
present *verbatim* as the basis of the framework decision, while the standing
prohibition is on carrying an unverifiable negative claim about a real entity.

The file already argues for its own resolution: locate the original and attach
an attribution header, or delete the citation from BAR-020 and state plainly
that ADK was chosen without a published comparison. Neither is a change a
verification pass should make unilaterally, so it was left exactly as found and
is raised here. It is the only item in the tree where two of the project's own
rules point in opposite directions.
