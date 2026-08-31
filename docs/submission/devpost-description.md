# Devpost submission text — Baraza

> **How to use this file.** The headings map to Devpost's fixed fields. This is
> an individual entry; prose is first person singular. Paste each section into
> its field.
>
> **Numbers.** This document contains no unmeasured numbers. Where a
> measurement does not yet exist, the sentence is written without a number
> rather than with a placeholder — a Devpost field is not the place to announce
> that a metric is missing, and inventing one is prohibited by the project's
> own rules. Any figure added later must trace to `docs/metrics.json` with a
> run ID.
>
> **Before submitting:** replace nothing blindly — there are no `<…>`
> placeholders left in this file except the hosted URL and video URL fields on
> the form itself, which come from the recording-day checklist.

---

## Category

**The Collaborative Partner.**

---

## Inspiration

I run a lot of AI sessions in a week, and I have typed the same corrections
into them more times than I can defend: never pad estimates. Cite the source
before the number. I decide what's visible, not you. Every product I use now
has a "memory" feature, and every one of those memories is an opaque blob — a
paraphrase of me I never approved, with no source, no date, and no way to
retract it that I can verify. When it's wrong, it's wrong silently. When I
contradict myself — and I do — it silently keeps whichever version it heard
last, which means it isn't adapting to me; it's erasing me.

So the question behind Baraza is not "how does an agent remember the user" but
**"what would it take for a user to trust the file an agent keeps on them?"**
My answer is borrowed from institutions that already solved trust in records:
due process. Verbatim quotes. An append-only record. The right to confront
contradictions. The right to inspect and retract. *Baraza* is a Swahili word
for the council place where disputes are heard in public and settled on the
record — and the dispute this one hears is you-of-Tuesday versus
you-of-Thursday.

## What it does

Baraza is a working partner that drafts documents with you while building an
auditable model of how you think — and it will not act on any belief about you
that you haven't ratified.

- **Every belief is a claim with evidence.** When you state a preference, rule,
  or judgment mid-session, it becomes a claim carrying your verbatim quote and
  a turn anchor pointing at the exact exchange. A fabricated anchor is a stop
  condition, not a warning.
- **The log cannot be quietly rewritten.** Claims append to a Firestore event
  log whose deployed security rules reject update and delete — you can attempt
  an edit in the console and watch the rules refuse. Fixing anything means
  appending a superseding event.
- **It catches you contradicting yourself.** The contradiction detector runs on
  the user's own statements. When today's instruction collides with a rule you
  committed last week, a divergence card fires with both quotes and both
  timestamps, and the agent refuses to silently overwrite the old rule until
  you adjudicate — often by splitting it into a conditional, which is where
  judgment-shaped beliefs come from.
- **Nothing acts without ratification.** No belief reaches `committed` — and
  therefore behavior — except through the approval flow. Approvals batch at
  session end. Rejecting a belief later is one click, the retraction is itself
  an append-only event, and rerunning the same task shows the difference.
- **Doctrine, with provenance.** Committed beliefs compile into the session's
  operating policy, and every rule carries the claim ID and quote that put it
  there. The compilation is replayable byte for byte: same doctrine, every rule
  cited. The doctrine diff between two points in time names which belief
  changed which rule.
- **It leads.** A scheduled job reads the log, builds an agenda from open
  contradictions and stale beliefs, appends a session proposal honestly
  labelled `scheduled`, and invites you. Resolved items retire themselves on
  the record, so the next session is visibly shorter than the last.

## The six phrases, as mechanisms

1. **Leads the way** — Cloud Scheduler → reconcile job → agenda from the
   ledger → `session.proposed` event (labelled `scheduled`, never passed off
   as organic) → outbound invitation. The agent opens the session speaking
   first, each agenda item citing the ledger entry that spawned it.
2. **Takes notes** — turn-level claim extraction: quote mandatory, anchor
   `turn:t-N`, appended to the log that rejects edits. A live claim panel shows
   beliefs landing as you speak.
3. **Asks clarifying questions** — a question exists only because the disputed
   ledger says two of your own statements collide, or a rule is too
   under-specified to compile. No filler questions, by construction.
4. **Guides step-by-step** — the agenda state machine drives the real work item
   by item; resolved contradictions retire their own agenda items, closing the
   loop between sessions.
5. **A clear way to capture feedback** — feedback *is* the approval flow: the
   dossier view lists every belief with its quote and the moment it was
   learned; ratify in batches, reject with one click, and the same task reruns
   under the amended doctrine.
6. **Constantly adapts to the user's unique way of thinking** — the doctrine
   compiler folds committed beliefs into policy with rule←claim provenance.
   Extraction targets judgment shape — conditions, thresholds, exceptions —
   not tone sliders. The doctrine diff shows exactly which belief changed
   which rule.

## How I built it

Python 3.11+, on Google Cloud end to end:

