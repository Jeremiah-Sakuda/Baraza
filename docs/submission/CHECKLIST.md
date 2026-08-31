# Devpost submission checklist — Baraza (DOSSIER pivot)

**Deadline: today, 2026-08-31, 5:00 PM PDT.** This checklist was rewritten
2026-08-31 against the current state of the tree and the live `baraza-2026`
project. Items marked done are done because a command ran or a record in the
repo says so, with the evidence named — not because a file exists.

## How to read this

- **(agent-done)** — closed by a coding session; evidence cited.
- **(agent)** — closable by a coding session; not yet closed.
- **(user-only)** — requires your browser, your accounts, your camera, or your
  judgment.

**⚠ Source caveat (still true).** The official rules text is not committed in
this repository. Every item below derives from the rules as pasted into
session prompts. Before submitting, open the live rules page and re-derive
sections A–H against it; items tagged **[VERIFY-RULES]** are where exact
wording matters.

---

## A. Category and eligibility

- [ ] **(user-only)** Category selected on the form: **The Collaborative
      Partner**. Text prepared in `devpost-description.md` (rewritten for the
      dossier pivot, 2026-08-31 — do not paste an older cached copy).
- [ ] **(user-only)** Confirm one-prize-per-project and cross-category
      consideration against the live rules. **[VERIFY-RULES]**
- [ ] **(user-only)** Entry submitted as an individual, matching how the
      project describes itself everywhere.
- [ ] **(user-only)** Eligibility (region, age, employment) confirmed against
      the live rules. **[VERIFY-RULES]**
- [ ] **(user-only)** Submission is on the correct Devpost project page and not
      left in draft.

---

## B. Hosted project URL

- [x] **(agent-done)** A deployment exists. `baraza-2026` is live: Firestore
      with append-only rules verified live, Artifact Registry images, four
      least-privilege service accounts, two Cloud Run jobs, two Cloud Run
      services. Evidence: `STOPPED-DEPLOY.md` (2026-08-15) and commit
      `c5bb3fa`. The public URL verified then, HTTP 200 logged out:
      `https://baraza-successor-tlaymplktq-uc.a.run.app`.
- [ ] **(user-only)** Confirm which URL is current on submission day. If the
      dossier web face (WS2) redeployed the public surface under a new service
      name, the form, the video narration, and this file must all carry the
      **same** URL. One URL, three places, byte-identical.
- [ ] **(user-only)** URL loads **logged out**, in a private window, from a
      machine that never authenticated to the project. Actually opened, not
      "should work."
- [ ] **(user-only)** The logged-out view demonstrates something — the judge
      pages must render without credentials. A login wall is a dead link.
- [ ] **(user-only)** URL stays live and free to access through the judging
      window (do **not** run `make teardown` before Oct 1). **[VERIFY-RULES]**
      on the exact end date.
- [ ] **(user-only)** Billing budget alert set so the service is not suspended
      mid-judging.
- [x] **(agent-done)** No credential, key, or service-account file reachable
      from any public surface — full-history secret scan came back clean before
      the repo went public (`docs/BY-HAND.md` H1).
- [ ] **(user-only)** The hosted instance shows no real person or organization
      data. The corpus is synthetic and the dossier subject is the builder
      himself; confirm by reading the rendered pages, not the generator.

---

## C. Repository access

- [x] **(agent-done)** Repository is **public** at
      <https://github.com/Jeremiah-Sakuda/Baraza>. Public satisfies the access
      requirement outright; the grants to `testing@devpost.com` and
      `cloudhackathons@google.com` are only needed if it ever goes private —
      in that case grant **both**, with invites that survive the judging
      window.
- [ ] **(user-only)** Open the repo URL in a private window on submission day
      and confirm it is still public and shows the latest push.
- [x] **(agent-done)** No secrets in history or working tree (scan cited in
      §B). `.gitignore` covers env files and service-account JSON.
- [ ] **(agent)** Re-grep the tree before the final push: no real person,
      member, or company named anywhere — code, fixtures, comments, docs,
      commit messages.
- [x] **(agent-done)** `LICENSE` (Apache-2.0) present and consistent with
      `pyproject.toml`.

---

## D. README with spin-up instructions

- [ ] **(agent)** README rewritten for the dossier framing (WS7). The pitch in
      the first three lines is the dossier pitch, not the succession pitch.
      Until this lands, the README contradicts the submission.
- [ ] **(agent)** Spin-up instructions a stranger can follow: clone →
      `make install` → `make demo`, prerequisites named (Python 3.11+, no GCP
      project required for the offline path).
- [ ] **(agent)** Every number in the README traces to a metrics entry or a
      runnable script; where none exists it says `not yet measured`.
