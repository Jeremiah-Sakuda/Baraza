# BY-HAND.md — everything only you can do

**Today: Friday 2026-08-14. Deadline: Sunday 2026-08-31, 5:00 pm PT. 17 days.**

Everything in this file requires your credentials, your accounts, your face, or
real elapsed time. Nothing here can be done by an agent. Items are ordered by
when they stop being recoverable, not by size.

Current honest position, from the ten-agent judging panel:

| | Score |
|---|---|
| **Stage 1 gate today** | **FAIL** — no public repo URL, no Google Cloud service running |
| **Stage 2 today** | **2.5 / 6** |
| **Stage 2 projected**, human items done competently | **≈ 4.15** |
| **+ Stage 3 bonus** (blog + social) | **≈ 4.55 / 6** |
| **+ Gemma earned rather than dropped** | **≈ 4.75 / 6** |

The gap between 2.5 and 4.55 is entirely this file.

---

## 🔴 TODAY — non-recoverable if missed

### H1 · Push to a remote

The repo is committed locally (six commits, B0–B5, 120 files) but has **no
remote**. Everything exists on one disk.

Public is strictly safer than private. If you go private, you must grant **both**
addresses — granting only one is a common and fatal miss:

- `testing@devpost.com`
- `cloudhackathons@google.com`

```bash
gh repo create baraza --public --source=. --push
```

Then replace the literal `<repo-url>` placeholder in `README.md`.

A secret scan over the full history and working tree came back clean, so there
is nothing blocking a public push.

### H2 · GCP project — ✅ DONE

`baraza-2026` created and active. Nine APIs enabled: run, firestore, aiplatform,
cloudscheduler, artifactregistry, cloudbuild, iam, logging, cloudtrace.

Two things worth knowing about how this landed:

- **`hodi-2026` was inspected and rejected.** It turned out to hold six live
  Cloud Run services, ten service accounts, and five Firestore databases. The
  rules require the video to show the Cloud Run dashboard and the Scheduler
  execution history as proof of Google Cloud deployment, and in a shared project
  those two frames show another system's fleet alongside Baraza's. A dedicated
  project makes both frames unambiguous and lets teardown delete cleanly.
- **Billing linked to `My Billing Account` (`015D5D-94704F-956BF9`), not
  Deployment Billing.** Deployment Billing returned `Cloud billing quota
  exceeded` — it already carries five projects and Google caps how many a single
  account can fund. This is a hard platform limit, not a preference. To move it
  later, free a slot on Deployment Billing and re-link:

  ```bash
  gcloud billing projects link baraza-2026 --billing-account=015ACB-BA3DCD-D7BD7F
  ```

### H3 · Application Default Credentials

Still absent. This one is genuinely yours — it opens a browser and an agent
cannot complete an interactive OAuth flow.

```bash
gcloud auth application-default login
```

This is the single biggest blocker in the project. It gates cassette recording,
which gates five `make` targets, which gates every measured number.

### H4 · The $150 Google Cloud credit form

**Closes Aug 28, 12:00 pm PT.** Approval is not instant — the rules say up to 72
business hours. Apply now even if you think you won't need it.

<https://forms.gle/riGhgDSHkHeMx8Ca6>

### H5 · Bootstrap and deploy the BAR-021 stub Scheduler **tonight**

This is the one item no amount of later effort can recover. BAR-410 wants ≥10
nightly reconcile runs visible in the execution history by recording day, and
that history only accumulates in real time. Starting tonight yields ~13 nights.
Starting Aug 20 yields ~6. Nothing warns you when it expires.

```bash
export BARAZA_PROJECT_ID=<the project you pick in H2>
make bootstrap
```

Budget for several failures on the first run. `deploy/README.md` concedes
plainly that no `gcloud` command in that script has touched a live API and the
IAM permission strings are unverified.

### H6 · Set a billing budget alert while you are in the console

A judged URL that 404s in September because credits ran out is a self-inflicted
loss. Cloud Console → Billing → Budgets & alerts.

**Do not run `make teardown` before Oct 1** — the rules require the project to
stay free and testable until judging ends.

---

## 🟠 Aug 15–18

### H7 · Verify the model pins

```bash
make verify-models
```

Model IDs are pinned but have **never been resolved against live Vertex**. Until
this exits 0, no document in the repo may state which model version shipped —
that rule is enforced by `scripts/compliance.py`.

### H8 · Record the cassettes

Supervised, costs live Vertex calls. One command flips `demo`, `demo-agenda`,
`demo-interview`, `verify-anchors`, and the 17 behaviour probes from red to
green, then unlocks `adaptation-metric`.

```bash
python3 scripts/record_cassettes.py --yes && make demo
```

Run `make demo` immediately after — a single prompt drift produces a
`CassetteMiss`, which fails loudly by design rather than inventing a response.

### H9 · Confirm the gate

```bash
make gate
```

### H10 · Decide Gemma: earn it or drop it

