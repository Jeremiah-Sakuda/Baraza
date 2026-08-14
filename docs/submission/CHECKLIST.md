# Devpost submission checklist — Baraza

**Deadline per `docs/PRD.md` §5: Aug 31, 5:00 PM PDT. Aug 30 is the checklist
walk; Aug 31 is buffer.**

## How to read this

Each item is marked with who can close it:

- **(agent)** — closable by a coding session. No human needed.
- **(human-only)** — requires a browser, an account, a payment method, a
  console, a camera, or a judgment a script cannot make.
- **(agent → human)** — the agent prepares it; a human verifies and submits.

**⚠ Source caveat.** The official rules text is **not in this repository.** It
was pasted into a session prompt and is not committed anywhere in the tree. Every
item below is reconstructed from that prompt and from `docs/PRD.md` §4. Before
submitting, **open the live rules page and re-derive this list against it.**
Items marked **[VERIFY-RULES]** are ones where the exact wording or threshold
matters and a paraphrase is not good enough.

---

## A. Category and eligibility

- [ ] **(human-only)** Category selected on the Devpost form: **The Collaborative
      Partner**. Text prepared in `devpost-description.md`.
- [ ] **(human-only)** Confirm one-prize-per-project still applies and that
      selecting one category does not forfeit consideration under the others.
      **[VERIFY-RULES]**
- [ ] **(human-only)** Entry submitted as an individual, matching how the project
      is described everywhere else.
- [ ] **(human-only)** Confirm eligibility (region, age, employment) against the
      live rules. **[VERIFY-RULES]**
- [ ] **(human-only)** Submission opened on the correct Devpost project page and
      the project is not left in draft.

---

## B. Hosted project URL

- [ ] **(human-only)** A hosted URL exists and is reachable. **Nothing is
      deployed as of this writing.** `deploy/` now carries the Dockerfiles,
      the two Cloud Run service manifests, the Scheduler manifest and the
      Firestore rules, and `scripts/bootstrap_gcp.sh` exists and is
      syntax-clean — but none of it has been run against a project.
- [ ] **(human-only)** URL loads **logged out**, in a private/incognito window,
      from a machine that has never authenticated to the project. Not "should
      work" — actually opened and confirmed.
- [ ] **(human-only)** The logged-out view demonstrates something. A login wall
      that a judge cannot get past is functionally a dead link.
- [ ] **(human-only)** The URL stays live and **free to access until at least
      Oct 1**. **[VERIFY-RULES]** — confirm the exact date on the rules page.
- [ ] **(human-only)** Billing configured so the service is not suspended before
      that date, and budget alerts set. A judged URL that 404s in September
      because credits ran out is a self-inflicted loss.
- [ ] **(agent)** No credential, key, project ID, or service-account file is
      reachable from any public surface. Verify `.gitignore` coverage and grep
      the working tree before the repo goes public.
- [ ] **(human-only)** The hosted instance contains **no real person or
      organization data.** The corpus is synthetic; confirm by reading the
      rendered page, not by trusting the fixture generator.

---

## C. Repository access

- [ ] **(human-only)** Repository is public **or** access is granted to **both**
      of these, per the rules:
      - `testing@devpost.com`
      - `cloudhackathons@google.com`
      Granting one and not the other is a common and fatal miss.
- [ ] **(human-only)** If the repo is private, access is granted with permissions
      that survive the judging window (not a time-limited invite that expires).
- [ ] **(agent)** Repository contains no secrets, no service-account JSON, no
      `.env`. `.gitignore` already covers these; confirm with a history scan, not
      just a working-tree scan — a secret committed and later deleted is still in
      the history.
- [ ] **(agent)** No real person, member, company, or organization name appears
      anywhere in the tree — code, fixtures, comments, docs, commit messages.
- [x] **(agent)** License file present and consistent with `pyproject.toml`.
      `LICENSE` is the Apache-2.0 text; `pyproject.toml` declares Apache-2.0.

---

## D. README with spin-up instructions

