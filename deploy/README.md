# deploy/ — the deploy lane

BAR-021 (early scheduler), BAR-410 (deploy), BAR-411 (hosted surface).

One command provisions everything:

```bash
BARAZA_PROJECT_ID=your-project make bootstrap
```

One command removes it:

```bash
BARAZA_PROJECT_ID=your-project make teardown CONFIRM=--yes-destroy
```

> **Verification status, stated before anything else.** Everything in this
> directory has been syntax-checked, parsed, rendered, and — for the two
> services and the run-ID arithmetic — executed locally against a synthetic
> event log. **No `gcloud` command in `bootstrap_gcp.sh` has been run against a
> live project by the session that wrote it.** What that means in practice:
> flag names, API shapes, and IAM permission strings are written from the
> documented interfaces and are unverified. The first real run is the
> verification, and it will either complete or stop with a named error in
> `STOPPED-DEPLOY.md`. Nothing in this file claims a deployed measurement.

---

## What each piece is

| Path | What it is |
|---|---|
| `firestore.rules` | Append-only at the database level. `create` only; `update` and `delete` denied on every path, including paths that do not exist yet. |
| `Dockerfile.job` | Cloud Run Job image — the nightly reconciler and the ingestion Job. Python 3.11-slim, non-root (UID 10001), no credentials. |
| `Dockerfile.service` | Cloud Run service image — one image, both FastAPI apps, selected by `BARAZA_APP`. |
| `entrypoint-job.sh` | Composes the `--run-id` the reconcile Job needs. See *The run ID* below; this is the least obvious file here. |
| `entrypoint-service.sh` | Starts uvicorn on `$PORT`. |
| `cloudbuild.yaml` | Builds both images from one submission of one context, so they cannot drift apart. |
| `scheduler.yaml` | The nightly trigger. Source of truth for cadence — `bootstrap_gcp.sh` parses it rather than keeping a second copy. |
| `service-interview.yaml` | Cloud Run service, `minScale: 0`, **not** publicly invokable. |
| `service-successor.yaml` | Cloud Run service, `minScale: 0`, the one public surface. |
| `../scripts/bootstrap_gcp.sh` | `make bootstrap`. Idempotent. Stops rather than widening. |
| `../scripts/teardown.sh` | `make teardown`. Idempotent. Requires `--yes-destroy`. |
| `../scripts/verify_append_only.sh` | Proves the append-only guarantee against a live project. Reports skipped checks as skipped. |
| `../src/baraza/interview/service.py` | The interview surface. Reads as `Audience.OWNER`. |
| `../src/baraza/dossier/service.py` | The public surface. Reads as `Audience.PUBLIC`. |
| `../src/baraza/telemetry.py` | OpenTelemetry wiring. Spans carry `claim.digest()`, never the quote. |

---

## What gets created

| Resource | Name |
|---|---|
| Firestore | `(default)`, native mode |
| Firestore rules release | `cloud.firestore` → a ruleset built from `firestore.rules` |
| Artifact Registry | `baraza` (docker, regional) |
| Cloud Run Job | `baraza-reconcile` — nightly, stub mode until BAR-321 |
| Cloud Run Job | `baraza-ingest` |
| Cloud Run service | `baraza-interview` — authenticated only |
| Cloud Run service | `baraza-successor` — `allUsers` invoker; the hosted demo URL |
| Cloud Scheduler | `baraza-reconcile-nightly` — 03:17 UTC daily |
| Service accounts | `baraza-ingest`, `baraza-reconcile`, `baraza-interview`, `baraza-successor` |
| Custom IAM roles | `baraza_log_appender`, `baraza_log_reader`, `baraza_job_trigger` |

---

## The IAM matrix

Read the **Enforced by** column carefully. It is the honest part.

