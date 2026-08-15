#!/usr/bin/env bash
#
# make bootstrap — provision the whole deploy lane in one command (BAR-021,
# BAR-410, BAR-411).
#
# Idempotent. Every step describes itself before it runs, checks whether the
# thing already exists, and creates it only if it does not. Running this twice
# is a no-op with a longer transcript.
#
# ---------------------------------------------------------------------------
# THE RULE THIS SCRIPT IS WRITTEN AROUND
#
# PRD §2.5.2: stop, never route around. On a missing permission, a missing API,
# or a refused grant, this script writes STOPPED-DEPLOY.md and halts. It never
# widens a scope, a key, or a service-account role to unblock itself, and it
# never falls back to a broader predefined role when a custom one is rejected.
# Those are the documented failure modes of an unattended agent at a red gate,
# and a bootstrap script is exactly where they are most tempting: the fix is
# always one `roles/editor` away.
#
# The roles below are granted up front, as declared provisioning. That is not
# the same thing as widening: nothing here reacts to a failure by asking for
# more than it started with.
# ---------------------------------------------------------------------------
#
# Usage:
#   BARAZA_PROJECT_ID=your-project make bootstrap
#
# Optional environment:
#   BARAZA_REGION               Cloud Run + Scheduler region   (default us-central1)
#   BARAZA_FIRESTORE_LOCATION   Firestore location             (default nam5)
#   BARAZA_IMAGE_TAG            Image tag                      (default: git sha)
#   BARAZA_SKIP_BUILD=1         Reuse the existing images
#   BARAZA_SKIP_TEST_FIRE=1     Do not trigger the Scheduler once at the end

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ------------------------------------------------------------------ constants

readonly PROJECT="${BARAZA_PROJECT_ID:-}"
readonly REGION="${BARAZA_REGION:-us-central1}"
readonly FS_LOCATION="${BARAZA_FIRESTORE_LOCATION:-nam5}"
readonly AR_REPO="baraza"

readonly SA_INGEST="baraza-ingest"
readonly SA_RECONCILE="baraza-reconcile"
readonly SA_INTERVIEW="baraza-interview"
readonly SA_SUCCESSOR="baraza-successor"

readonly ROLE_APPENDER="baraza_log_appender"
readonly ROLE_READER="baraza_log_reader"

readonly JOB_INGEST="baraza-ingest"
readonly JOB_RECONCILE="baraza-reconcile"
readonly SVC_INTERVIEW="baraza-interview"
readonly SVC_SUCCESSOR="baraza-successor"

readonly RULES_FILE="deploy/firestore.rules"
readonly SCHEDULER_FILE="deploy/scheduler.yaml"

STEP=0

# ------------------------------------------------------------------- output

say() {
  STEP=$((STEP + 1))
  printf '\n\033[1m[%02d] %s\033[0m\n' "$STEP" "$*"
}

info() { printf '     %s\n' "$*"; }
ok()   { printf '     \033[32mok\033[0m  %s\n' "$*"; }
skip() { printf '     \033[2m--\033[0m  %s\n' "$*"; }

# stop() is the whole safety story. It records what failed, what was NOT
# attempted, and halts — it does not retry with more permission.
stop() {
  local gate="$1"; shift
  local detail="$*"
  {
    printf '# STOPPED-DEPLOY.md\n\n'
    printf '**Gate:** %s\n\n' "$gate"
    printf '**When:** %s\n\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    printf '**Project:** %s   **Region:** %s\n\n' "${PROJECT:-<unset>}" "$REGION"
    printf '**Exact error:**\n\n```\n%s\n```\n\n' "$detail"
    printf '**What was NOT attempted:** every step after this one. In particular\n'
    printf 'no role, scope, or key was widened to get past this. Per PRD §2.5.2 the\n'
    printf 'deploy lane stops here and the local build continues unaffected.\n\n'
    printf '**To resume:** fix the condition above and re-run `make bootstrap`.\n'
    printf 'The script is idempotent; completed steps will be skipped.\n'
  } > STOPPED-DEPLOY.md

  printf '\n\033[31mSTOPPED\033[0m at: %s\n' "$gate" >&2
  printf '%s\n\n' "$detail" >&2
  printf 'Written to STOPPED-DEPLOY.md. Nothing was widened to work around it.\n' >&2
  exit 1
}