- [x] **(agent)** `README.md` exists and `pyproject.toml`'s `readme` key
      resolves. Its status table is the per-command exit-code record; re-run
      those commands and re-date the table before submitting, because a status
      table is stale the moment a session lands.
- [ ] **(agent)** README states what the project is in the first three lines, in
      the PRD §1.3 order.
- [ ] **(agent)** README contains **spin-up instructions a stranger can follow**:
      clone → `make install` → `make demo`, with the prerequisites named
      (Python 3.11+, no GCP project required for the offline path).
- [ ] **(agent)** README documents the seven contract make targets and what each
      proves.
- [ ] **(agent)** README cites the divergence turn by ID (e.g. "see turn `t-14`")
      so a judge can locate the exact exchange in a committed transcript.
      Requires committed transcripts to exist first.
- [ ] **(agent)** README's `## Negative decisions` section, per BAR-501 — no
      vector DB, no ML entity matcher, no destructive merges, no voice, and the
      adaptation mechanism considered and not adopted.
- [ ] **(agent)** Every number in the README traces to a metrics entry or a
      runnable script. Where none exists, the README says `not yet measured`.
- [ ] **(human-only)** A **clean clone on a different machine** runs
      `make install && make demo` green with no network access except Vertex
      (PRD §5, Aug 25 reproducibility gate). This cannot be self-certified from
      the machine that built it.

---

## E. Architecture diagram

- [ ] **(agent → human)** Diagram exists (BAR-505). **None exists in the tree.**
- [ ] **(agent)** Diagram shows the Google Cloud services by name: Cloud Run Jobs
      (ingest, reconcile), Cloud Run services (interview, successor), Firestore,
      Cloud Scheduler, Vertex AI.
- [ ] **(agent)** Diagram shows the four agents and what each may write — the
      separation-of-concerns claim is only credible if the diagram shows the
      write boundaries, not just boxes and arrows.
- [ ] **(agent)** Diagram displays **no unmeasured number.** Every metric is
      currently `not yet measured`, so the diagram carries no figures until a
      measurement run produces them.
- [ ] **(agent)** Diagram names **no framework the code does not import.**
- [ ] **(human-only)** Diagram is embedded in the Devpost gallery and readable at
      the size Devpost renders it. Test at gallery scale, not at full size.

---

## F. Video

- [ ] **(human-only)** Recorded from `docs/submission/video-script.md`.
- [ ] **(human-only)** **Duration ≤ 4:00**, verified in the editor's timeline, not
      estimated. Script is budgeted to 3:50.
- [ ] **(human-only)** Uploaded to **YouTube or Vimeo**. **[VERIFY-RULES]** —
      confirm which platforms are accepted.
- [ ] **(human-only)** Video is **public**, not unlisted, if the rules require
      public. **[VERIFY-RULES]** Confirm by opening the link logged out, in a
      private window.
- [ ] **(human-only)** No copyrighted music. Silence is fine.
- [ ] **(human-only)** **Google Cloud proof frames present** (mandatory):
      - [ ] Cloud Run console showing the deployed services and jobs
      - [ ] Vertex AI request logs
      - [ ] Cloud Scheduler **execution history** with nightly runs visible
- [ ] **(human-only)** The `.run.app` URL is **spoken aloud** and visible on
      screen, and is the same URL submitted on the form.
- [ ] **(human-only)** The centrepiece terminal section is one unedited take —
      no cuts, no speed ramps.
- [ ] **(human-only)** Every visible string in every frame is synthetic. Freeze
      and read the corpus frames before the cut is locked.
- [ ] **(human-only)** No unmeasured number is spoken or captioned. Cross-check
      against the "what must NOT be claimed" list in the script.
- [ ] **(human-only)** Video link added to the Devpost form **and** the link
      opens for a logged-out viewer.

---

## G. Language

- [ ] **(agent)** All submission text is in English: description, README, repo
      docs, diagram labels.
- [ ] **(human-only)** Video narration and any on-screen text is in English, or
      subtitled in English. **[VERIFY-RULES]**

---

## H. Bonus URLs

- [ ] **(human-only)** **Blog post** published (dev.to or Medium) from
      `blog-post.md`, and the URL added to the submission.
