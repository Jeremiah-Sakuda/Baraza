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
called, and it is the rule that governed the framework row below through three
build sessions in which ADK was a declared dependency nothing imported. The row now
names ADK, because the import now exists — and it still marks the part that is not
yet true.

---

## Provenance, and what this file cannot check

**The official rules text was checked from the live Devpost rules page and the
ADK-aligned v1.2 product contract is now committed at `docs/PRD.md`.** The PRD is a
project contract, not a substitute for the official rules; before submitting, the
team must still re-check the live page for changes.

- **(recovered)** — the requirement text is present in
  `baraza-prd-v1.2-amendments.md` §3, which recovered those rows from PRD v1.1.
- **(in-tree inference)** — the requirement is reconstructed from BAR IDs and
  acceptance criteria present in the tree. **The wording has not been checked against
  the official rules**, and a row marked this way is a statement about what Baraza
  built, not a verified quotation of what was required.

`make compliance` now runs the BAR-007 PRD audit and the invariant lints. A green
audit validates internal requirement references; it does not turn an unmeasured or
undeployed feature into a completed one.

---

## Mandatory requirements

| Rule requirement | How Baraza satisfies it | Requirement IDs | Check it |
|---|---|---|---|
| **At least one Google agent-development framework** (recovered) | **Satisfied, on two independent bases.** (1) Google ADK: `src/baraza/agents.py` imports `LlmAgent`, `RunConfig`, `InMemoryRunner` and `FunctionTool` from `google.adk` (the import block at lines 118-122), and `build_extractor` / `build_reconciler` / `build_interviewer` construct real `LlmAgent` instances with per-agent tool isolation and transfer disabled. The **extractor is on the live ingestion path**: `baraza.ingest.extract.AgentClaimExtractor` drives it through an ADK `Runner`, and `IngestionPipeline` constructs it whenever the run is not offline (`src/baraza/ingest/pipeline.py`). (2) The Google GenAI SDK is on every model call path in the tree (`src/baraza/llm.py`, three `from google.genai import types` sites). **Scope, stated plainly:** one of the three agents is driven by a `Runner`; the reconciler and interviewer are built and isolation-tested but still reach the model through `llm.py`. The **offline/cassette path is deliberately direct**, so a replayed demo does not exercise ADK — see the framework note below. | BAR-020 | `grep -rn "google\.adk" src/` → 7 hits in `agents.py`; `grep -rn "baraza.agents" src/` → `ingest/extract.py`; `grep -rn "google\.genai" src/` → `llm.py` ×3, `ingest/extract.py` ×1; `PYTHONPATH=src pytest tests/unit/test_agents.py tests/unit/test_agent_extraction.py -q` |
| **At least one Google Cloud infrastructure service** (recovered) | Cloud Run Jobs for the ingestion Job and the nightly `baraza-reconcile` Job; Cloud Run services for the interview and successor surfaces; Firestore as the append-only claim-event log, session store and entity table; Cloud Scheduler as the nightly trigger. | BAR-021, BAR-410, BAR-411† | `src/baraza/fold/store.py`, `src/baraza/reconcile/job.py`; deployment state in the README's status table |
| **Google models perform the work** (in-tree inference) | Gemini in two roles: a reasoning role for contradiction adjudication, agenda synthesis, the divergence turn and successor synthesis; a fast role for extraction, alias proposals and interview turns. Gemma is **pinned and wired for** the ingestion relevance pre-filter but has never run: unattended ingestion uses the `stub`, and the `gemma` branch calls the ordinary `generate_content` path while the pin declares `surface="vertex-endpoint"` — nothing reads `GemmaFilter.endpoint`, so the first live attempt will most likely fail open on every chunk. That failure is now legible rather than silent (`FilterReport.failed_open`; a degraded pass prints `DEGRADED` and writes `not yet measured`), and the BAR-303 bonus is not claimed. Pins live only in `src/baraza/schema/models.py`. | BAR-303, BAR-320, BAR-330 | `make compliance` fails on a model-ID literal anywhere else; `make verify-models` resolves every pin against live Vertex |
| **Original work, built for this hackathon** (in-tree inference) | The repository's first commit is dated 2026-08-13 and carries the session ID in its message. Prior work carried in from a sibling project is disclosed rather than absorbed. **Gap, narrowed but not closed:** B0 and B3 have contemporaneous entries. B1, B2 and B4 were committed without one and have since been **backfilled from `git show --stat` and the commit messages, each marked as reconstructed after the fact**. What is permanently gone is the verbatim opening prompt and course corrections for those three sessions; they are recorded as unrecoverable rather than written from memory. So the build log is complete as a record of *what landed* and incomplete as a record of *how each session was driven*, and it says which is which per entry. | No BAR ID — submission-level | `git log --reverse --format='%ad %s'`; `docs/BUILD-LOG.md`; the Disclosures section of `README.md` |
| **Public repository with an open-source license** (in-tree inference) | Apache-2.0, full text at `LICENSE`, declared in `pyproject.toml`. | BAR-501† | `LICENSE`; `grep license pyproject.toml` |
| **Project description and README** (in-tree inference) | `README.md` carries the problem, the mechanism with its arithmetic, spin-up instructions, the seven contract targets, the negative decisions required by BAR-501, the disclosures, and an explicit statement of what has and has not been measured. | BAR-501† | `README.md` |
| **Architecture diagram** (in-tree inference) | `docs/architecture.md` (Mermaid, renders on GitHub) and `docs/architecture.svg` (self-contained, legible in light and dark). Both show the four native formats, the model roles, the append-only log, the fold, on-write detection, the ledger and agenda, the interview and approval path, the visibility boundary, the successor reader and the Scheduler. Neither prints a model ID, because `make verify-models` has not run green. | BAR-505† | `docs/architecture.md`, `docs/architecture.svg` |
| **Demonstration video** (in-tree inference) | Not yet produced. Planned content: the unattended agenda generation, the contradiction catch, the divergence moment, approval with the visibility choice, the static graph diff, and a Scheduler execution-history frame. | BAR-601†, BAR-602†, BAR-603†, BAR-604†, BAR-605†, BAR-606†, BAR-607†, BAR-608† | Recording gate 2026-08-28 in `docs/GATE.md` |
| **Publicly reachable hosted instance** (in-tree inference) | The deployed successor service reads as `Audience.PUBLIC`, so a logged-out judge sees only explicitly public committed claims. It now exposes read-only `/`, `/ledger`, and `/agenda` views, all rendered through the same audience boundary. The Scheduler trigger remains unresolved; this row does not claim autonomous execution. | BAR-410, BAR-411 | `STOPPED-DEPLOY.md`; `tests/unit/test_public_surfaces.py` |
| **Reproducibility from a clean clone** (in-tree inference) | `make install` then `make demo`, offline, with no credentials: local append-only JSONL event log and recorded model cassettes. `make bootstrap` and `make teardown` provision and remove the deployed path, and `teardown` is safe to run repeatedly. **Not yet met:** `fixtures/cassettes/` holds no recordings, so `make demo` exits 2 and does no work. Recording them is a supervised step that costs live Vertex calls. | BAR-506†, BAR-007 | Reproducibility gate 2026-08-25 in `docs/GATE.md`; the README's status table records every target's observed exit code |
| **Disclosure of AI assistance** (in-tree inference) | Disclosed in `README.md`: the assistant wrote the majority of the code under the session protocol in `AGENTS.md`, with every session's prompt and outcome logged. Ported prior work and the placeholder finding file are disclosed in the same section. | No BAR ID — submission-level | `README.md`, Disclosures |
| **Additional Google models beyond the primary one** (in-tree inference) | Gemma as the ingestion relevance pre-filter, with a real interface and a `stub` / `gemma` flag, declared in `src/baraza/schema/models.py` so the claim traces to code rather than to a sentence. **This bonus is not earned and may not be claimed as things stand:** the survival rate is `not yet measured`, and the `gemma` branch reaches the model through `generate_content` while the pin declares `surface="vertex-endpoint"` — `GemmaFilter.endpoint` is assigned and never read, so a live run would fail open on every chunk and Gemma would not have done any work. Earning it needs an endpoint-aware call path plus a green `make verify-models`; forgoing it needs this row deleted. Either is honest; claiming it as-is is not. A text-embedding pin was also listed here; it has been removed, because no module ever embedded anything and the rule at the top of this file forbids claiming a component that does not exist — including in the file that states the rule. | BAR-303 | `src/baraza/ingest/prefilter.py`; `docs/metrics.json`; `grep -rn embed src/` returns nothing |