# Run a gcloud command, capturing output so a failure can be reported verbatim.
run() {
  local gate="$1"; shift
  local out
  if ! out="$("$@" 2>&1)"; then
    stop "$gate" "command: $*
${out}"
  fi
  [ -n "$out" ] && printf '%s\n' "$out" | sed 's/^/       | /'
  return 0
}

# ------------------------------------------------------------------- guards

say "Preflight"

if [ -z "$PROJECT" ]; then
  cat >&2 <<'EOF'
     BARAZA_PROJECT_ID is unset.

     This is not defaulted on purpose. A bootstrap script that guesses its
     project is a bootstrap script that will one day provision a stranger's.
     schema/models.py refuses to default it for the same reason.

         BARAZA_PROJECT_ID=your-project make bootstrap
EOF
  exit 2
fi
ok "project ${PROJECT}, region ${REGION}"

command -v gcloud >/dev/null 2>&1 || stop "preflight" "gcloud is not on PATH."
command -v curl   >/dev/null 2>&1 || stop "preflight" "curl is not on PATH (needed for the Firestore rules API)."

ACTOR="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "$ACTOR" ] && [ "$ACTOR" != "(unset)" ] \
  || stop "preflight" "no active gcloud account. Run: gcloud auth login"
case "$ACTOR" in
  *.gserviceaccount.com) ACTOR_MEMBER="serviceAccount:${ACTOR}" ;;
  *)                     ACTOR_MEMBER="user:${ACTOR}" ;;
esac
ok "authenticated as ${ACTOR}"

gcloud projects describe "$PROJECT" >/dev/null 2>&1 \
  || stop "preflight" "project ${PROJECT} is not visible to ${ACTOR}."
ok "project reachable"

[ -f "$RULES_FILE" ]     || stop "preflight" "${RULES_FILE} is missing."
[ -f "$SCHEDULER_FILE" ] || stop "preflight" "${SCHEDULER_FILE} is missing."

# The ingest Job's entrypoint lives in baraza.cli, which the ingestion lane
# owns. Its absence is reported, not routed around, and it does not block the
# rest of the lane — the Job is still provisioned so the Scheduler, the IAM
# surface, and the services can be verified tonight.
INGEST_ENTRYPOINT_PRESENT=1
if [ ! -f "src/baraza/cli.py" ]; then
  INGEST_ENTRYPOINT_PRESENT=0
  info "WARNING: src/baraza/cli.py is absent. The ingest Job will be created but"
  info "         cannot run until the ingestion lane lands its entrypoint. This"
  info "         is recorded in the summary rather than papered over."
fi

if [ -n "${BARAZA_IMAGE_TAG:-}" ]; then
  IMAGE_TAG="$BARAZA_IMAGE_TAG"
elif command -v git >/dev/null 2>&1 && git -C "$REPO_ROOT" rev-parse --short HEAD >/dev/null 2>&1; then
  IMAGE_TAG="$(git -C "$REPO_ROOT" rev-parse --short HEAD)"
else
  IMAGE_TAG="bootstrap"
fi
readonly IMAGE_TAG
readonly IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT}/${AR_REPO}"
readonly JOB_IMAGE="${IMAGE_BASE}/job:${IMAGE_TAG}"
readonly SERVICE_IMAGE="${IMAGE_BASE}/service:${IMAGE_TAG}"
ok "image tag ${IMAGE_TAG}"

# --------------------------------------------------------------------- APIs

say "Enabling APIs"

# Each entry names the requirement it serves. An API enabled "just in case" is
# an API nobody can justify removing later.
APIS=(
  run.googleapis.com               # Cloud Run Jobs + services            BAR-410
  firestore.googleapis.com         # the append-only claim-event log      BAR-410
  aiplatform.googleapis.com        # Gemini via Vertex                    BAR-020
  cloudscheduler.googleapis.com    # the nightly reconcile trigger        BAR-021
  artifactregistry.googleapis.com  # image storage                        BAR-410
  cloudbuild.googleapis.com        # image builds                         BAR-410
  firebase.googleapis.com          # required to hold Firestore rules
  firebaserules.googleapis.com     # deploying deploy/firestore.rules
  cloudtrace.googleapis.com        # OpenTelemetry span export
  logging.googleapis.com           # job + service logs
  iam.googleapis.com               # custom roles + service accounts
)
info "${#APIS[@]} services"
run "api enablement" gcloud services enable "${APIS[@]}" --project="$PROJECT"
ok "APIs enabled (idempotent; already-enabled services are a no-op)"

