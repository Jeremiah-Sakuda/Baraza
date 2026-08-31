# STOPPED-DEPLOY.md — Cloud Scheduler cannot invoke the reconcile Job

**Date:** 2026-08-15 · **Project:** `baraza-2026` · **Lane:** 2 (deploy), non-blocking

Per PRD §2.5.3, a deploy failure logs here and the run continues local-only. It
does not stop the build. It does stop one specific acceptance criterion, and
that is stated below rather than worked around.

---

## What works

Everything except the trigger. Verified by running it, not by reading it.

| Component | State | Evidence |
|---|---|---|
| Project, billing, 11 APIs | live | `gcloud projects describe baraza-2026` |
| Firestore native DB | live | created 2026-08-15T21:56Z |
| **Append-only rules** | **deployed and verified** | `scripts/verify_append_only.sh` → passed 3, skipped 2, failed 0 |
| Artifact Registry + 2 images | pushed | `baraza/job`, `baraza/service` |
| 4 service accounts | created | least-privilege, per `deploy/README.md` |
| 2 custom IAM roles | created | appender holds neither `.update` nor `.delete` |
| Cloud Run Jobs (×2) | deployed | `baraza-reconcile`, `baraza-ingest` |
| Cloud Run services (×2) | deployed | interview (private), successor (public) |
| Successor URL, logged out | **HTTP 200** | `https://baraza-successor-tlaymplktq-uc.a.run.app` |
| **The Job itself runs** | **exit 0, twice** | `baraza-reconcile-ffglp`, `baraza-reconcile-l46fn` |
| **The heartbeat reaches Firestore** | **confirmed** | 1 event, `event_type=heartbeat`, `actor=reconcile-job` |
| Cloud Scheduler job | ENABLED, `17 3 * * *` UTC | exists and fires on schedule |

The full path — Cloud Run Job → append-only Firestore write → heartbeat event —
is proven end to end. Only the *trigger* is broken.

---

## The failing gate

```
gcloud scheduler jobs run baraza-reconcile-nightly --location=us-central1
  → status.code: 7 (PERMISSION_DENIED)

Cloud Scheduler log:
  status:    PERMISSION_DENIED
  url:       https://run.googleapis.com/v2/projects/baraza-2026/locations/
             us-central1/jobs/baraza-reconcile:run
  debugInfo: URL_ERROR-ERROR_OTHER. Original HTTP response code number = 403
```

## What has been ruled out

Each of these was checked against the live project, not assumed.

1. **The SA lacks the permission** — ruled out. `roles/run.invoker` is bound on
   the Job resource, and that role's `includedPermissions` contains
   `run.jobs.run` (verified via `gcloud iam roles describe`).

2. **The SA genuinely cannot run the Job** — ruled out *empirically*. Minting a
   token as `baraza-reconcile` and POSTing the identical URL succeeded:

   ```
   SUCCESS — execution started:
     projects/baraza-2026/.../executions/baraza-reconcile-l46fn
   ```

   The service account can do the thing Cloud Scheduler is failing to do, using
   the same endpoint and the same identity.

3. **The Cloud Scheduler service agent is missing** — ruled out. It exists with
   `roles/cloudscheduler.serviceAgent`.

4. **The Scheduler agent cannot impersonate the SA** — granted and still failing.
   `service-1031838711515@gcp-sa-cloudscheduler.iam.gserviceaccount.com` now
   holds `roles/iam.serviceAccountTokenCreator` on `baraza-reconcile`.

5. **The invocation body is wrong** — ruled out. The Scheduler body already
   carries the correct container override:

   ```json
   {"overrides":{"containerOverrides":[{"env":[
     {"name":"BARAZA_RUN_TRIGGER","value":"cloud-scheduler"}]}]}}
   ```

6. **The caller lacks actAs on the runtime identity** — granted
   (`baraza-reconcile` now holds `roles/iam.serviceAccountUser` on itself, since
   it triggers a Job that runs as itself) and still failing.

## Why this stops here