---

## The framework row, in full

This is the row a judge is most likely to test. It holds. It did not hold for the
first three build sessions, and the paragraphs below used to say so in detail — that
history is kept rather than quietly overwritten, because a compliance file that
edits its own past is worth less than one that shows its work.

**What BAR-020 says.** ADK is the runtime framework for the interviewer, reconciler
and extractor agents, resolved by evidence rather than re-verified. The
pre-committed fallback is scoped to exactly one surface: if ADK's token-streaming
path cannot meet BAR-330's first-visible-token criterion, or its session surface
cannot meet BAR-334's per-turn externalization, within one bounded attempt of no more
than three hours, the **interview service only** drops to direct GenAI SDK calls with
our own turn loop. The reconciler and extractor remain on ADK regardless.

**What the code does.** `src/baraza/agents.py` is the ADK layer. Its import block
(lines 118-122) pulls `LlmAgent`, `LlmCallsLimitExceededError` and `RunConfig`
from `google.adk.agents`, `InMemoryRunner` from `google.adk.runners` and
`FunctionTool` from `google.adk.tools`; `build_extractor`, `build_reconciler` and
`build_interviewer`
each return a real `LlmAgent` — carrying a model pin resolved through
`schema/models.py`, a role instruction, its own tool list, and
`disallow_transfer_to_parent` / `disallow_transfer_to_peers` set so that no
reasoning agent can hand work to the approver. The approver is deliberately *not*
an `LlmAgent`: promotion is the one operation that must never be a model's
judgement call, so the surface that performs it has no model.