# ---------------------------------------------------------------- Firestore

say "Firestore (native mode)"

if gcloud firestore databases describe --database='(default)' --project="$PROJECT" >/dev/null 2>&1; then
  skip "(default) database already exists"
else
  info "creating (default) in ${FS_LOCATION}, type firestore-native"
  # Native mode, not Datastore mode. The store uses document create() with an
  # exists-precondition, which is what makes append-only idempotent under
  # retries; Datastore mode does not offer the same semantics.
  run "firestore create" gcloud firestore databases create \
    --location="$FS_LOCATION" \
    --type=firestore-native \
    --project="$PROJECT" \
    --quiet
  ok "database created"
fi

# ------------------------------------------------------------ Firestore rules

say "Deploying ${RULES_FILE} (append-only at the database level)"

TOKEN="$(gcloud auth print-access-token 2>/dev/null || true)"
[ -n "$TOKEN" ] || stop "rules deploy" "could not mint an access token."

# The project must be a Firebase project to hold a ruleset. Adding Firebase to
# an existing GCP project changes no IAM and no data; it registers the project
# with the Firebase management surface so firebaserules has somewhere to put the
# release.
ADD_FB="$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST "https://firebase.googleapis.com/v1beta1/projects/${PROJECT}:addFirebase" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT}" \
  -H 'Content-Type: application/json' \
  -d '{}' || true)"
case "$ADD_FB" in
  200|409) ok "firebase registration present (http ${ADD_FB})" ;;
  *)       info "addFirebase returned http ${ADD_FB}; continuing to the ruleset call, which will report definitively" ;;
esac

# Build the ruleset payload with python: the rules file contains quotes,
# newlines and braces, and hand-rolling that into JSON with sed is how a
# deployed ruleset ends up subtly different from the file in the repository.
RULES_PAYLOAD="$(python3 - "$RULES_FILE" <<'PY'
import json, sys
source = open(sys.argv[1], encoding="utf-8").read()
print(json.dumps({"source": {"files": [{"name": "firestore.rules", "content": source}]}}))
PY
)"

RULESET_RESPONSE="$(curl -s \
  -X POST "https://firebaserules.googleapis.com/v1/projects/${PROJECT}/rulesets" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT}" \
  -H 'Content-Type: application/json' \
  -d "$RULES_PAYLOAD" || true)"

RULESET_NAME="$(printf '%s' "$RULESET_RESPONSE" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("name",""))' 2>/dev/null || true)"

if [ -z "$RULESET_NAME" ]; then
  # A log the rules do not protect is a log whose append-only guarantee rests
  # on one layer instead of two. That is a stop condition, not a warning:
  # continuing would deploy services against an unprotected database and let the
  # README claim a property the project does not have.
  stop "firestore rules" "could not create a ruleset from ${RULES_FILE}.
Response:
${RULESET_RESPONSE}

The append-only guarantee has two layers (IAM, and these rules). Deploying with
one of them missing would make deploy/README.md's claim untrue, so the lane
stops here rather than continuing and writing the claim anyway."
fi
ok "ruleset ${RULESET_NAME}"

RELEASE_BODY="$(python3 - "$PROJECT" "$RULESET_NAME" <<'PY'
import json, sys
project, ruleset = sys.argv[1], sys.argv[2]
print(json.dumps({
    "name": f"projects/{project}/releases/cloud.firestore",
    "rulesetName": ruleset,
}))
PY
)"

# Try to update an existing release first; fall back to creating one. Both are
# the same intent — "cloud.firestore points at this ruleset" — and which verb
# applies depends only on whether rules have ever been deployed here.
RELEASE_CODE="$(curl -s -o /tmp/baraza-release.json -w '%{http_code}' \
  -X PATCH "https://firebaserules.googleapis.com/v1/projects/${PROJECT}/releases/cloud.firestore" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "x-goog-user-project: ${PROJECT}" \
  -H 'Content-Type: application/json' \
  -d "{\"release\": ${RELEASE_BODY}}" || true)"