- [ ] **(human-only)** Blog post contains the required "created for the purposes
      of entering this hackathon" statement, in the **exact wording the rules
      specify**. **[VERIFY-RULES]** — the draft carries a paraphrase and a note
      to replace it.
- [ ] **(human-only)** **Social posts** published from `social-posts.md` (X and
      LinkedIn), each carrying `#AllThingsAgenticHackathon` exactly.
- [ ] **(human-only)** Social post URLs added to the submission form.
- [ ] **(human-only)** Posts are **publicly visible** — a LinkedIn post set to
      connections-only earns nothing.
- [ ] **(agent → human)** **Additional models** bonus: Gemma is used as the
      ingestion relevance pre-filter and an embedding model is used for blocking
      key expansion, both pinned in `src/baraza/schema/models.py`. The claim is
      only submittable once the pre-filter has actually run in `gemma` mode in a
      supervised session — currently `gemma_prefilter_mode_used` is
      `not yet measured`, so **the bonus is not yet earned.** **[VERIFY-RULES]**
      on what counts as "used".

---

## I. Google Cloud requirements

- [ ] **(agent → human)** **≥1 Google agent framework used.** ⚠ **Currently
      unmet.** `google-adk` is declared in `pyproject.toml`; **no module under
      `src/` imports it.** The runtime path is `google.genai` via
      `src/baraza/llm.py`. Either wire ADK into a shipped path, or state plainly
      that the runtime is the GenAI SDK and re-check whether that satisfies the
      requirement. **[VERIFY-RULES]** — this is the highest-risk open item in
      this file.
- [ ] **(agent)** `docs/framework-decision.md` updated to record which branch
      actually shipped, and the compliance matrix updated to match in the same
      commit.
- [ ] **(human-only)** **≥1 Google Cloud infrastructure service used**, provably:
      Cloud Run, Firestore, Cloud Scheduler. Requires deployment.
- [ ] **(human-only)** Vertex AI used for all model calls, with logs to prove it.
- [ ] **(agent)** `make verify-models` runs green. The script exists;
      **it has never run.** It exits **3** ("could not run") because
      `BARAZA_PROJECT_ID` is unset and is deliberately not defaulted. Until it
      exits 0, no artifact states which model version shipped.
- [ ] **(human-only)** Scheduler execution history shows **≥10 nightly reconcile
      runs** before recording day (BAR-410), with the stub-to-real replacement
      date identifiable. ⏳ **Time-gated — requires ten nights.** Nothing is
      deployed, so the clock has not started.
- [ ] **(agent)** Scheduler runs are labelled as scheduled anywhere runs or
      traffic are counted. Never presented as organic activity.

---

## J. Repo-internal blockers that gate everything above

Recorded here because a submission checklist that ignores the state of the tree
is a wish list. Re-verified by running every command on **2026-08-13** (session
B3); the closed items below are closed because a command was run, not because a
file appeared.

**Still red:**

- [ ] **(agent)** `fixtures/cassettes/` holds no recordings, so `make demo`,
      `make demo-agenda` and `make demo-interview` all exit 2 before doing any
      work. **This is now the top blocker** — it is upstream of the transcripts,
      of every behavioural probe in `make verify-manifest`, of every citation in
      `make verify-anchors`, and of `make adaptation-metric`. Recording is a
      supervised step: `python3 scripts/record_cassettes.py --yes`, which costs
      live Vertex calls.
- [ ] **(agent)** `docs/PRD.md` merged, so `make compliance` runs its actual
      BAR-007 audit instead of exiting 2. ~35 requirement IDs currently have no
      acceptance criteria in the tree. `make gate` is red for this reason alone.
- [ ] **(human-only)** `docs/antigravity/decision.md` is a **placeholder**. Copy
      the original Aug 8 finding in with an attribution header, or delete the
      citation from BAR-020 and state that the framework was chosen without a
      published comparison. Do not summarize a document nobody can check.
- [ ] **(agent)** `fixtures/transcripts/` does not exist; it is written by replay
      runs, so it unblocks when the cassettes land.
