#!/usr/bin/env bash
#
# Verify the append-only guarantee against the live project.
#
#   BARAZA_PROJECT_ID=your-project scripts/verify_append_only.sh
#
# ---------------------------------------------------------------------------
# WHY THIS SCRIPT IS SHAPED LIKE THIS
#
# "The log is append-only" is enforced by two different mechanisms against two
# different sets of callers, and a verification that conflates them proves less
# than it appears to.
#
#   IAM     governs the four service accounts. Firestore security rules are
#           BYPASSED by service-account credentials, so IAM is the only thing
#           standing between the reconcile Job and a delete. The appender role
#           holds datastore.entities.create and neither .update nor .delete.
#
#   RULES   govern client-SDK and API-key traffic — browsers, leaked web
#           configs, and any future surface somebody adds with a client SDK
#           because it was quicker. `allow update: if false` covers those.
#
# So this script runs up to four checks and says exactly which ones ran. A check
# that was skipped is reported as skipped, never rolled into a pass. The reason
# that matters here more than usual: the person running this is often a project
# owner, and an owner's own credentials bypass both layers — an owner
# successfully updating a document proves nothing about either mechanism, and a
# script that ran that request and printed a green tick would be worse than no
# script at all.
# ---------------------------------------------------------------------------

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

readonly PROJECT="${BARAZA_PROJECT_ID:-}"
readonly RULES_FILE="deploy/firestore.rules"
readonly FS_BASE="https://firestore.googleapis.com/v1/projects"

PASSED=0
SKIPPED=0
FAILED=0

section() { printf '\n\033[1m%s\033[0m\n' "$*"; }
pass()  { PASSED=$((PASSED + 1)); printf '     \033[32mPASS\033[0m  %s\n' "$*"; }
fail()  { FAILED=$((FAILED + 1)); printf '     \033[31mFAIL\033[0m  %s\n' "$*"; }
omit()  { SKIPPED=$((SKIPPED + 1)); printf '     \033[33mSKIP\033[0m  %s\n' "$*"; }
note()  { printf '           %s\n' "$*"; }

[ -n "$PROJECT" ] || { printf 'BARAZA_PROJECT_ID is unset.\n' >&2; exit 2; }
command -v gcloud >/dev/null 2>&1 || { printf 'gcloud is not on PATH.\n' >&2; exit 1; }
command -v curl   >/dev/null 2>&1 || { printf 'curl is not on PATH.\n' >&2; exit 1; }

TOKEN="$(gcloud auth print-access-token 2>/dev/null || true)"
[ -n "$TOKEN" ] || { printf 'could not mint an access token.\n' >&2; exit 1; }

printf 'Append-only verification — project %s\n' "$PROJECT"
printf '%s\n' "======================================================================"

# --------------------------------------------------------------------------
section "1. The deployed ruleset is the file in this repository"

LIVE_RULES="$(curl -s \
  -H "Authorization: Bearer ${TOKEN}" \
  "https://firebaserules.googleapis.com/v1/projects/${PROJECT}/releases/cloud.firestore" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin).get("rulesetName",""))' 2>/dev/null || true)"

if [ -z "$LIVE_RULES" ]; then
  fail "no cloud.firestore release found. Run: make bootstrap"
else
  DEPLOYED_SOURCE="$(curl -s \
    -H "Authorization: Bearer ${TOKEN}" \
    "https://firebaserules.googleapis.com/v1/${LIVE_RULES}" \
    | python3 -c '
import json, sys
payload = json.load(sys.stdin)
files = payload.get("source", {}).get("files", [])
sys.stdout.write(files[0]["content"] if files else "")
' 2>/dev/null || true)"

  if [ -z "$DEPLOYED_SOURCE" ]; then
    fail "release ${LIVE_RULES} exists but its source could not be read"
  elif printf '%s' "$DEPLOYED_SOURCE" | diff -q - "$RULES_FILE" >/dev/null 2>&1; then
    pass "deployed ruleset is byte-identical to ${RULES_FILE}"
    note "${LIVE_RULES}"
  else
    fail "deployed ruleset DIFFERS from ${RULES_FILE}"
    note "the file below is what the repository claims is deployed:"
    printf '%s' "$DEPLOYED_SOURCE" | diff - "$RULES_FILE" | head -40 | sed 's/^/           /'
  fi
fi

# --------------------------------------------------------------------------
section "2. The appender role cannot update or delete"

for role in baraza_log_appender baraza_log_reader; do
  PERMS="$(gcloud iam roles describe "$role" --project="$PROJECT" \
             --format='value(includedPermissions)' 2>/dev/null || true)"
  if [ -z "$PERMS" ]; then
    fail "custom role ${role} not found. Run: make bootstrap"
    continue
  fi
  BAD=""
  case "$PERMS" in *datastore.entities.update*) BAD="${BAD} update" ;; esac
  case "$PERMS" in *datastore.entities.delete*) BAD="${BAD} delete" ;; esac
  if [ -n "$BAD" ]; then
    fail "${role} holds datastore.entities.${BAD# }"
  else
    pass "${role} holds neither datastore.entities.update nor .delete"
  fi
done

# Named explicitly, because an IAM matrix that implies more than IAM can do is
# the kind of overclaim this repository exists to avoid.
note ""
note "NOT verifiable by IAM, and not claimed anywhere: that baraza-ingest cannot"
note "write an event whose event_type is claim.committed. IAM's Firestore"
note "permissions are per-operation and per-database; they cannot express a"
note "predicate over a document field. That split is enforced by the rules file"
note "(check 3) and by the code path, and deploy/README.md says so per row."

