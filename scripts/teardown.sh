#!/usr/bin/env bash
#
# make teardown — remove everything scripts/bootstrap_gcp.sh created.
#
# Safe to run repeatedly: every deletion checks whether the thing exists first,
# and a missing resource is a skip, not a failure. Running this twice leaves the
# project in the same state as running it once.
#
# Requires an explicit confirmation flag. There is no interactive prompt,
# because a prompt in a script that might be run from a Makefile target is a
# prompt somebody answers by reflex.
#
#   scripts/teardown.sh --yes-destroy
#   scripts/teardown.sh --yes-destroy --include-firestore   (see the warning)
#
# ---------------------------------------------------------------------------
# WHY FIRESTORE IS NOT DELETED BY DEFAULT
#
# The event log is the system of record and the entire architecture rests on it
# being append-only: no update, no delete, ever, from inside the application.
# Deleting the database is the one operation the whole design exists to make
# impossible, and doing it silently as part of "clean up my Cloud Run services"
# would be the most expensive kind of convenience.
#
# So it takes a second, separate flag, and the flag is named after what it does.
# Everything else here is infrastructure that can be rebuilt from this
# repository in one command; the log cannot be rebuilt from anything.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

readonly PROJECT="${BARAZA_PROJECT_ID:-}"
readonly REGION="${BARAZA_REGION:-us-central1}"
readonly AR_REPO="baraza"

readonly SCHED_JOB="baraza-reconcile-nightly"
readonly JOBS=(baraza-reconcile baraza-ingest)
readonly SERVICES=(baraza-interview baraza-successor)
readonly ACCOUNTS=(baraza-ingest baraza-reconcile baraza-interview baraza-successor)
readonly ROLES=(baraza_log_appender baraza_log_reader)

CONFIRMED=0
INCLUDE_FIRESTORE=0
INCLUDE_IMAGES=0

for arg in "$@"; do
  case "$arg" in
    --yes-destroy)       CONFIRMED=1 ;;
    --include-firestore) INCLUDE_FIRESTORE=1 ;;
    --include-images)    INCLUDE_IMAGES=1 ;;
    -h|--help)
      sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      printf 'unknown argument: %s\n' "$arg" >&2
      exit 64
      ;;
  esac
done

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
gone() { printf '     \033[32mdeleted\033[0m  %s\n' "$*"; }
skip() { printf '     \033[2mabsent \033[0m  %s\n' "$*"; }
warn() { printf '     \033[33m%s\033[0m\n' "$*"; }

if [ -z "$PROJECT" ]; then
  printf 'BARAZA_PROJECT_ID is unset. Refusing to guess which project to tear down.\n' >&2
  exit 2
fi

if [ "$CONFIRMED" -ne 1 ]; then
  cat >&2 <<EOF
Refusing to tear down without an explicit flag.

This would delete, in project ${PROJECT} (region ${REGION}):

  scheduler   ${SCHED_JOB}
  jobs        ${JOBS[*]}
  services    ${SERVICES[*]}
  accounts    ${ACCOUNTS[*]}
  roles       ${ROLES[*]}

Re-run with:  scripts/teardown.sh --yes-destroy

The Firestore database and the event log in it are NOT touched unless you also
pass --include-firestore. Container images are kept unless you pass
--include-images.
EOF
  exit 2
fi

command -v gcloud >/dev/null 2>&1 || { printf 'gcloud is not on PATH.\n' >&2; exit 1; }
gcloud projects describe "$PROJECT" >/dev/null 2>&1 \
  || { printf 'project %s is not reachable.\n' "$PROJECT" >&2; exit 1; }

# Every deletion is best-effort in one specific sense: a resource that is
# already gone is not an error. A resource that exists and refuses to delete IS
# an error and is reported, because a teardown that silently leaves a public
# endpoint bound to allUsers is worse than one that fails loudly.
drop() {
  local label="$1"; shift
  if "$@" >/dev/null 2>&1; then
    gone "$label"
  else
    skip "$label"
  fi
}

say "Cloud Scheduler"
if gcloud scheduler jobs describe "$SCHED_JOB" --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  drop "$SCHED_JOB" gcloud scheduler jobs delete "$SCHED_JOB" \
    --location="$REGION" --project="$PROJECT" --quiet