Worth +0.2. The panel found the Gemma path is currently **unclaimable**: the
endpoint variable is read by nothing, and a total filter outage used to print
`kept 33/33 = 100.0% (gemma)` — byte-identical to the filter working perfectly.
That silent-failure mode is now fixed and reports `DEGRADED`, but the
endpoint-aware branch was deliberately left unwritten because it cannot be
verified without a live endpoint.

Either write and verify it, or delete the Gemma rows and forgo the 0.2. The
README and compliance matrix currently state that neither has happened.

---

## 🟡 Aug 19–25

### H11 · Supervised measurement session 1

Populate `docs/metrics.json` with real run IDs and dates. All 20 entries
currently read `"not yet measured"`.

Highest-value single number: **contradiction precision against the 18-landmine
manifest**. "18 of 18 plants found, 15 of 17 behaviours caught, and here are the
2 misses" beats every paragraph of prose in the repository.

### H12 · Supervised measurement session 2

Persona replay runs → `fixtures/transcripts/` → `make adaptation-metric` green.
This produces the BAR-330 number and the turn ID of the in-session adaptation
moment that the README and video script reference.

### H13 · Flip the reconcile Job to `--real`

`Dockerfile.job` defaults to `stub` and `scheduler.yaml` does not override it.
Needs **≥3 real nights before Aug 28** or the video's differential-ledger
section has nothing to show.

### H14 · The Aug 25 reproducibility gate

Clean clone on a **different machine**, then `make install && make demo`. You
cannot self-certify this from the box that built it. Note the Dockerfiles do not
install from `requirements.lock`, which was resolved on Python 3.14/macOS while
the images are 3.11-slim.

### H15 · PRD v1.1, if you can find it

You chose "I'll supply v1.1" but it never landed. `make compliance` exits 2
because `docs/PRD.md` is absent, and ~35 BAR requirement IDs have no acceptance
criteria in the tree. Low external priority — no judge runs `make compliance` —
but it is the repo's own contract.

If it is unrecoverable, change `make gate` so it stops reporting red for an
internal-only gap.

### H16 · Two decisions I declined to make for you

Both involve editing normative project documents, and three separate agents
independently refused to do it unilaterally:

1. `AGENTS.md` §7 and `baraza-prd-v1.2-amendments.md` (three places) still cite
   `docs/antigravity/decision.md`. That file was a placeholder for prior work
   from a sibling project that was never supplied. It carried a second-hand
   negative claim about a named vendor's SDK, which collides with the standing
   rule against unverifiable negative claims about real entities. Either supply
   the original, or cut the citation from BAR-020 and state plainly that ADK was
   chosen without a published comparison.
2. Whether to keep the sibling-project ports disclosed as they currently are in
   the README.

---

## 🟢 Aug 26–31

### H17 · Record the video

Script is at `docs/submission/video-script.md`, budgeted at 3:50 with 0:10 of
slack against the 4:00 hard cap. It needs preconditions met, not rewriting.

Three things the panel flagged specifically:

- **Shoot the centrepiece against live Vertex**, with the Cloud Console log
  stream in a second window — not against cassettes. The rules ask for
  *unedited live execution*.
- **Put the `extraction path: adk-agent` report line on screen** rather than
  asserting ADK in narration. Offline replay is direct-call by design, so
  nothing filmed from `make demo` is an agent loop — that is the sentence most
  likely to become an on-camera overclaim.
- Keep the three mandatory Google Cloud proof frames: Cloud Run dashboard,
  Vertex AI logs, Scheduler execution history.

Worth adding to the opening: the corpus is synthetic because publishing a real
student organization's chat export and budget would be the wrong thing to do.
That reframes it from a shortcut into a deliberate choice.

### H18 · Publish the blog — **+0.2**

`docs/submission/blog-post.md` is drafted and already contains the required
"created for the purposes of entering this hackathon" language. Must be public,
not unlisted.

### H19 · Post to social — **+0.2**

`docs/submission/social-posts.md`. Must carry `#AllThingsAgenticHackathon`
exactly.

### H20 · Submit to Devpost — **by Aug 30, not Aug 31**

Select **The Collaborative Partner**.

Before submitting, purge from `devpost-description.md`: every `<…>` placeholder,
and all six occurrences of `not yet measured`. Keep that discipline in the
README where it earns credit for honesty; a Devpost field announcing that its
own metrics don't exist reads as unfinished. Add `google-adk` to Built With.

Full checklist: `docs/submission/CHECKLIST.md`.

---

## What I could not do, and why

| Item | Reason |
|---|---|
| Deploy anything | Needed your project choice; you were interrupted before naming it |
| Record cassettes | ADC absent — interactive browser OAuth |
| Any measured number | Follows from the two above |
| Record the video | Your voice, your screen |
| Publish blog / social / Devpost | Your accounts |
| Merge PRD v1.2 | v1.1 was never supplied, and §6 forbids reconstructing it |
| Copy the Antigravity finding | Lives in a sibling project I was not given |
| ≥10 nights of Scheduler history | Real elapsed time; cannot be compressed |