if [ "$RELEASE_CODE" != "200" ]; then
  RELEASE_CODE="$(curl -s -o /tmp/baraza-release.json -w '%{http_code}' \
    -X POST "https://firebaserules.googleapis.com/v1/projects/${PROJECT}/releases" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "x-goog-user-project: ${PROJECT}" \
    -H 'Content-Type: application/json' \
    -d "$RELEASE_BODY" || true)"
fi

[ "$RELEASE_CODE" = "200" ] \
  || stop "firestore rules release" "release call returned http ${RELEASE_CODE}.
$(cat /tmp/baraza-release.json 2>/dev/null || true)"
ok "release cloud.firestore -> ${RULESET_NAME}"
info "verify a rejected update with: scripts/verify_append_only.sh"

# --------------------------------------------------------- Artifact Registry

say "Artifact Registry"

if gcloud artifacts repositories describe "$AR_REPO" \
     --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  skip "repository ${AR_REPO} already exists"
else
  run "artifact registry" gcloud artifacts repositories create "$AR_REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Baraza job and service images" \
    --project="$PROJECT" --quiet
  ok "repository ${AR_REPO} created"
fi

# ------------------------------------------------------------ service accounts

say "Service accounts (four, least privilege)"

create_sa() {
  local name="$1" display="$2" description="$3"
  if gcloud iam service-accounts describe "${name}@${PROJECT}.iam.gserviceaccount.com" \
       --project="$PROJECT" >/dev/null 2>&1; then
    skip "${name} already exists"
  else
    run "service account ${name}" gcloud iam service-accounts create "$name" \
      --display-name="$display" \
      --description="$description" \
      --project="$PROJECT" --quiet
    ok "${name} created"
  fi
}

create_sa "$SA_INGEST" "Baraza ingest" \
  "Corpus ingestion Job. Appends claim.asserted. Cannot update or delete."
create_sa "$SA_RECONCILE" "Baraza reconcile" \
  "Nightly reconcile Job. Appends contradiction.* and heartbeat. Cannot update or delete."
create_sa "$SA_INTERVIEW" "Baraza interview" \
  "Interview service and approval path. The only writer of claim.committed."
create_sa "$SA_SUCCESSOR" "Baraza successor" \
  "Public successor surface. Read only: no create, no update, no delete."

EMAIL_INGEST="${SA_INGEST}@${PROJECT}.iam.gserviceaccount.com"
EMAIL_RECONCILE="${SA_RECONCILE}@${PROJECT}.iam.gserviceaccount.com"
EMAIL_INTERVIEW="${SA_INTERVIEW}@${PROJECT}.iam.gserviceaccount.com"
EMAIL_SUCCESSOR="${SA_SUCCESSOR}@${PROJECT}.iam.gserviceaccount.com"

# ---------------------------------------------------------------- custom roles

say "Custom IAM roles"

# Two roles, not four, and the reason is worth stating because the alternative
# looks better and is a lie.
#
# IAM's Firestore permissions are per-operation (create / get / list / update /
# delete) and per-database. They cannot express "this principal may create
# documents whose event_type field is claim.asserted." So four roles whose
# permission sets were identical, named after four different responsibilities,
# would be an IAM matrix that reads like enforcement and enforces nothing.
#
# What IAM genuinely enforces here is the append-only guarantee (create without
# update or delete, for every writer) and the read-only successor. What enforces
# the event-type split is code plus the deployment shape plus the Firestore
# rules, and deploy/README.md's matrix says so per row.
upsert_role() {
  local role_id="$1" title="$2" description="$3" permissions="$4"
  if gcloud iam roles describe "$role_id" --project="$PROJECT" >/dev/null 2>&1; then
    info "updating ${role_id} to the declared permission set"
    # --permissions replaces rather than merges, so this is a declaration, not
    # an accumulation. A role that only ever grew would drift away from least
    # privilege one unblocking session at a time.
    run "role ${role_id}" gcloud iam roles update "$role_id" \
      --project="$PROJECT" \
      --title="$title" \
      --description="$description" \
      --permissions="$permissions" \
      --quiet
    ok "${role_id} updated"
  else
    run "role ${role_id}" gcloud iam roles create "$role_id" \
      --project="$PROJECT" \
      --title="$title" \
      --description="$description" \
      --permissions="$permissions" \
      --stage=GA \
      --quiet
    ok "${role_id} created"
  fi
}