| Capability | ingest | reconcile | interview | successor | Enforced by |
|---|---|---|---|---|---|
| Create an event (`datastore.entities.create`) | yes | yes | yes | **no** | **IAM** — `baraza_log_appender` vs `baraza_log_reader` |
| Start a Job execution **with the scheduled override** (`run.jobs.runWithOverrides`) | no | **yes** (via `baraza_job_trigger`, bound on the Job only) | no | no | **IAM** — the permission whose absence was the sixteen-day Scheduler 403; `roles/run.invoker` does not include it |
| Read events (`get`, `list`) | yes | yes | yes | yes | IAM |
| **Update an event** | **no** | **no** | **no** | **no** | **IAM** — the permission is in neither custom role |
| **Delete an event** | **no** | **no** | **no** | **no** | **IAM** — the permission is in neither custom role |
| Write `claim.asserted` | yes | yes | yes | no | code — extractors construct only this event type |
| Write `contradiction.*`, `heartbeat` | no | yes | no | no | code — only `reconcile/job.py` constructs them |
| Write `claim.committed`, `claim.visibility_set` | **no** | **no** | **yes** | **no** | **code + rules, NOT IAM** — see below |
| Call Vertex (`aiplatform.user`) | yes | yes | yes | yes | IAM |
| Trigger the reconcile Job (`run.invoker`) | no | yes (that Job only) | no | no | IAM, resource-scoped |
| Be invoked by an unauthenticated request | n/a | n/a | **no** | **yes** | IAM — `allUsers` bound on the successor service only |
| Read a `private` claim's quote | no | no | yes (`OWNER`) | no | code — `Claim.quote_for(audience)`; the field is unreachable otherwise |

### The row IAM cannot enforce, said plainly

**IAM cannot express "this principal may create documents whose `event_type`
field is `claim.asserted`."** Firestore's IAM permissions are per-operation
(create / get / list / update / delete) and per-database. They carry no predicate
over document contents.

So there are not four custom roles here. There are two, because four roles with
identical permission sets and four different names would be an IAM matrix that
*reads* like enforcement and enforces nothing — which is worse than the honest
version, since it is the version a reviewer would believe.

What actually holds the `claim.committed` boundary:

1. **Code path.** `claim.committed` and `claim.visibility_set` are constructed
   in exactly one module, `interview/approval.py`, and only the interview
   service's request handlers call it. Stated precisely, because the looser
   version was in this file and was wrong: the **reconcile** Job does not import
   `approval` at all (`import baraza.reconcile.job` leaves it out of
   `sys.modules`), but the **ingest** Job does — `entrypoint-job.sh` runs
   `python -m baraza.cli demo-agenda`, and `baraza.cli` imports the module. On the
   ingest container the isolation is therefore *which code path runs*, not *what is
   loaded*. What backs it: `BarazaAgents.assert_promotion_isolated()` runs at
   extractor construction on every deployed ingest run — not only under pytest —
   and refuses any tool defined in a module that so much as references the
   promotion event type. A unit test asserts the extractor cannot produce a
   committed claim.
2. **`firestore.rules`.** `isApprovalOnlyEvent()` denies those two event types
   on the `create` rule. This binds every rules-governed caller — browsers,
   leaked web configs, any surface someone later builds with a client SDK. It
   does **not** bind the service accounts, because rules are bypassed by
   service-account credentials.
3. **IAM, for everything else.** The append-only guarantee itself — no update,
   no delete, ever, by anyone — *is* IAM-enforced, and that is the guarantee
   that matters most.

### Two layers, two audiences

| | Governs | Does not govern |
|---|---|---|
| **IAM** | The four service accounts. The Jobs and services. | Browsers and API-key clients. |
| **Firestore rules** | Client SDKs, Firebase Auth, API-key REST traffic. | Anything holding service-account credentials — rules are bypassed. |

Neither layer is claimed to be the other. `scripts/verify_append_only.sh` tests
them separately and reports which check ran.

---

## Verifying that the append-only rule actually rejects an update

```bash
BARAZA_PROJECT_ID=your-project scripts/verify_append_only.sh
```

Four checks. Checks 1 and 2 always run. Checks 3 and 4 need one extra thing each
and are reported as **SKIP** — never folded into a pass — when they cannot run.

### Check 1 — the deployed rules are the file in this repository

Fetches the live `cloud.firestore` release, pulls its ruleset source, and diffs
it against `deploy/firestore.rules`. A rules file that is committed but not
deployed protects nothing.

### Check 2 — the roles hold no update or delete permission

```bash
gcloud iam roles describe baraza_log_appender --project="$BARAZA_PROJECT_ID" \
  --format='value(includedPermissions)'
```

Expected: `datastore.databases.get`, `datastore.entities.create`,
`datastore.entities.get`, `datastore.entities.list`, `datastore.indexes.list` —
and **no** `datastore.entities.update`, **no** `datastore.entities.delete`.

### Check 3 — the curl (this is the one to run)