Two IAM grants have already been made chasing this. A third would be
indistinguishable from "widen the permission until the error goes away," which
AGENTS.md names as a prohibited failure mode and PRD §2.5.2 makes a stop
condition. The remaining candidates all involve broadening `run.invoker` from
the Job resource to the project, and that would trade the least-privilege
property the project actually advertises for one green checkmark.

**Nothing was widened. The two grants made are both minimal and both correct for
the documented pattern**, regardless of whether they turn out to be the fix:
Scheduler must be able to mint a token as the SA, and a caller must hold `actAs`
on the identity a Job runs as.

## What this costs

**BAR-410's acceptance criterion — ≥10 nightly reconcile runs in the execution
history before recording day — is at risk and the clock is running.**

The Scheduler is ENABLED and will attempt at 03:17 UTC nightly. Two possibilities:

- The grants made today needed propagation longer than the ~10 minutes of
  retries allowed, and tonight's scheduled attempt succeeds on its own. **Check
  first thing tomorrow** — this costs nothing and may already be resolved.
- It still fails, in which case the next step is below.

Every night lost is one that cannot be recovered later.

## Next step for a human

```bash
# 1. Did tonight's 03:17 UTC run succeed?
gcloud run jobs executions list --job=baraza-reconcile \
  --region=us-central1 --project=baraza-2026

gcloud scheduler jobs describe baraza-reconcile-nightly \
  --location=us-central1 --project=baraza-2026 --format='value(status.code)'
#    empty  = success
#    7      = still PERMISSION_DENIED
```

If still failing, the decision is yours to make explicitly rather than mine to
make silently — grant `roles/run.invoker` to `baraza-reconcile` at the **project**
level:

```bash
gcloud projects add-iam-policy-binding baraza-2026 \
  --member='serviceAccount:baraza-reconcile@baraza-2026.iam.gserviceaccount.com' \
  --role='roles/run.invoker'
```

That is broader than the repo currently claims. If you take it, `deploy/README.md`'s
IAM matrix must be updated to match, because the project's rule is that the
matrix never describes a tighter posture than the one deployed.

## Also outstanding on this deployment

The deployed `baraza/job` image predates commit `0fca155` and still hardcodes
`scheduled=True` on every append. Until it is rebuilt, a manual run is recorded
as a scheduled one — the exact defect that commit fixes. Rebuild before any
nightly-run count is quoted anywhere:

```bash
BARAZA_PROJECT_ID=baraza-2026 make bootstrap   # idempotent; rebuilds and replaces
```

The single heartbeat currently in Firestore was written by a **manual** run under
the old image and is labelled `scheduled=True`. It is wrong, and the log is
append-only, so it cannot be edited. Either accept a nightly count that is one
too high and say so, or delete the `events` collection now while it holds exactly
one test artifact and no real history.

---

## Update 2026-08-31 — root cause narrowed, fix identified

Three further hypotheses tested against the live project:

1. **Project-level `roles/run.invoker`** — granted, still 403, **reverted**. The
   earlier decision to stop rather than widen is vindicated: widening bought
   nothing.
2. **Stale Scheduler auth config** — the job was deleted and recreated with
   identical config after all grants were in place. Still 403.
3. **The audit log** — the discriminating result. Admin-activity audit logs show
   **no request authenticated as `baraza-reconcile` ever reaching the Run API**
   from Scheduler. The SA's own token calls the identical URL successfully. The
   failure is therefore in Scheduler's OAuth token path for this SA, not in any
   IAM binding on the Job — every documented grant is present and verified.

**Recommended fix (architecture, not permissions):** stop having Scheduler call
the Run Admin API directly. Add a trigger endpoint to the interview service
(`POST /internal/run-reconcile`, OIDC-guarded, invoker = the scheduler SA) that
calls `jobs.run` itself using its runtime identity. Scheduler→OIDC→Cloud Run
*service* is the well-trodden path; the service's own credentials already work
against the Jobs API (proven by the impersonation test). No scope is widened —
the same SA does the same thing, one hop later.
