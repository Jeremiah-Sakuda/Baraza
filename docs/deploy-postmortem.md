# The sixteen-day 403 — a postmortem the repo owes its own method

**Resolved 2026-08-31.** Cloud Scheduler could not start the nightly reconcile
Job from 2026-08-15 to 2026-08-31: roughly a hundred `PERMISSION_DENIED`
attempts across eleven nights of scheduled fires plus every manual retry, with
every documented grant verified in place. This file records the true cause, the
wrong theory that survived two weeks, and why it survived — because the wrong
theory was recorded in `STOPPED-DEPLOY.md` at the time with full confidence,
and the correction deserves equal prominence.

## The true cause

`POST …/jobs/baraza-reconcile:run` with a `containerOverrides` body requires
**`run.jobs.runWithOverrides`** — a distinct permission from `run.jobs.run`,
and one `roles/run.invoker` does not include. Every real trigger carried the
override, because the override (`BARAZA_RUN_TRIGGER=cloud-scheduler`) is
exactly what makes a run honestly labelled `scheduled`. Every attempt was
therefore denied on a permission whose name never appeared in any log Scheduler
exposes — only `URL_ERROR-ERROR_OTHER. Original HTTP response code number = 403`.

## The wrong theory, and why it held

The investigation's control experiment — mint a token as the same service
account, POST the same URL — succeeded, and was taken as proof that the SA's
permissions were sufficient, which shifted suspicion onto Scheduler's token
minting. But the diagnostic had posted an **empty body**. Control and
experiment differed in the one byte that mattered: `{}` exercises
`run.jobs.run`; the real body exercises `run.jobs.runWithOverrides`. Every
subsequent elimination step inherited the flaw. An audit-log absence that
seemed to confirm the token theory was a logging-visibility artifact.

The lesson, in this repo's own vocabulary: **a verification that does not
reproduce the failing input byte-for-byte verifies a different claim.** The
same discipline that demands quotes be verbatim applies to diagnostics.

## The fix, deployed and verified live

1. **Custom role `baraza_job_trigger`** — exactly `run.jobs.run` +
   `run.jobs.runWithOverrides` — bound on the Job, to `baraza-reconcile`, and
   to nothing else. Reproduced by `scripts/bootstrap_gcp.sh`.
2. **The `baraza-trigger` hop** (Scheduler → OIDC → Cloud Run service →
   Jobs API), retained on its merits: the service hard-codes the
   `cloud-scheduler` label server-side, so no Scheduler-config edit can spoof
   a scheduled run, and OIDC-to-service failures produce readable logs — which
   is what finally broke the case.

Verified end to end 2026-08-31:

```
Scheduler fire → OIDC → baraza-trigger (200) → jobs.run(+overrides)
→ execution baraza-reconcile-56bqt → container exit 0
→ Firestore: heartbeat        scheduled=True  trigger=cloud-scheduler
             session.proposed scheduled=True  trigger=cloud-scheduler
```

Also fixed in the same sweep, each found only by running the deployed system:
the trigger service's 256Mi memory floor (gen2 requires 512Mi); corpus and
output paths resolving into site-packages in the container
(`REPO = Path(__file__).parents[2]` is a checkout assumption); and ADK's
GenAI client needing `GOOGLE_GENAI_USE_VERTEXAI`/`GOOGLE_CLOUD_PROJECT`/
`GOOGLE_CLOUD_LOCATION`, which nothing set because direct calls pass those
explicitly. Four defects, zero visible from reading the code.

`scheduler_nightly_runs_completed` in `docs/metrics.json` stays honest: it
counts only Scheduler-triggered runs, which accrue from tonight's 03:17 UTC
fire onward. Nothing before 2026-08-31 counts, because nothing before then ran.