Firestore's REST API needs either an OAuth token or a Firebase Web API key.
**Do not use your own OAuth token here.** An owner's token bypasses both layers;
the request would very likely succeed and would prove the opposite of what it
looks like it proves. Use a Firebase Web API key, which is exactly what a
browser would hold:

```bash
PROJECT=your-project
KEY=AIza...                                   # Firebase console -> Project settings -> Web app
DOC=evt_00000000000000000000000000000000      # or a real event ID from the log

# Attempt to UPDATE an event. Expected: HTTP 403.
curl -i -X PATCH \
  "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/documents/events/${DOC}?key=${KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"fields":{"actor":{"stringValue":"tamper"}}}'

# Attempt to DELETE an event. Expected: HTTP 403.
curl -i -X DELETE \
  "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/documents/events/${DOC}?key=${KEY}"
```

Expected response for both:

```
HTTP/2 403
{ "error": { "status": "PERMISSION_DENIED",
             "message": "Missing or insufficient permissions." } }
```

Rules are evaluated before document existence, so a synthetic `DOC` exercises
the same `allow update: if false` branch as a real one. To use a real event ID:

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
  "https://firestore.googleapis.com/v1/projects/${PROJECT}/databases/(default)/documents/events?pageSize=1" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["documents"][0]["name"].rsplit("/",1)[-1])'
```

### Check 4 — the read-only service account cannot write

Impersonates `baraza-successor` and attempts the same PATCH; expects 403 from
IAM. It needs `roles/iam.serviceAccountTokenCreator`, which **bootstrap
deliberately does not grant** — a permission handed out so a test can pass is a
permission the test then stops testing. Grant it yourself if you want the check,
and revoke it afterwards.

---

## The run ID

The single least obvious design decision in this directory, so it is written
down rather than left in a commit message.

Cloud Scheduler **cannot** inject a per-run timestamp into a Cloud Run Job. Its
HTTP target is the Run Admin API; the `X-CloudScheduler-ScheduleTime` header it
sends is consumed there and never reaches the container.

A literal `--run-id` in the Scheduler request body would therefore be identical
every night. Event IDs are content hashes, so night two's heartbeat would
collide with night one's, be dropped as a duplicate, and the heartbeat count
would sit at **1** while the Scheduler execution history kept growing. Two
numbers that look like they measure the same thing, disagreeing, with the
smaller one being the true one — precisely the failure mode BAR-021 exists to
avoid.

So `entrypoint-job.sh` composes it:

```
nightly-<epoch millis of 00:00:00Z on the current UTC day>
```

- **Day granularity, not wall clock.** `_heartbeat_instant()` derives the
  heartbeat instant *from the run ID* specifically so a retried execution
  appends the same heartbeat rather than a second one. The nightly count stays a
  count of nights instead of a count of attempts.
- **13 digits.** `_heartbeat_instant()` searches for a 13-digit millis component
  before falling back to 10-digit seconds.
- **03:17 UTC.** Far enough from midnight that a retry window cannot straddle a
  UTC date boundary and mint a second ID for the same night. Off the hour
  because the top of the hour is when every cron on the platform fires.

The Scheduler body carries `BARAZA_RUN_TRIGGER=cloud-scheduler` as a container
override, so a scheduled run is labelled as scheduled in the container's own
logs as well as in Scheduler's. **A scheduled run is never counted as organic
activity**, and `EventStore.count_scheduled()` exists so any figure derived from
it is obviously a count of scheduled runs.

---

## The stub-to-real changeover

BAR-021's stub and BAR-321's real reconciler are the same Cloud Run Job, updated
in place:

```bash
gcloud run jobs update baraza-reconcile \
  --region="$BARAZA_REGION" --project="$BARAZA_PROJECT_ID" \
  --update-env-vars=BARAZA_RECONCILE_MODE=real
```

A new Job name would restart the execution history at zero and discard the
evidence the early deploy exists to accumulate. Same name means the history is
continuous and the changeover date is identifiable in it, which is what
BAR-410's AC asks for.

Counting the nights:

```bash
gcloud run jobs executions list --job=baraza-reconcile \
  --region="$BARAZA_REGION" --project="$BARAZA_PROJECT_ID"
```

Every one of those is a scheduled run. None of them is organic activity.

---

## Reaching the services

**Successor (public).** The hosted URL a judge visits. Open it logged out.

```bash
gcloud run services describe baraza-successor --region="$BARAZA_REGION" \
  --project="$BARAZA_PROJECT_ID" --format='value(status.url)'
