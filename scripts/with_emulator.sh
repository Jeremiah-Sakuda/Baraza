#!/usr/bin/env bash
#
# Run a command against a throwaway Firestore emulator.
#
#   scripts/with_emulator.sh .venv/bin/pytest tests/emulator -q
#
# Starts the emulator, exports FIRESTORE_EMULATOR_HOST, runs "$@", and tears the
# emulator down on every exit path including a failed command, Ctrl-C, and a
# SIGTERM from CI. A leaked emulator holds its port, and the next run then fails
# for a reason that has nothing to do with the code under test — so teardown is
# a trap, not a line at the bottom of the script.
#
# Preconditions are checked and reported rather than worked around. If the
# emulator cannot start, this exits nonzero and says why. It never falls through
# to running the tests without an emulator: a green run that silently skipped
# the thing it was meant to exercise is worse than a red one, because only one
# of those gets noticed.
#
# The emulator holds no credentials and reaches no network. BARAZA_PROJECT_ID is
# set to a local-only value because schema/models.py refuses to default it, and
# defaulting a project ID is how writes land in the wrong place.

set -euo pipefail

HOST="${BARAZA_EMULATOR_HOST:-127.0.0.1}"
PORT="${BARAZA_EMULATOR_PORT:-8231}"
READY_TIMEOUT="${BARAZA_EMULATOR_TIMEOUT:-60}"
LOG_FILE="$(mktemp -t baraza-emulator.XXXXXX)"
EMULATOR_PID=""

die() {
  echo "with_emulator: $*" >&2
  exit 1
}

cleanup() {
  local status=$?
  if [[ -n "${EMULATOR_PID}" ]] && kill -0 "${EMULATOR_PID}" 2>/dev/null; then
    # The gcloud wrapper spawns a Java child. Signalling the process group is
    # what actually stops both; signalling only the wrapper orphans the JVM and
    # leaves the port bound.
    kill -TERM -- "-${EMULATOR_PID}" 2>/dev/null \
      || kill -TERM "${EMULATOR_PID}" 2>/dev/null \
      || true
    for _ in $(seq 1 20); do
      kill -0 "${EMULATOR_PID}" 2>/dev/null || break
      sleep 0.25
    done
    kill -KILL -- "-${EMULATOR_PID}" 2>/dev/null || true
  fi
  if [[ ${status} -ne 0 && -s "${LOG_FILE}" ]]; then
    echo "with_emulator: emulator log tail ------------------------------" >&2
    tail -n 25 "${LOG_FILE}" >&2
    echo "--------------------------------------------------------------" >&2
  fi
  rm -f "${LOG_FILE}"
  exit "${status}"
}
trap cleanup EXIT INT TERM

[[ $# -gt 0 ]] || die "usage: $0 <command> [args...]"

command -v gcloud >/dev/null 2>&1 || die \
  "gcloud is not on PATH. Install the Google Cloud SDK and the Firestore
  emulator:  gcloud components install cloud-firestore-emulator"

# `command -v java` is not enough: macOS ships a /usr/bin/java stub that exists
# and cannot run anything, which turns a missing JDK into a confusing emulator
# startup failure twenty seconds later instead of a clear message now.
java -version >/dev/null 2>&1 || die \
  "java is on PATH but will not run. The Firestore emulator is a JVM process;
  install a JDK (17 or later) and re-run."

if command -v lsof >/dev/null 2>&1 && lsof -iTCP:"${PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port ${PORT} is already in use. Set BARAZA_EMULATOR_PORT to a free port."
fi

PROJECT="${BARAZA_PROJECT_ID:-baraza-emulator-local}"

echo "with_emulator: starting Firestore emulator on ${HOST}:${PORT}"

# set -m puts the background job in its own process group, which is what makes
# the group-signal in cleanup() reach the JVM child.
set -m
gcloud emulators firestore start \
  --host-port="${HOST}:${PORT}" \
  --project="${PROJECT}" \
  >"${LOG_FILE}" 2>&1 &
EMULATOR_PID=$!
set +m

deadline=$(( $(date +%s) + READY_TIMEOUT ))
until (exec 3<>"/dev/tcp/${HOST}/${PORT}") 2>/dev/null; do
  kill -0 "${EMULATOR_PID}" 2>/dev/null || die "emulator exited before becoming ready"
  [[ $(date +%s) -lt ${deadline} ]] || die "emulator did not become ready in ${READY_TIMEOUT}s"
  sleep 0.25
done
exec 3<&- 2>/dev/null || true

echo "with_emulator: ready. running: $*"

export FIRESTORE_EMULATOR_HOST="${HOST}:${PORT}"
export GOOGLE_CLOUD_PROJECT="${PROJECT}"
export BARAZA_PROJECT_ID="${PROJECT}"

"$@"