The version resolved in the build environment is `google-adk` 2.6.2.

**What is claimed, and what is not.** The requirement is that the project uses a
Google agent-development framework, and it does. But this file's standing rule is
that a framework is named only if the code uses it, so the boundary is drawn
exactly:

- **Claimed:** ADK is a real dependency of real code. The agents are constructed,
  their tool isolation is enforced, and `tests/unit/test_agents.py` asserts
  `isinstance(fleet.extractor, LlmAgent)` against the genuine ADK class — a test
  that fails if the import ever silently degrades to a stub.
- **Also claimed, as of session B5:** one agent is driven by an ADK `Runner` on a
  real path. `baraza.ingest.extract.AgentClaimExtractor` builds the extractor with
  `read_chunk` and `propose_claim` bound to the chunk under extraction and to the
  three validation gates, opens an `InMemoryRunner`, and bounds the loop with
  `RunConfig(max_llm_calls=MAX_AGENT_TURNS)` and an `asyncio.wait_for` at
  `AGENT_TIMEOUT_SECONDS`. `IngestionPipeline` constructs it whenever the run is
  not offline, which is what the deployed ingest Job runs
  (`deploy/entrypoint-job.sh` invokes `baraza.cli demo-agenda --no-offline`).
  `grep -rn "baraza.agents" src/` now returns a production hit.
- **Not claimed:** that *every* model call in production flows through an ADK
  `Runner`. It does not. The reconciler and interviewer agents are constructed and
  their tool isolation is enforced, but the reconcile Job and the interview service
  still reach the model through `src/baraza/llm.py` directly.
