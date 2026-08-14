# Compliance matrix

How Baraza satisfies each mandatory requirement of the hackathon, with the
requirement IDs that carry it and the command a judge can run to check.

Two standing rules govern this file.

**Cells enumerate IDs. They never use ranges.** `BAR-301, BAR-302, BAR-303` — never
`BAR-301` through `BAR-309`. A range hides which requirements actually back a claim,
and it lets a cell keep looking supported after one of the requirements inside it is
cut. `scripts/compliance.py` fails the build on range notation in a matrix cell.

**A framework, model or service is named here only if the code uses it.** Not if it
is planned, not if it is a declared dependency, not if it was almost used. This is
the rule that pulled an earlier revision's claim about a service the code never
called, and it is the rule that governs the framework row below — which currently
does not say what the project intends it to say.

---

## Provenance, and what this file cannot check

**The official rules text is not carried in this repository.** It was pasted into a
build session prompt and is not reproduced in the tree. So each row states where its
requirement wording came from:

- **(recovered)** — the requirement text is present in
  `baraza-prd-v1.2-amendments.md` §3, which recovered those rows from PRD v1.1.
- **(in-tree inference)** — the requirement is reconstructed from BAR IDs and
  acceptance criteria present in the tree. **The wording has not been checked against
  the official rules**, and a row marked this way is a statement about what Baraza
  built, not a verified quotation of what was required.

Separately: `docs/PRD.md` is absent, so the BAR-007 ID audit cannot run. Roughly
thirty-five requirement IDs exist in this repository as identifiers with no
acceptance criteria. Any ID marked **†** below has no recovered AC text in the tree;
citing it means "this is the requirement that owns this work", not "this AC has been
read and satisfied".

IDs with full recovered requirement text: BAR-007, BAR-020, BAR-021, BAR-303,
BAR-309, BAR-320, BAR-330, BAR-410.

---

## Mandatory requirements

| Rule requirement | How Baraza satisfies it | Requirement IDs | Check it |
|---|---|---|---|
| **At least one Google agent-development framework** (recovered) | **Currently unsatisfied in code — see the framework note below.** ADK is declared in `pyproject.toml` and named as the resolved framework in `docs/framework-decision.md`, but no module imports it. Every model call in the tree routes through the GenAI SDK via `src/baraza/llm.py`. Per the rule at the top of this file, this matrix will not claim ADK until an import exists. | BAR-020 | `grep -rn "google.adk" src/` returns nothing today; `grep -rn "google.genai" src/` returns the call sites |
| **At least one Google Cloud infrastructure service** (recovered) | Cloud Run Jobs for the ingestion Job and the nightly `baraza-reconcile` Job; Cloud Run services for the interview and successor surfaces; Firestore as the append-only claim-event log, session store and entity table; Cloud Scheduler as the nightly trigger. | BAR-021, BAR-410, BAR-411† | `src/baraza/fold/store.py`, `src/baraza/reconcile/job.py`; deployment state in the README's status table |
| **Google models perform the work** (in-tree inference) | Gemini in two roles: a reasoning role for contradiction adjudication, agenda synthesis, the divergence turn and successor synthesis; a fast role for extraction, alias proposals and interview turns. Gemma runs the ingestion relevance pre-filter. Pins live only in `src/baraza/schema/models.py`. | BAR-303, BAR-320, BAR-330 | `make compliance` fails on a model-ID literal anywhere else; `make verify-models` resolves every pin against live Vertex |
| **Original work, built for this hackathon** (in-tree inference) | The repository's first commit is dated 2026-08-13 and carries the session ID in its message. Prior work carried in from a sibling project is disclosed rather than absorbed. **Gap:** only session B0 has a build-log entry; the B1 and B2 commits landed without one, so the per-session log is incomplete for two of the four sessions in the history. | No BAR ID — submission-level | `git log --reverse --format='%ad %s'`; `docs/BUILD-LOG.md`; the Disclosures section of `README.md` |
| **Public repository with an open-source license** (in-tree inference) | Apache-2.0, full text at `LICENSE`, declared in `pyproject.toml`. | BAR-501† | `LICENSE`; `grep license pyproject.toml` |
| **Project description and README** (in-tree inference) | `README.md` carries the problem, the mechanism with its arithmetic, spin-up instructions, the seven contract targets, the negative decisions required by BAR-501, the disclosures, and an explicit statement of what has and has not been measured. | BAR-501† | `README.md` |
| **Architecture diagram** (in-tree inference) | `docs/architecture.md` (Mermaid, renders on GitHub) and `docs/architecture.svg` (self-contained, legible in light and dark). Both show the four native formats, the model roles, the append-only log, the fold, on-write detection, the ledger and agenda, the interview and approval path, the visibility boundary, the successor reader and the Scheduler. Neither prints a model ID, because `make verify-models` has not run green. | BAR-505† | `docs/architecture.md`, `docs/architecture.svg` |
| **Demonstration video** (in-tree inference) | Not yet produced. Planned content: the unattended agenda generation, the contradiction catch, the divergence moment, approval with the visibility choice, the static graph diff, and a Scheduler execution-history frame. | BAR-601†, BAR-602†, BAR-603†, BAR-604†, BAR-605†, BAR-606†, BAR-607†, BAR-608† | Recording gate 2026-08-28 in `docs/GATE.md` |
| **Publicly reachable hosted instance** (in-tree inference) | Not yet deployed. The hosted instance reads as `Audience.PUBLIC`, which is the least-privileged audience in `src/baraza/schema/visibility.py`, so a logged-out judge sees only claims explicitly published. | BAR-410, BAR-411† | Not yet checkable |
| **Reproducibility from a clean clone** (in-tree inference) | `make install` then `make demo`, offline, with no credentials: local append-only JSONL event log and recorded model cassettes. `make bootstrap` and `make teardown` provision and remove the deployed path, and `teardown` is safe to run repeatedly. **Not yet met:** `fixtures/cassettes/` holds no recordings, so `make demo` exits 2 and does no work. Recording them is a supervised step that costs live Vertex calls. | BAR-506†, BAR-007 | Reproducibility gate 2026-08-25 in `docs/GATE.md`; the README's status table records every target's observed exit code |
| **Disclosure of AI assistance** (in-tree inference) | Disclosed in `README.md`: the assistant wrote the majority of the code under the session protocol in `AGENTS.md`, with every session's prompt and outcome logged. Ported prior work and the placeholder finding file are disclosed in the same section. | No BAR ID — submission-level | `README.md`, Disclosures |
| **Additional Google models beyond the primary one** (in-tree inference) | Gemma as the ingestion relevance pre-filter, with a real interface and a `stub` / `gemma` flag; text embeddings for blocking-key expansion. Both are declared in `src/baraza/schema/models.py` so the claim traces to code rather than to a sentence. The Gemma survival rate is `not yet measured`. | BAR-303 | `src/baraza/ingest/prefilter.py`; `docs/metrics.json` |