- [ ] **(user-only)** Clean clone on a **different machine** runs
      `make install && make demo` green. Cannot be self-certified from the
      machine that built it.

---

## E. Architecture diagram

- [x] **(agent-done)** Diagram exists: `docs/architecture.md` (Mermaid) and
      `docs/architecture.svg` (self-contained, legible in light and dark),
      naming the Google Cloud services (Cloud Run services and jobs, Firestore,
      Cloud Scheduler, Vertex AI), showing that approval is the only writer of
      `claim.committed`, displaying no unmeasured number and naming no
      framework the code does not import.
- [ ] **(agent)** Update the diagram's labels for the pivot where they still
      say "successor"/"exit interview" — the mechanism is unchanged but a judge
      reading the diagram against the video must not find two projects.
- [ ] **(user-only)** Diagram embedded in the Devpost gallery and readable at
      the size Devpost renders it.

---

## F. Video

- [ ] **(user-only)** Recorded from `docs/submission/video-script.md`
      (rewritten 2026-08-31 for the dossier demo — the old succession script
      is gone; record from the current file only).
- [ ] **(user-only)** Duration ≤ 4:00, verified in the editor's timeline.
      Script is budgeted to 3:50.
- [ ] **(user-only)** Uploaded to YouTube or Vimeo. **[VERIFY-RULES]** on
      accepted platforms and on public-vs-unlisted; confirm by opening the
      link logged out.
- [ ] **(user-only)** No copyrighted music. Silence is fine.
- [ ] **(user-only)** Google Cloud proof frames present (mandatory):
      - [ ] Cloud Run console — deployed services and jobs
      - [ ] Vertex AI request logs — `gemini-3.7-flash` / `gemini-3.5-flash`
            calls visible
      - [ ] Cloud Scheduler execution history — **only if the trigger fix has
            landed and runs are green**; otherwise film the Run job execution
            list and use the honest fallback narration in the script (Shot 5
            precondition).
- [ ] **(user-only)** The `.run.app` URL spoken aloud, visible on screen, and
      identical to the URL on the form.
- [ ] **(user-only)** The centrepiece (Shot 3) is one unedited take against
      live Vertex — no cuts, no cassettes.
- [ ] **(user-only)** Every visible string in every frame is synthetic or the
      builder's own. Freeze-frame pass before locking the cut.
- [ ] **(user-only)** No unmeasured number spoken or captioned — walk
      Appendix B of the script against the locked cut.
- [ ] **(user-only)** Video link added to the form and opens for a logged-out
      viewer.

---

## G. Language

- [x] **(agent-done)** All submission text is in English: description, README,
      repo docs, diagram labels, this directory.
- [ ] **(user-only)** Video narration and on-screen text in English (or
      English-subtitled). **[VERIFY-RULES]**

---

## H. Bonus URLs

- [ ] **(user-only)** Blog post published (dev.to or Medium) from
      `blog-post.md` and the URL added to the submission. The draft's first
      line carries the "created for the purposes of entering this hackathon"
      statement — **[VERIFY-RULES]** confirm the exact required wording and
      adjust before publishing.
- [ ] **(user-only)** Social posts published from `social-posts.md` (one X, one
      LinkedIn variant), each carrying `#AllThingsAgenticHackathon` exactly,
      each publicly visible, URLs added to the form. Replace `<VIDEO-URL>` /
      `<BLOG-URL>` placeholders before posting.
- [ ] **(user-only)** **Additional-models bonus: claim only if earned.** The
      Gemma pre-filter's endpoint-aware call path was deliberately left
      unwritten (see `docs/FINDINGS.md`, B5 addendum) and
      `gemma_prefilter_mode_used` is `not yet measured`. Unless that changed
      in a supervised session with evidence, **do not claim this bonus.**

---

## I. Google Cloud requirements

- [x] **(agent-done)** ≥1 Google agent framework used: ADK agents built and an
      ADK `Runner` on the production extraction path
      (`src/baraza/ingest/extract.py`; `grep -rn "google\.adk" src/`). The
      GenAI SDK is on every model call path (`src/baraza/llm.py`). Two honest
      limits, stated in `docs/compliance.md`: the reconciler and interviewer
      agents are built but reach the model through `llm.py`, and offline
      replay is deliberately the direct path — nothing filmed from `make demo`
      is an agent loop.
- [x] **(agent-done)** ≥1 Google Cloud infrastructure service used, provably:
      Cloud Run, Firestore, Cloud Scheduler all deployed on `baraza-2026`
      (`STOPPED-DEPLOY.md`, commit `c5bb3fa`).