# No datastore.entities.update. No datastore.entities.delete. That omission is
# the append-only guarantee at the IAM layer, and it is the layer that actually
# applies to these service accounts — Firestore rules are bypassed by
# service-account credentials.
upsert_role "$ROLE_APPENDER" "Baraza log appender" \
  "Append-only access to the claim-event log: create and read, never update or delete." \
  "datastore.databases.get,datastore.entities.create,datastore.entities.get,datastore.entities.list,datastore.indexes.list"

upsert_role "$ROLE_READER" "Baraza log reader" \
  "Read-only access to the claim-event log. No writes of any kind." \
  "datastore.databases.get,datastore.entities.get,datastore.entities.list,datastore.indexes.list"

# ------------------------------------------------------------------- bindings

say "IAM bindings"

bind() {
  local member="$1" role="$2"
  run "binding ${role} -> ${member}" gcloud projects add-iam-policy-binding "$PROJECT" \
    --member="serviceAccount:${member}" \
    --role="$role" \
    --condition=None \
    --quiet
}

for sa in "$EMAIL_INGEST" "$EMAIL_RECONCILE" "$EMAIL_INTERVIEW"; do
  bind "$sa" "projects/${PROJECT}/roles/${ROLE_APPENDER}"
done
bind "$EMAIL_SUCCESSOR" "projects/${PROJECT}/roles/${ROLE_READER}"
ok "log access bound (three appenders, one reader)"

# Every surface calls Gemini through Vertex. aiplatform.user is the narrowest
# predefined role that permits prediction; there is no create-only variant.
for sa in "$EMAIL_INGEST" "$EMAIL_RECONCILE" "$EMAIL_INTERVIEW" "$EMAIL_SUCCESSOR"; do
  bind "$sa" "roles/aiplatform.user"
  bind "$sa" "roles/logging.logWriter"
  bind "$sa" "roles/cloudtrace.agent"
done
ok "vertex, logging and trace bound"

# Scoped to the one Job resource, not project-wide. This is the binding that
# lets Cloud Scheduler trigger the nightly run, and the identity that can
# trigger the reconciler is exactly the identity that does the reconciler's
# work. Applied after the Job exists — see below.

# Deploying Cloud Run with a runtime service account requires actAs on that
# account. Granted per service account rather than project-wide.
for sa in "$EMAIL_INGEST" "$EMAIL_RECONCILE" "$EMAIL_INTERVIEW" "$EMAIL_SUCCESSOR"; do
  run "actAs ${sa}" gcloud iam service-accounts add-iam-policy-binding "$sa" \
    --member="$ACTOR_MEMBER" \
    --role="roles/iam.serviceAccountUser" \
    --project="$PROJECT" --quiet
done
ok "actAs granted to ${ACTOR} on the four runtime accounts"

# --------------------------------------------------------------------- build

say "Building images"

if [ "${BARAZA_SKIP_BUILD:-0}" = "1" ]; then
  skip "BARAZA_SKIP_BUILD=1; reusing ${IMAGE_TAG}"
else
  info "cloud build: deploy/Dockerfile.job and deploy/Dockerfile.service"
  info "tag ${IMAGE_TAG}"
  run "cloud build" gcloud builds submit "$REPO_ROOT" \
    --config=deploy/cloudbuild.yaml \
    --substitutions="_REGION=${REGION},_REPO=${AR_REPO},_TAG=${IMAGE_TAG}" \
    --project="$PROJECT" --quiet
  ok "images pushed"
fi

# ---------------------------------------------------------------------- jobs

say "Cloud Run Jobs"

upsert_job() {
  local name="$1" sa="$2"; shift 2
  local verb=create
  if gcloud run jobs describe "$name" --region="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
    verb=update
    info "updating ${name} in place"
  else
    info "creating ${name}"
  fi
  # In place, deliberately. BAR-021's stub is replaced by BAR-321's real
  # reconciler under the same Job name so the execution history is continuous
  # across the changeover and the replacement date is identifiable in it. A new
  # Job name would restart the history at zero and quietly discard the evidence
  # the early deploy exists to accumulate.
  run "job ${name}" gcloud run jobs "$verb" "$name" \
    --image="$JOB_IMAGE" \
    --region="$REGION" \
    --service-account="$sa" \
    --task-timeout=1800s \
    --memory=1Gi \
    --cpu=1 \
    --max-retries=1 \
    --project="$PROJECT" --quiet "$@"
  ok "${name} ${verb}d"
}