# --------------------------------------------------------------------------
section "3. A rules-governed client cannot update an event"

DOC_ID=""
LIST="$(curl -s -H "Authorization: Bearer ${TOKEN}" \
  "${FS_BASE}/${PROJECT}/databases/(default)/documents/events?pageSize=1" || true)"
DOC_ID="$(printf '%s' "$LIST" | python3 -c '
import json, sys
try:
    docs = json.load(sys.stdin).get("documents", [])
except Exception:
    docs = []
sys.stdout.write(docs[0]["name"].rsplit("/", 1)[-1] if docs else "")
' 2>/dev/null || true)"

if [ -z "$DOC_ID" ]; then
  # Rules are evaluated before existence, so a synthetic ID exercises the same
  # `allow update: if false` branch. Said out loud so nobody reads the result as
  # "an existing event was protected" when no event existed.
  DOC_ID="evt_00000000000000000000000000000000"
  note "no events in the log yet; using a synthetic document ID"
  note "(rules are evaluated before document existence, so the branch is the same)"
fi

if [ -z "${BARAZA_WEB_API_KEY:-}" ]; then
  omit "BARAZA_WEB_API_KEY is unset"
  note "Firestore's REST API needs either an OAuth token or a Firebase Web API"
  note "key. An OAuth token from your own account BYPASSES rules — running that"
  note "request would prove nothing and would probably succeed, which is why it"
  note "is not run. To exercise the rules path, create a Firebase Web App in"
  note "this project, then re-run with its key:"
  note ""
  note "  BARAZA_WEB_API_KEY=AIza... scripts/verify_append_only.sh"
  note ""
  note "The request it will make, verbatim:"
  note ""
  note "  curl -i -X PATCH \\"
  note "    '${FS_BASE}/${PROJECT}/databases/(default)/documents/events/${DOC_ID}?key=\$KEY' \\"
  note "    -H 'Content-Type: application/json' \\"
  note "    -d '{\"fields\":{\"actor\":{\"stringValue\":\"tamper\"}}}'"
  note ""
  note "  expected: HTTP 403, \"Missing or insufficient permissions\""
else
  CODE="$(curl -s -o /tmp/baraza-appendonly.json -w '%{http_code}' \
    -X PATCH \
    "${FS_BASE}/${PROJECT}/databases/(default)/documents/events/${DOC_ID}?key=${BARAZA_WEB_API_KEY}" \
    -H 'Content-Type: application/json' \
    -d '{"fields":{"actor":{"stringValue":"tamper"}}}' || true)"
  if [ "$CODE" = "403" ]; then
    pass "update rejected with HTTP 403 by the deployed rules"
  else
    fail "update returned HTTP ${CODE}; expected 403"
    note "$(head -c 400 /tmp/baraza-appendonly.json 2>/dev/null || true)"
  fi

  CODE="$(curl -s -o /tmp/baraza-appendonly.json -w '%{http_code}' \
    -X DELETE \
    "${FS_BASE}/${PROJECT}/databases/(default)/documents/events/${DOC_ID}?key=${BARAZA_WEB_API_KEY}" || true)"
  if [ "$CODE" = "403" ]; then
    pass "delete rejected with HTTP 403 by the deployed rules"
  else
    fail "delete returned HTTP ${CODE}; expected 403"
    note "$(head -c 400 /tmp/baraza-appendonly.json 2>/dev/null || true)"
  fi
fi

# --------------------------------------------------------------------------
section "4. A read-only service account cannot write"

SUCCESSOR_SA="baraza-successor@${PROJECT}.iam.gserviceaccount.com"
IMPERSONATED="$(gcloud auth print-access-token \
  --impersonate-service-account="$SUCCESSOR_SA" 2>/dev/null || true)"

if [ -z "$IMPERSONATED" ]; then
  omit "cannot impersonate ${SUCCESSOR_SA}"
  note "This needs roles/iam.serviceAccountTokenCreator on that account, which"
  note "bootstrap deliberately does NOT grant — a permission handed out so a"
  note "test can pass is a permission the test then stops testing. Grant it to"
  note "yourself explicitly if you want this check, and revoke it afterwards."
else
  CODE="$(curl -s -o /tmp/baraza-appendonly.json -w '%{http_code}' \
    -X PATCH \
    "${FS_BASE}/${PROJECT}/databases/(default)/documents/events/${DOC_ID}" \
    -H "Authorization: Bearer ${IMPERSONATED}" \
    -H 'Content-Type: application/json' \
    -d '{"fields":{"actor":{"stringValue":"tamper"}}}' || true)"
  if [ "$CODE" = "403" ]; then
    pass "successor account's update rejected with HTTP 403 by IAM"
  else
    fail "successor account's update returned HTTP ${CODE}; expected 403"
    note "$(head -c 400 /tmp/baraza-appendonly.json 2>/dev/null || true)"
  fi
fi

# --------------------------------------------------------------------------
printf '\n%s\n' "======================================================================"
printf 'passed %d   skipped %d   failed %d\n' "$PASSED" "$SKIPPED" "$FAILED"
if [ "$SKIPPED" -gt 0 ]; then
  printf 'Skipped checks were not run and are not evidence of anything.\n'
fi
[ "$FAILED" -eq 0 ] || exit 1