- **Agent Development Kit (ADK)** — the extraction agent is driven by an ADK
  `Runner` with tools bound to real validation gates (anchor resolution, quote
  verification), bounded by call and time limits.
- **GenAI SDK on Vertex AI** — every model call. **Gemini 3.7 Flash** for
  reasoning (adjudication, agenda synthesis, the divergence turn) and
  **Gemini 3.5 Flash** for fast paths, both live-verified against the project
  before any document was allowed to name them.
- **Cloud Run** — the web face and services, plus jobs for ingestion and the
  nightly reconcile.
- **Firestore** — the append-only event log; `create`-only security rules
  deployed and verified live by a script that attempts the forbidden writes.
  Every graph state is a fold over the log; there is no mutable store.
- **Cloud Scheduler** — the initiation trigger, with every scheduled run
  labelled as such in the log.
- **Artifact Registry + Cloud Build** — container images for the jobs and
  services.

Design decisions worth naming: visibility defaults to private and the read
predicate fails closed; quote text is structurally unreachable except through
an audience-checked accessor, enforced by a compliance lint that fails the
build; all time comparisons are integer epoch millis — ISO strings are
serialization only; and model IDs live in exactly one module, with a lint that
fails the build on a literal anywhere else.

## Challenges I ran into (true war stories)

- **The ISO-sort trap.** Comparing timestamps as strings passes every obvious
  test and fails across date boundaries under mixed UTC offsets: the repo's
  planted counterexample is `2026-05-01T20:00:00-05:00` vs
  `2026-05-02T00:00:00Z` — string order says the first is earlier; it is an
  hour later. The intuitive illustration everyone reaches for doesn't actually
  diverge, which is exactly how this bug survives review. Epoch millis
  everywhere is now a build-failing lint, not a convention.
- **The scheduled-vs-manual honesty bug.** An early job image hardcoded
  `scheduled=True` on every append, so a manual test run was recorded as a
  scheduled one — in an append-only log, where it cannot be edited away. The
  fix distinguishes trigger provenance at write time; the mislabelled event is
  documented rather than deleted, because the log's whole point is that you
  can't quietly fix history.
- **Model pins that didn't exist.** The original model pins were plausible
  literals nobody had checked — one of them named a model that does not exist
  in the Vertex catalog, and the models that do exist only resolve at
  location `global`, not the regional endpoint the deploy scripts assumed.
  A verification script now resolves every pin against live Vertex, and no
  document in the repo may name a model version until it exits green. A pinned
  literal nobody checked is a plausible value where a verified one belongs.
- **A Cloud Scheduler 403 that survived every correct IAM grant.** The service
  account could invoke the Run job with its own token; Scheduler, configured
  identically, could not — and audit logs showed its requests never arriving
  authenticated as that SA. Rather than widening permissions until the error
  went away (the repo bans that move by name), the failure was root-caused,
  documented in a stop file, and rearchitected: Scheduler → OIDC → a service
  endpoint that runs the job with its own runtime identity.
- **Tests that pass while the thing they test cannot work.** A tool-wrapping
  shim dropped function signatures, so every agent tool reached the model
  declared as taking no parameters — while every isolation test stayed green,
  because the tests asserted over tool *names*. The repaired tests ask a
  capability question instead of a naming question.

## Accomplishments I'm proud of

Contradiction detection pointed at the user — with both quotes on screen and a
refusal to silently overwrite — is something I haven't seen elsewhere, and it
only works because the claim/anchor/append-only substrate makes both sides of
the collision citable. The edit-refusal demo in the Firestore console is the
product in one shot: a memory you can trust because you can watch it refuse to
be rewritten. And the project's honesty rules held under deadline pressure:
unmeasured numbers stayed unwritten, a mislabelled event stayed documented
instead of deleted, and a permission problem stopped the build instead of
being widened away.

## What I learned

Due process is an engineering pattern, not a metaphor: quotes are evidence,
approval is jurisdiction, retraction is appeal, and an append-only log is the
court record. The compiler that turns ratified beliefs into policy can be
replayable byte for byte — but the model's compliance with that policy is
probabilistic, and the honest formulation is "same doctrine, every rule
cited," never "same behavior." Measuring the gap between policy and behavior,
and showing the imperfect number, beats promising a perfect one.

## What's next for Baraza

The dossier as a trust layer, not an app: any personalized agent — in law,
medicine, finance, or your pocket — will eventually need an auditable,
retractable, provenance-tracked user model, and right-to-inspect regulation
points the same direction. Nearer term: longer dogfooding to grow the belief
corpus, the compliance battery run on a schedule with its numbers published as
measured, and the same engine pointed at a second subject — an organization's
records instead of a person's — which is where this project began.

## Built with

`python` · `google-adk` · `google-genai` · `vertex-ai` · `gemini` ·
`cloud-run` · `firestore` · `cloud-scheduler` · `artifact-registry` ·
`cloud-build` · `fastapi` · `pytest`