# max-retries=1 rather than the default 3: Cloud Scheduler already retries this
# trigger three times (deploy/scheduler.yaml). Stacking job-level retries on top
# would turn one failed night into nine executions in the history, and the
# history is the evidence.
upsert_job "$JOB_RECONCILE" "$EMAIL_RECONCILE" \
  --set-env-vars="BARAZA_JOB=reconcile,BARAZA_RECONCILE_MODE=${BARAZA_RECONCILE_MODE:-stub},BARAZA_PROJECT_ID=${PROJECT},BARAZA_LOCATION=${REGION},BARAZA_OFFLINE=0"

upsert_job "$JOB_INGEST" "$EMAIL_INGEST" \
  --set-env-vars="BARAZA_JOB=ingest,BARAZA_PROJECT_ID=${PROJECT},BARAZA_LOCATION=${REGION},BARAZA_OFFLINE=0"

if [ "$INGEST_ENTRYPOINT_PRESENT" = "0" ]; then
  info "NOTE: ${JOB_INGEST} is provisioned but its entrypoint (baraza.cli) has"
  info "      not landed. Executing it will exit 78 with an explanation rather"
  info "      than exiting 0 having ingested nothing."
fi

# Scoped invoker binding, now that the Job resource exists.
run "scheduler invoker" gcloud run jobs add-iam-policy-binding "$JOB_RECONCILE" \
  --region="$REGION" \
  --member="serviceAccount:${EMAIL_RECONCILE}" \
  --role="roles/run.invoker" \
  --project="$PROJECT" --quiet
ok "run.invoker on ${JOB_RECONCILE} scoped to ${SA_RECONCILE}"

# ------------------------------------------------------------------ services

say "Cloud Run services"

RENDER_DIR="$(mktemp -d)"
trap 'rm -rf "$RENDER_DIR"' EXIT

render_service() {
  local source="$1" target="$2"
  sed -e "s|__PROJECT_ID__|${PROJECT}|g" \
      -e "s|__REGION__|${REGION}|g" \
      -e "s|__SERVICE_IMAGE__|${SERVICE_IMAGE}|g" \
      "$source" > "$target"
  # A placeholder that survived substitution would deploy a service pointing at
  # the literal string __SERVICE_IMAGE__, which fails at pull time with an error
  # that names Artifact Registry rather than this file.
  if grep -q '__' "$target"; then
    stop "service render" "unsubstituted placeholder left in ${source}:
$(grep -n '__' "$target")"
  fi
}

render_service deploy/service-interview.yaml "${RENDER_DIR}/interview.yaml"
render_service deploy/service-successor.yaml "${RENDER_DIR}/successor.yaml"
ok "rendered both service manifests"

run "deploy ${SVC_INTERVIEW}" gcloud run services replace "${RENDER_DIR}/interview.yaml" \
  --region="$REGION" --project="$PROJECT" --quiet
ok "${SVC_INTERVIEW} deployed (no allUsers binding — authenticated access only)"

run "deploy ${SVC_SUCCESSOR}" gcloud run services replace "${RENDER_DIR}/successor.yaml" \
  --region="$REGION" --project="$PROJECT" --quiet
ok "${SVC_SUCCESSOR} deployed"

# The one public binding in the system. It is safe because of what the service
# can read, not because of what the service is: baraza-successor holds the
# read-only role and constructs its librarian with Audience.PUBLIC, so the only
# claims reachable through it are committed AND explicitly published.
say "Publishing the successor surface"
info "binding allUsers as invoker on ${SVC_SUCCESSOR} only"
if ! out="$(gcloud run services add-iam-policy-binding "$SVC_SUCCESSOR" \
      --region="$REGION" \
      --member="allUsers" \
      --role="roles/run.invoker" \
      --project="$PROJECT" --quiet 2>&1)"; then
  stop "public invoker binding" "could not bind allUsers on ${SVC_SUCCESSOR}:
${out}

This is usually the iam.allowedPolicyMemberDomains org policy. It is NOT
worked around here: the alternative would be to loosen an organization policy,
and BAR-411's logged-out demo surface is not worth that trade. Either grant an
exception for this project deliberately, or host the demo in a project that
permits public Cloud Run services."
fi
ok "successor surface is logged-out readable"