- [x] **(agent-done)** Model pins live-verified against Vertex on 2026-08-31:
      `gemini-3.7-flash` (reasoning), `gemini-3.5-flash` (fast),
      `gemini-embedding-001`, location `global` — recorded in
      `src/baraza/schema/models.py` (commit `9c05a46`). The originally pinned
      pro model **did not exist** in the catalog; this is why the
      verify-before-quote rule exists.
- [ ] **(user-only)** Vertex AI request logs captured for the video, showing
      the two Gemini models under project `baraza-2026`.
- [ ] **(user-only)** Scheduler: the direct trigger 403s (root-caused
      2026-08-31 to Scheduler's OAuth token path — `STOPPED-DEPLOY.md`
      update). The OIDC-via-service fix is WS1's to deploy. On submission day,
      state only what the execution history actually shows; scheduled runs are
      labelled `scheduled` wherever counted, never presented as organic.
- [ ] **(agent)** After any deploy change: `scripts/verify_append_only.sh`
      green, and the job image postdates commit `0fca155` so manual runs are
      not recorded as scheduled.

---

## J. Repo-internal blockers that gate the demo

Re-derived 2026-08-31 for the pivot. The WS numbers are the DECISION doc's
build plan (`docs/pivot/DECISION-dossier.md` §3).

- [ ] **(agent)** WS2 web face deployed — claim panel, agenda rail, divergence
      card, dossier list with Reject, doctrine view, approval queue. Every shot
      in the video renders in it. **Absent is fatal; adequate is acceptable.**
- [ ] **(agent)** WS3 belief engine — turn-level extraction (quote + `turn:t-N`
      anchor, fabricated-anchor stop intact) and the doctrine compiler with
      rule←claim provenance, property-tested for byte stability.
- [ ] **(agent)** WS1 initiation — Scheduler fix deployed, `initiate.py`
      appending honestly-labelled `session.proposed` events, outbound
      invitations flowing, and **real dogfooding sessions in the log** (elapsed
      time is the deliverable; it cannot be backfilled).
- [ ] **(agent)** WS4 contradiction-on-the-user live in the session view, with
      the retired mechanism named in DECISION §4 fully off the live path.
- [ ] **(agent)** WS5 doctrine diff + rewritten `scripts/adaptation_metric.py`
      (determinism replay + compliance battery, imports nothing from the
      package). Until the battery runs, both numbers are `not yet measured`.
- [ ] **(agent)** `fixtures/transcripts/` populated via cassette recording
      (`scripts/record_cassettes.py`, supervised — costs live Vertex calls).
      Currently empty; upstream of `make demo` and the metric.
- [ ] **(agent)** WS7 realignment — README, PRD narrative, and
      `docs/architecture.*` rewritten to the dossier framing; `dossier/` rename
      already landed (commit `9c05a46`, test suite green after the rename).

---

## K. Day-of submission walk (today)

1. **(user-only)** Open the live rules page; resolve every **[VERIFY-RULES]**
   tag above.
2. **(agent)** `PYTHONPATH=src .venv/bin/python -m pytest -q` green;
   `.venv/bin/python scripts/compliance.py --no-prd` green.
3. **(user-only)** Hosted URL in a private window; click through as a
   logged-out judge.
4. **(user-only)** Video link in a private window, watched to the end, timer
   ≤ 4:00.
5. **(user-only)** Repo URL in a private window — public, current.
6. **(user-only)** Blog and social URLs in a private window.
7. **(agent)** Grep every submission artifact for `TODO`, `TBD`, `XXX`, and
   `<` placeholders. The only permitted angle-bracket tokens are the
   deliberately-unfilled URL slots this checklist names.
8. **(agent)** Grep every submission artifact for numbers: each traces to
   `docs/metrics.json` with a run ID, or the artifact says `not yet measured`
   (Devpost fields excepted — there, unmeasured numbers are omitted entirely).
9. **(user-only)** Paste `devpost-description.md` field by field. Category:
   The Collaborative Partner. Built With includes `google-adk`.
10. **(user-only)** Submit, then reload the public submission page logged out
    and read it as a judge.
11. **(agent)** Append the submission to `docs/BUILD-LOG.md` with the URLs and
    record in `docs/FINDINGS.md` what was still unmeasured at submission time.

---

## What this checklist will not do for you

It will not tell you that a number is right. Every repo artifact writes
`not yet measured` where an unmeasured number belongs, because that is the
true state; Devpost fields omit unmeasured numbers instead of announcing them.
A value enters any surface only after it lands in `docs/metrics.json` with a
run ID and a date. The failure mode this directory is built against: a
plausible number typed into a submission field at 4 a.m. because the field
looked empty.