- [ ] **(agent)** `fixtures/golden-log.jsonl` does not exist. `AGENTS.md`'s repo
      layout names it; the verifiers look for it and fall back to
      `out/events.jsonl`.
- [ ] **(agent)** No module imports ADK — see section I and `docs/compliance.md`.
- [ ] **(agent)** `docs/BUILD-LOG.md` has no entry for sessions **B1** or **B2**,
      both of which are in the commit history. The session protocol requires the
      entry before the commit; two sessions skipped it, and the prompts are not
      recoverable after the fact.

**Now green, each verified by running it on 2026-08-13:**

- [x] `src/baraza/cli.py` exists and all four CLI-backed targets reach their
      cassette check before failing.
- [x] `scripts/verify_manifest.py` — `found 18 of 18 planted problems`, exit 2
      pending an event log.
- [x] `scripts/verify_anchors.py` — 11 sources re-registered from bytes on disk,
      exit 2 pending an event log.
- [x] `scripts/adaptation_metric.py` — exit 1, refuses to score an empty corpus
      of transcripts rather than printing a zero.
- [x] `scripts/generate_corpus.py` — exit 0, 13 artifacts, every one round-tripped
      through the project's own readers.
- [x] `scripts/verify_models.py`, `scripts/with_emulator.sh` — exist; both report
      "could not run" honestly when their prerequisite is absent.
- [x] `fixtures/` carries `BIBLE.md`, `MANIFEST.md`, the generated corpus, the
      entity gold set and both interview personas.
- [x] `tests/` — 154 passed across `tests/unit` (8 modules) and `tests/property`.
      `tests/emulator` holds the SIGKILL rig; its JSONL half passes with no
      emulator (`pytest tests/emulator -k jsonl`).
- [x] `deploy/` carries both Dockerfiles, both service manifests, the Scheduler
      manifest, the Firestore rules, `bootstrap_gcp.sh` and `teardown.sh`. Every
      shell script in `scripts/` and `deploy/` passes `bash -n`.
- [x] `LICENSE` and `README.md` both exist.
- [x] `python3 scripts/compliance.py --no-prd` passes all four invariant lints
      (visibility boundary, model pin location, temporal comparison, metrics
      provenance), each originally verified by planting a violation and watching
      it fail.

---

## K. Day-of submission walk (Aug 30)

Do these in order, on the day, in one sitting:

1. **(human-only)** Open the live rules page. Re-derive sections A–H against it.
   Note every **[VERIFY-RULES]** item resolved.
2. **(agent)** `make gate` green on a clean clone.
3. **(human-only)** Clean clone on a second machine; `make install && make demo`.
4. **(human-only)** Open the hosted URL in a private window. Click through the
   demo path as a logged-out judge would.
5. **(human-only)** Open the video link in a private window. Watch it to the end.
   Confirm the timer stops at or under 4:00.
6. **(human-only)** Open the repo URL in a private window, or confirm both
   access grants are live.
7. **(human-only)** Open the blog URL and both social URLs in a private window.
8. **(agent)** Grep every submission artifact for placeholders: `<`, `TODO`,
   `TBD`, `XXX`. Zero hits before submitting.
9. **(agent)** Grep every submission artifact for numbers. Every one traces to a
   metrics entry with a run ID, or the artifact says `not yet measured`.
10. **(human-only)** Paste `devpost-description.md` into the form field by field.
    Category: The Collaborative Partner.
11. **(human-only)** Submit. Then reload the public submission page **logged
    out** and read it as a judge would.
12. **(agent)** Append the submission to `docs/BUILD-LOG.md` with the URLs, and
    record in `docs/FINDINGS.md` what was still unmeasured at submission time.

---

## What this checklist will not do for you

It will not tell you that a number is wrong. Every artifact in
`docs/submission/` currently writes `not yet measured` where a number belongs,
because that is the true state. The moment a measurement run produces a real
value, it goes into `docs/metrics.json` with a run ID and a date, and **only
then** does it appear in a description, a diagram, a post, or a narration line.

The failure mode this whole directory is built against: a plausible number typed
into a submission field at 4 a.m. because the field looked empty.