SUCCESSOR_URL="$(gcloud run services describe "$SVC_SUCCESSOR" \
  --region="$REGION" --project="$PROJECT" --format='value(status.url)' 2>/dev/null || true)"
INTERVIEW_URL="$(gcloud run services describe "$SVC_INTERVIEW" \
  --region="$REGION" --project="$PROJECT" --format='value(status.url)' 2>/dev/null || true)"

# ----------------------------------------------------------------- scheduler

say "Cloud Scheduler (BAR-021 nightly reconcile)"

# deploy/scheduler.yaml is the source of truth for cadence. Parsed here rather
# than duplicated, so changing the schedule means changing a committed file.
yaml_top()    { sed -n -E "s/^${2}:[[:space:]]*\"?([^\"#]*[^\" #])\"?[[:space:]]*$/\1/p" "$1" | head -n1; }
yaml_nested() { sed -n -E "s/^[[:space:]]+${2}:[[:space:]]*\"?([^\"#]*[^\" #])\"?[[:space:]]*$/\1/p" "$1" | head -n1; }
yaml_body()   { awk '/^[[:space:]]+body:[[:space:]]*\|/{getline; sub(/^[[:space:]]+/,""); print; exit}' "$1"; }

SCHED_NAME="$(yaml_top "$SCHEDULER_FILE" name)"
SCHED_CRON="$(yaml_top "$SCHEDULER_FILE" schedule)"
SCHED_TZ="$(yaml_top "$SCHEDULER_FILE" timeZone)"
SCHED_DEADLINE="$(yaml_top "$SCHEDULER_FILE" attemptDeadline)"
SCHED_RETRIES="$(yaml_nested "$SCHEDULER_FILE" retryCount)"
SCHED_MINBACK="$(yaml_nested "$SCHEDULER_FILE" minBackoffDuration)"
SCHED_MAXBACK="$(yaml_nested "$SCHEDULER_FILE" maxBackoffDuration)"
SCHED_MAXDUR="$(yaml_nested "$SCHEDULER_FILE" maxRetryDuration)"
SCHED_URI="$(yaml_nested "$SCHEDULER_FILE" uri | sed -e "s|__PROJECT_ID__|${PROJECT}|g" -e "s|__REGION__|${REGION}|g")"
SCHED_BODY="$(yaml_body "$SCHEDULER_FILE")"

for pair in "name:$SCHED_NAME" "schedule:$SCHED_CRON" "timeZone:$SCHED_TZ" \
            "attemptDeadline:$SCHED_DEADLINE" "uri:$SCHED_URI" "body:$SCHED_BODY"; do
  [ -n "${pair#*:}" ] || stop "scheduler config" "could not read '${pair%%:*}' from ${SCHEDULER_FILE}."
done

info "name      ${SCHED_NAME}"
info "schedule  ${SCHED_CRON} (${SCHED_TZ})"
info "target    ${SCHED_URI}"

SCHED_VERB=create
if gcloud scheduler jobs describe "$SCHED_NAME" \
     --location="$REGION" --project="$PROJECT" >/dev/null 2>&1; then
  SCHED_VERB=update
  info "updating existing trigger in place"
fi

run "scheduler ${SCHED_VERB}" gcloud scheduler jobs "$SCHED_VERB" http "$SCHED_NAME" \
  --location="$REGION" \
  --schedule="$SCHED_CRON" \
  --time-zone="$SCHED_TZ" \
  --uri="$SCHED_URI" \
  --http-method=POST \
  --headers="Content-Type=application/json" \
  --message-body="$SCHED_BODY" \
  --oauth-service-account-email="$EMAIL_RECONCILE" \
  --attempt-deadline="$SCHED_DEADLINE" \
  --max-retry-attempts="${SCHED_RETRIES:-3}" \
  --min-backoff="${SCHED_MINBACK:-30s}" \
  --max-backoff="${SCHED_MAXBACK:-300s}" \
  --max-retry-duration="${SCHED_MAXDUR:-3600s}" \
  --description="BAR-021 nightly reconcile. Scheduled runs are labelled scheduled and are never counted as organic activity." \
  --project="$PROJECT" --quiet
ok "trigger ${SCHED_VERB}d"

# ---------------------------------------------------------------- test fire

say "Verifying the trigger"

if [ "${BARAZA_SKIP_TEST_FIRE:-0}" = "1" ]; then
  skip "BARAZA_SKIP_TEST_FIRE=1"