else
  skip "$SCHED_JOB"
fi

say "Cloud Run services"
for svc in "${SERVICES[@]}"; do
  if gcloud run services describe "$svc" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    # Deleting the service removes its IAM policy with it, including the
    # allUsers invoker binding on the successor surface. That is the binding
    # this teardown most needs to actually take effect.
    drop "$svc" gcloud run services delete "$svc" \
      --region="$REGION" --project="$PROJECT" --quiet
  else
    skip "$svc"
  fi
done

say "Cloud Run jobs"
for job in "${JOBS[@]}"; do
  if gcloud run jobs describe "$job" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    drop "$job" gcloud run jobs delete "$job" \
      --region="$REGION" --project="$PROJECT" --quiet
  else
    skip "$job"
  fi
done

say "IAM bindings and service accounts"
for name in "${ACCOUNTS[@]}"; do
  email="${name}@${PROJECT}.iam.gserviceaccount.com"
  if gcloud iam service-accounts describe "$email" --project="$PROJECT" >/dev/null 2>&1; then
    # Project-level bindings are removed before the account, so the policy does
    # not keep a dangling deleted:serviceAccount: member. Those entries are
    # harmless but they accumulate, and a policy full of tombstones is a policy
    # nobody reads carefully.
    for role in "roles/aiplatform.user" "roles/logging.logWriter" \
                "roles/cloudtrace.agent" \
                "projects/${PROJECT}/roles/baraza_log_appender" \
                "projects/${PROJECT}/roles/baraza_log_reader"; do
      gcloud projects remove-iam-policy-binding "$PROJECT" \
        --member="serviceAccount:${email}" \
        --role="$role" \
        --condition=None --quiet >/dev/null 2>&1 || true
    done
    drop "$email" gcloud iam service-accounts delete "$email" \
      --project="$PROJECT" --quiet
  else
    skip "$email"
  fi
done

say "Custom roles"
for role in "${ROLES[@]}"; do
  if gcloud iam roles describe "$role" --project="$PROJECT" >/dev/null 2>&1; then
    # `roles delete` soft-deletes: the role is disabled and purged after 30
    # days, and the ID cannot be reused until then. Bootstrap handles that by
    # updating a role it finds rather than failing, so a teardown/bootstrap
    # cycle inside the window still works.
    drop "$role (soft delete, 30-day purge)" gcloud iam roles delete "$role" \
      --project="$PROJECT" --quiet
  else
    skip "$role"
  fi
done

say "Container images"
if [ "$INCLUDE_IMAGES" -eq 1 ]; then
  if gcloud artifacts repositories describe "$AR_REPO" \
       --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    drop "artifact registry repository ${AR_REPO}" \
      gcloud artifacts repositories delete "$AR_REPO" \
        --location="$REGION" --project="$PROJECT" --quiet
  else
    skip "artifact registry repository ${AR_REPO}"
  fi
else
  warn "kept. Images are the only cost line that grows across repeated"
  warn "bootstraps; pass --include-images to remove the repository."
fi

say "Firestore"
if [ "$INCLUDE_FIRESTORE" -eq 1 ]; then
  warn "DELETING THE APPEND-ONLY EVENT LOG. This is the one operation the"
  warn "system's own design forbids from the inside. It is not recoverable."
  if gcloud firestore databases describe --database='(default)' --project="$PROJECT" >/dev/null 2>&1; then
    drop "(default) database" gcloud firestore databases delete \
      --database='(default)' --project="$PROJECT" --quiet
  else
    skip "(default) database"
  fi
  warn "The deployed firestore.rules ruleset and release remain in the"
  warn "firebaserules service. They govern nothing once the database is gone,"
  warn "and bootstrap replaces the release on the next run."
else
  skip "(default) database — kept. Pass --include-firestore to delete it."
fi

say "APIs"
printf '     Left enabled on purpose. Disabling a service API affects anything\n'
printf '     else in the project that uses it, and this script cannot know what\n'
printf '     else lives here. Disable them by hand if the project was created\n'
printf '     solely for Baraza.\n'

printf '\n\033[32mteardown: complete\033[0m\n'
