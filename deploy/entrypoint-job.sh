#!/usr/bin/env bash
#
# Cloud Run Job container entrypoint.
#
# WHY this exists rather than a bare `python -m baraza.reconcile.job`:
#
# Cloud Scheduler cannot inject a per-run timestamp into a Cloud Run Job. Its
# HTTP target is the Run Admin API, and the `X-CloudScheduler-ScheduleTime`
# header it sends is consumed by that API — it never reaches this container. A
# `--run-id` written literally into the Scheduler request body would therefore
# be byte-identical every night. Event IDs are content hashes, so the second
# night's heartbeat would collide with the first and be dropped as a duplicate,
# and the nightly-run count would sit at 1 forever while the Scheduler execution
# history kept growing. That is the exact shape of a number that looks real and
# is not, so the run ID is composed here instead.
#
#   nightly-<epoch millis of 00:00:00Z on the current UTC day>
#
# Day granularity, not wall clock, and that is the whole point.
# `baraza.reconcile.job._heartbeat_instant` derives the heartbeat instant from
# the run ID specifically so a retried execution appends the *same* heartbeat
# rather than a second one — the nightly count stays a count of nights instead
# of a count of attempts. Wall-clock millis would break that property. The UTC
# day keeps retries idempotent while still yielding exactly one heartbeat per
# night, which is why the Scheduler fires at 03:17Z: a retry window that far
# from midnight cannot straddle a UTC date boundary and mint a second ID.
#
# 13 digits is not incidental either — `_heartbeat_instant` searches the run ID
# for a 13-digit millis component before falling back to a 10-digit seconds one.
set -euo pipefail

readonly JOB="${BARAZA_JOB:-reconcile}"
readonly TRIGGER="${BARAZA_RUN_TRIGGER:-manual}"

epoch_day_ms=$(( ( $(date -u +%s) / 86400 ) * 86400 * 1000 ))
readonly RUN_ID="${BARAZA_RUN_ID:-nightly-${epoch_day_ms}}"

echo "baraza job     : ${JOB}"
echo "baraza run-id  : ${RUN_ID}"
echo "baraza trigger : ${TRIGGER}"
if [[ "${TRIGGER}" == "cloud-scheduler" ]]; then
  # BAR-021: a scheduled run is labelled as scheduled in every accounting it
  # touches. It is never counted as organic activity, here or downstream.
  echo "baraza note    : scheduled run — not organic activity"
fi

case "${JOB}" in
  reconcile)
    mode="${BARAZA_RECONCILE_MODE:-stub}"
    # Refused rather than defaulted. An unrecognized mode silently falling back
    # to `stub` would let a project believe the real reconciler had been running
    # for a week when it had not.
    if [[ "${mode}" != "stub" && "${mode}" != "real" ]]; then
      echo "BARAZA_RECONCILE_MODE must be 'stub' or 'real', got '${mode}'" >&2
      exit 64
    fi
    exec python -m baraza.reconcile.job "--${mode}" --run-id "${RUN_ID}" --json
    ;;

  ingest)
    # The ingest entrypoint lives in `baraza.cli`, which is owned by the
    # ingestion lane. `demo-agenda` is that lane's cold-ingest command: corpus
    # in, claims extracted with on-write detection, ledger and agenda out. The
    # "demo-" prefix is a naming wart, recorded in deploy/README.md rather than
    # papered over with an alias that would make two names for one code path.
    #
    # The guard checks the *subcommand*, not just that the module imports.
    # Importing was the original check and it was not enough: an earlier
    # revision of this file invoked a `baraza.cli ingest` subcommand that was
    # never built, so the import guard passed and argparse then exited 2 —
    # a Job failing with a usage string instead of the reported gap the guard
    # exists to produce.
    if ! python -m baraza.cli demo-agenda --help >/dev/null 2>&1; then
      echo "baraza.cli has no usable demo-agenda command in this image; the" >&2
      echo "ingest entrypoint has not landed yet. The Job is provisioned but" >&2
      echo "cannot run. This is a reported gap, not a silent success." >&2
      exit 78
    fi
    exec python -m baraza.cli demo-agenda --no-offline \
      --corpus "${BARAZA_CORPUS:-fixtures/corpus/corpus-index.json}"
    ;;

  *)
    echo "unknown BARAZA_JOB '${JOB}' (expected 'reconcile' or 'ingest')" >&2
    exit 64
    ;;
esac