---

## The framework row, in full

This is the row a judge is most likely to test, and it is the row that does not
currently hold.

**What BAR-020 says.** ADK is the runtime framework for the interviewer, reconciler
and extractor agents, resolved by evidence rather than re-verified. The
pre-committed fallback is scoped to exactly one surface: if ADK's token-streaming
path cannot meet BAR-330's first-visible-token criterion, or its session surface
cannot meet BAR-334's per-turn externalization, within one bounded attempt of no more
than three hours, the **interview service only** drops to direct GenAI SDK calls with
our own turn loop. The reconciler and extractor remain on ADK regardless.

**What the code does.** Nothing imports ADK. `src/baraza/llm.py` is the single model
layer for the whole system — extractor, reconciler, interviewer and successor alike —
and it calls the GenAI SDK directly.

**Why that is not the fallback.** The fallback covers one surface and requires a
bounded attempt to have been made and recorded. No attempt has been recorded
(`docs/framework-decision.md` states the fallback branch has not been taken), and the
current state covers every surface, not one. So this is not the fallback branch — it
is a gap between the decision and the code.

**What this matrix does about it.** It declines to claim ADK. A dependency line in
`pyproject.toml` is not a use of a framework, and the rule that a framework is named
only if the code uses it does not have an exception for the row that most needs one.

**What closes it.** Either the extractor and reconciler agents are built on ADK and
this row is rewritten to name it, or the bounded attempt is run, fails, is recorded
in `docs/framework-decision.md` with the measurement that triggered it, and this row
is rewritten to name what actually shipped. Either way the row and the code change in
the same commit.

Frameworks and SDKs declared in `pyproject.toml`: `google-adk`, `google-genai`,
`fastapi`, `uvicorn`, `pydantic`, `httpx`, `google-cloud-firestore`,
`google-cloud-storage`, `pypdf`, `pdfplumber`, `openpyxl`, `python-docx`, and the
OpenTelemetry SDK, API and Cloud Trace exporter. There is no lockfile in the tree;
`pyproject.toml` is the declaration of record.

Two of those are declared and **not** used by any code path, and are therefore not
claimed anywhere in this file: `google-adk`, for the reason above, and
`google-cloud-storage`. Verify either with `grep -rn "google.adk" src/` and
`grep -rn "google.cloud.storage\|from google.cloud import storage" src/`, both of
which currently return nothing.

---

## Claims this repository deliberately does not make

Each of these was available and each was refused, for the same reason: a claim the
repository cannot back is worth less than no claim.

- **Antigravity is not claimed.** BAR-020 cites an Aug 8 negative finding rather than
  dual-listing it. The finding file is currently a placeholder; see the README's
  Disclosures.
- **No agent framework other than ADK is named**, and ADK itself is not claimed until
  it is imported.
- **No enterprise deployment claim.** Demo claims stay scoped to a single
  organization's synthetic corpus.
- **No voice or multimodal claim.** Voice was cut unconditionally, so the multimodal
  prize category is not pursued even though it exists.
- **No measured number is stated anywhere without provenance.** Every entry in
  `docs/metrics.json` currently reads `not yet measured`, and every surface that
  would display a number says so instead of estimating one.
- **No scheduled run is counted as organic activity.** Every event the nightly Job
  appends is marked `scheduled=True`.

---

## Checking this file

```bash
python3 scripts/compliance.py --no-prd   # the four invariant lints, standalone
make compliance                          # the same, plus the BAR-007 PRD ID audit
grep -rn "google.adk" src/               # the framework row's evidence, or its absence
make verify-models                       # resolves every pinned model ID against live Vertex
```

Exit codes from `scripts/compliance.py`: `0` green, `1` findings, `2` the audit could
not run. The distinction matters here — `2` is the current state of the PRD audit, and
a gate that skipped its main check while reporting green is the failure this whole
apparatus exists to prevent.