else
  # A trigger that has never fired is a trigger nobody has verified, and the
  # first time it runs unattended at 03:17 is the worst time to discover the
  # request body was malformed. This execution is a bootstrap verification: it
  # is labelled as such here and it is a scheduled-lane run, never organic
  # activity.
  info "firing once to prove the wiring (labelled: bootstrap verification)"
  if ! out="$(gcloud scheduler jobs run "$SCHED_NAME" \
        --location="$REGION" --project="$PROJECT" --quiet 2>&1)"; then
    stop "scheduler test fire" "the trigger was created but firing it failed:
${out}

Not worked around. A nightly job that 400s every night still produces a healthy
looking Scheduler entry, and BAR-021's whole value is that the execution history
is real."
  fi
  ok "trigger fired; check the execution in a moment with:"
  info "  gcloud run jobs executions list --job=${JOB_RECONCILE} --region=${REGION} --project=${PROJECT}"
fi

# ------------------------------------------------------------------- summary

say "Summary"

INGEST_NOTE=""
if [ "$INGEST_ENTRYPOINT_PRESENT" = "0" ]; then
  INGEST_NOTE="  [entrypoint not yet landed]"
fi

cat <<EOF
     project              ${PROJECT}
     region               ${REGION}
     image tag            ${IMAGE_TAG}

     jobs                 ${JOB_RECONCILE} (${BARAZA_RECONCILE_MODE:-stub} mode)
                          ${JOB_INGEST}${INGEST_NOTE}
     services             ${SVC_INTERVIEW}   ${INTERVIEW_URL:-<no url>}
                          ${SVC_SUCCESSOR}   ${SUCCESSOR_URL:-<no url>}
     scheduler            ${SCHED_NAME}  ${SCHED_CRON} ${SCHED_TZ}

     service accounts     ${SA_INGEST}     append-only
                          ${SA_RECONCILE}  append-only + run.invoker on its own Job
                          ${SA_INTERVIEW}  append-only
                          ${SA_SUCCESSOR}  read only

     The interview service is NOT publicly reachable. Open it with:
       gcloud run services proxy ${SVC_INTERVIEW} --region=${REGION} --project=${PROJECT}

     The successor service is the logged-out demo surface. On a fresh project it
     shows nothing, because visibility defaults to private and no approver has
     published anything yet. That is the boundary working, not a broken deploy.

     Verify the append-only rule actually rejects an update:
       scripts/verify_append_only.sh

------------------------------------------------------------------------------
COST SHAPE THROUGH OCT 1 (the judging window)

     No dollar figure is printed here, and the omission is deliberate: this
     project's numbers rule says never write a plausible number where a measured
     one belongs. A monthly estimate typed into a bootstrap script is exactly
     that. What can be stated without measuring is the shape:

       Cloud Run services   min-instances 0. Billed per request-second only.
                            Idle cost between demos is zero, not "low".
       Cloud Run Jobs       Billed only while executing. The nightly stub run
                            is seconds of one vCPU.
       Cloud Scheduler      One job. Published free tier covers three per
                            billing account per month.
       Firestore            One small collection. Storage and operations for a
                            hackathon-scale corpus sit inside the free daily
                            quota; sustained reads from the public surface are
                            the only thing that could change that.
       Artifact Registry    Two images, one tag each per build. Billed per
                            GB-month above the free allowance; old tags
                            accumulate, so this is the line item that grows if
                            bootstrap is run many times.
       Vertex AI            Per token, only when called. The dominant variable
                            and the only one a public endpoint can drive up.
       Logging / Trace      Inside the free tier at this volume.

     The actual spend is NOT YET MEASURED. Measure it, do not estimate it:

       gcloud billing accounts list
       # then, in the console, Billing -> Reports, filtered to project ${PROJECT}

     Standing cost is dominated by whether anything keeps calling Vertex. With
     min-instances 0 and the nightly stub job, nothing does unless a visitor
     asks the successor surface a question.
------------------------------------------------------------------------------
EOF

if [ -f STOPPED-DEPLOY.md ]; then
  # A stale stop record from a previous failed run would misrepresent this one.
  rm -f STOPPED-DEPLOY.md
  info "removed a stale STOPPED-DEPLOY.md from an earlier run"
fi

printf '\n\033[32mbootstrap: complete\033[0m\n'