```

On a fresh project **this page shows nothing**, and that is the boundary
working, not a broken deploy. Every claim is created `private`; a claim appears
here only when an approver both committed it *and* chose to publish it — two
decisions, recorded as two events. The page says so in as many words rather than
being padded with sample content, because the one surface a judge actually
visits is the worst possible place to put something that is not true.

Where committed records exist that a logged-out visitor may not read, the page
reports **how many**. The count is honest; the contents are not disclosed.

**Interview (not public).** No `allUsers` binding. It renders private testimony,
which is the entire point of the visibility boundary.

```bash
gcloud run services proxy baraza-interview --region="$BARAZA_REGION" \
  --project="$BARAZA_PROJECT_ID"
```

---

## Cost shape through Oct 1

**No dollar figure appears here or in the bootstrap output, and the omission is
deliberate.** A monthly estimate typed into a script is a plausible number where
a measured one belongs. What can be stated without measuring is the shape:

| Component | Shape |
|---|---|
| Cloud Run services | `minScale: 0`. Billed per request-second. Idle cost is **zero**, not "low". |
| Cloud Run Jobs | Billed only while executing. The nightly stub run is seconds of one vCPU. |
| Cloud Scheduler | One job. The published free tier covers three per billing account per month. |
| Firestore | One small collection; hackathon-scale. Sustained public reads are the only thing that could move this. |
| Artifact Registry | Two images per build, plus a `latest` tag. **The line item that grows** if bootstrap is run many times — `teardown.sh --include-images` clears it. |
| Vertex AI | Per token, only when called. The dominant variable, and the only one a public endpoint can drive up. |
| Logging / Trace | Inside the free tier at this volume. |

The actual spend is **not yet measured**. Measure it; do not estimate it:

```bash
gcloud billing accounts list
# then: console -> Billing -> Reports, filtered to your project
```

With `minScale: 0` and a nightly stub job, standing cost is dominated by whether
anything is still calling Vertex — which nothing does unless a visitor asks the
successor surface a question.

---

## Known gaps in this lane

Recorded here so they are found by reading rather than by being surprised.

1. **`gcloud` paths are unverified.** See the note at the top. `bash -n` passes
   on every script; the YAML parses; the scheduler-config parser was tested
   against the real `scheduler.yaml`; the run-ID arithmetic was tested against
   `_heartbeat_instant`. None of that is the same as a successful `gcloud` call.

2. **The ingest Job invokes a command named for a demo.** `baraza.cli` has
   landed, and its cold-ingest command is `demo-agenda` — corpus in, claims
   extracted with on-write detection, ledger and agenda out. That is what the
   Job runs. The `demo-` prefix is a naming wart from the Makefile's contract
   targets and is recorded here rather than hidden behind an alias, which would
   give one code path two names.

   Corrected 2026-08-13 (B3): this entrypoint previously ran
   `baraza.cli ingest --manifest fixtures/MANIFEST.md`. There is no `ingest`
   subcommand and no `--manifest` flag, and `fixtures/MANIFEST.md` is the
   landmine manifest, not the corpus index — three separate mismatches between
   the deploy lane and the ingestion lane. The old guard only checked
   `import baraza.cli`, so it passed and argparse then exited **2** with a usage
   string. The guard now probes the subcommand itself and exits **78** with an
   explanation if it is absent. Still unverified: no `gcloud` call has run this.

3. **The interview agenda is cached per instance.** Item IDs and the
   contradictions behind them are recovered from the folded ledger on a cache
   miss, but a question's *wording* is a model output and can differ after a cold
   start or an instance switch mid-interview. Fixing it needs an agenda payload
   on the `session.opened` event, which is a schema change owned by the interview
   lane. Until then the honest description is: stable within an instance,
   re-derived across instances.

4. **Firestore rules do not bind the service accounts.** Stated three times in
   this file because it is the thing most likely to be misread as a stronger
   guarantee than it is. IAM is what stops the Jobs from deleting events. Rules
   are what stop everyone else.

5. **No metric in `docs/metrics.json` has been filled in by this lane.**
   `initiated_sessions_scheduled_count` (each Scheduler-fired run appends its
   `session.proposed` event labelled `scheduled` — never counted as organic
   activity) and
   `scheduler_stub_to_real_replacement_date` stay `"not yet measured"` until
   there is an execution history to count. The command that counts it is above.