- **Not claimed, and important for anyone watching a recorded demo:** that the
  **offline** path uses ADK. It deliberately does not. An offline run replays
  recorded cassettes, and the ADK `Runner` bypasses the cassette client, so
  `_resolve_agent_extraction` forces the direct path whenever `offline` is true —
  a replay can never be mis-narrated as a live agent loop. Anything shown from
  `make demo` is the direct path; only `--no-offline` exercises ADK.

**The second, independent basis.** `google-genai` — the Google GenAI SDK — is on
every runtime path in the tree (three `from google.genai import types` sites in
`src/baraza/llm.py`, plus one in `src/baraza/ingest/extract.py`), so the
framework requirement has two supports rather than one. Per this file's provenance
rule, note the limit of that argument: the official rules text is not carried in
this repository, so whether the GenAI SDK counts as an *agent-development*
framework is an in-tree inference about wording nobody here can quote. The ADK
basis does not depend on it.

**The fallback was never taken.** BAR-020 pre-commits one deviation — the
*interview service only* dropping to direct GenAI SDK calls if ADK's streaming path
misses BAR-330's first-token budget. That branch was never exercised, because the
bounded attempt it gates was never needed. `docs/framework-decision.md` records
this.

Frameworks and SDKs declared in `pyproject.toml`: `google-adk`, `google-genai`,
`fastapi`, `uvicorn`, `pydantic`, `httpx`, `google-cloud-firestore`,
`google-cloud-storage`, `pypdf`, `pdfplumber`, `openpyxl`, `python-docx`, and the
OpenTelemetry SDK, API and Cloud Trace exporter. `requirements.lock` pins the
exact versions this tree was tested against and `make install` prefers it;
`pyproject.toml` declares the supported ranges. The lock was resolved on Python
3.14/macOS, and the deploy images are `python:3.11-slim`, which do **not** install
from it — that gap is stated in the lockfile's own header and is not closed.

One of those is declared and **not** used by any code path, and is therefore not
claimed anywhere in this file: `google-cloud-storage`. Verify with
`grep -rn "google.cloud.storage\|from google.cloud import storage" src/`, which
returns nothing.

`google-adk` was on that list for the first three build sessions and is no longer:
`grep -rn "google\.adk" src/` returns seven hits in `src/baraza/agents.py` (five
imports and two docstring references), and `grep -rn "baraza.agents" src/` returns
`src/baraza/ingest/extract.py`, which is production code rather than a test.

---

## Claims this repository deliberately does not make

Each of these was available and each was refused, for the same reason: a claim the
repository cannot back is worth less than no claim.

- **Antigravity is not claimed — and the negative finding that used to justify not
  claiming it has been withdrawn.** BAR-020 cited an Aug 8 verification failure from
  a sibling project; the source document was never in this repository and the
  placeholder standing in for it has been deleted. The framework was chosen without a
  published comparison, and `docs/framework-decision.md` now says so. A claim the
  repository cannot back is worth less than no claim — that rule applies to negative
  claims about other people's software too.
- **No agent framework other than ADK is named.** ADK is now claimed, because it is
  imported, instantiated, and driven by a `Runner` on the live ingestion path; it was
  not claimed while it was only a dependency line. What is still *not* claimed is that
  ADK sits on **every** production call path — the reconciler and interviewer reach
  the model directly, and the offline replay path is direct by design. See the
  framework row in full.
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
grep -rn "google\.adk" src/              # the framework row's evidence: 7 hits in agents.py
grep -rn "baraza.agents" src/            # ingest/extract.py — the extractor agent's production caller
make verify-models                       # resolves every pinned model ID against live Vertex
```

Exit codes from `scripts/compliance.py`: `0` green, `1` findings, `2` the audit could
not run. The distinction matters here — `2` is the current state of the PRD audit, and
a gate that skipped its main check while reporting green is the failure this whole
apparatus exists to prevent.
