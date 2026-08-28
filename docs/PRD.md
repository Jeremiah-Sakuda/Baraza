# Baraza — Product Requirements Document

**Version:** 1.2 (ADK-aligned) · **Date:** 2026-08-28 · **Category:** The Collaborative Partner

Baraza is succession intelligence: it turns a synthetic organization archive into
a citation-grounded disputed ledger, then conducts an agenda-led exit interview.
The product’s central claim is the *agenda inversion*: the corpus identifies what
it disagrees about before the human is asked to explain it.

## 1. Product and non-negotiable constraints

The runtime uses Gemini through Vertex AI. Google ADK is the sole agent framework;
the narrow direct GenAI SDK fallback is limited to the interview service as recorded
in `docs/framework-decision.md`. Claims are append-only events and graph state is a
deterministic fold. Visibility defaults to `private`, `readable_by()` is the only
read boundary, rejected claims retract, every claim carries a resolvable citation,
and every time comparison uses UTC epoch milliseconds.

The corpus is wholly synthetic. The project does not claim enterprise deployment,
a vector database, destructive identity merges, voice/TTS, or a real entity matcher.

## 2. Hackathon compliance matrix

| Requirement | Evidence | Requirement IDs |
|---|---|---|
| Gemini via Vertex AI and ADK | Pinned model module, ADK agents and Runner-backed extraction path | BAR-020, BAR-301 |
| Collaborative Partner: persistent, contextual dialogue | Agenda-led interview, cited divergence, approval/rejection, static graph diff, persisted sessions, successor retrieval | BAR-330, BAR-331, BAR-332, BAR-333, BAR-334, BAR-335, BAR-336, BAR-338, BAR-339, BAR-340 |
| Autonomous workflow and Cloud infrastructure | Ingest/reconcile Jobs, Scheduler, Firestore, Cloud Run services | BAR-021, BAR-306, BAR-321, BAR-322, BAR-323, BAR-410, BAR-411 |
| Reproducible submission | Cache-backed demo, verification targets, README, diagrams, deployment scripts | BAR-007, BAR-501, BAR-502, BAR-505, BAR-506, BAR-510 |
| Submission evidence | Public video, social, blog and Devpost materials | BAR-601, BAR-602, BAR-603, BAR-604, BAR-605, BAR-606, BAR-607, BAR-608, BAR-620, BAR-621, BAR-622, BAR-623, BAR-624 |
| Corpus and ingestion correctness | Native-format corpus, manifest, replay, citations, temporal/blocking detection | BAR-101, BAR-102, BAR-103, BAR-104, BAR-105, BAR-106, BAR-302, BAR-303, BAR-304, BAR-305, BAR-307, BAR-308, BAR-320 |
| Foundations and operations | Public-repo hygiene, gates, budget protection and build record | BAR-001, BAR-002, BAR-004, BAR-006, BAR-008, BAR-009, BAR-010 |

## 3. Architecture

Cloud Run ingestion reads chat exports, scans, spreadsheets, and minutes; claim
extraction appends proposed/private claims to Firestore. Reconciliation performs
blocked, temporally-gated contradiction detection and produces a ranked ledger and
interview agenda. The interview service persists turns and approval decisions. The
successor service exposes only committed claims readable by its configured audience.
Cloud Scheduler invokes the reconcile Job, and scheduled work is always labelled as
such rather than counted as organic activity.

## 4. Requirements

**BAR-001** — Maintain an auditable public repository history.

**BAR-002** — Prevent secrets from entering source control.

**BAR-004** — Disclose any prior-work lineage accurately.

**BAR-006** — Keep mechanical gates and explicit scope consequences.

**BAR-007** — `make compliance` audits this PRD and invariant lints.

**BAR-008** — Bound cloud spend and provide a safe teardown path.

**BAR-009** — Record relevant platform findings in the build log.

**BAR-010** — Keep a dated build log and findings record.

**BAR-020** — Use ADK as the agent framework; direct SDK fallback is narrowly bounded.

**BAR-021** — Label Cloud Scheduler work as scheduled, never organic activity.

**BAR-101** — Maintain a synthetic cross-artifact chapter corpus.

**BAR-102** — Parse corpus artifacts through native readers.

**BAR-103** — Verify planted corpus behavior and publish misses.

**BAR-104** — Provide hands-off replay fixtures for interviews.

**BAR-105** — Persist proposed interview claims before the next turn.

**BAR-106** — Keep submission material drafted before recording.

**BAR-301** — Pin and verify Vertex model identifiers.

**BAR-302** — Chunk sources with bounded, session-aware input sizes.

**BAR-303** — Route optional Gemma pre-filtering safely and disclose its evidence.

**BAR-304** — Require and verify native citation anchors on every claim.

**BAR-305** — Resolve aliases non-destructively and resist decoy merges.

**BAR-306** — Enforce append-only event writes and approval-only promotion.

**BAR-307** — Retrieve only independently citable claims.

**BAR-308** — Make ingestion and interview writes idempotent across retries.

**BAR-320** — Detect contradictions through blocking and temporal overlap, not all pairs.

**BAR-321** — Render a ranked, audience-safe disputed ledger.

**BAR-322** — Generate citation-grounded interview agenda items from the ledger.

**BAR-323** — Prove a differential ledger response to newly available evidence.

**BAR-330** — Run an agenda-led, structurally adaptive interview.

**BAR-331** — Surface citation-grounded testimony/document divergence.

**BAR-332** — Support approve, edit, reject, and explicit visibility choice.

**BAR-333** — Render graph state as a static fold diff.

**BAR-334** — Externalize session state and survive a mid-turn kill.

**BAR-335** — Refuse successor synthesis not supported by readable citations.

**BAR-336** — Exclude voice input and TTS from scope.

**BAR-338** — Retire resolved questions and regenerate the agenda unattended.

**BAR-339** — Demonstrate cross-session personalization from committed memory.

**BAR-340** — Prove the visibility boundary holds off the demo path.

**BAR-410** — Deploy the Cloud Run and Firestore path with evidence.

**BAR-411** — Provide read-only public ledger and agenda surfaces with scale-to-zero limits.

**BAR-501** — Provide a deterministic, credential-free offline demo when cassettes exist.

**BAR-502** — Document reproduction, provenance, findings, and negative decisions.

**BAR-505** — Maintain an architecture diagram that reflects code and deployment.

**BAR-506** — Provide reproducible bootstrap, teardown, lockfile, and pin workflows.

**BAR-510** — Make ADK and build-toolchain evidence easy for a judge to locate.

**BAR-601** — Open the video with the turnover problem and synthetic-data disclosure.

**BAR-602** — Show the heterogeneous source artifacts.

**BAR-603** — Show the causal chain from scheduled reconciliation to ledger and agenda.

**BAR-604** — Show the contradiction catch, approval, and graph change in one take.

**BAR-605** — Show a cited successor answer and a role-scoped refusal.

**BAR-606** — Show Cloud Run/Vertex execution evidence.

**BAR-607** — Show in-session and cross-session adaptation evidence.

**BAR-608** — Disclose replay precisely and visibly.

**BAR-620** — Publish an eligible project social post.

**BAR-621** — Publish an eligible project build article.

**BAR-622** — Complete the Devpost description fields accurately.

**BAR-623** — Claim an additional Google model only after it is evidenced.

**BAR-624** — Run the final logged-out submission checklist before the deadline.

## 5. Verification policy

Tests prove properties, not merely code paths. A red prerequisite stays red; the
project must never synthesize a cassette, citation, measurement, or deployment claim
to make a target look green. `docs/metrics.json` is the source of truth for values
that require a real run.
