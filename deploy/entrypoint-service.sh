#!/usr/bin/env bash
#
# Cloud Run service container entrypoint.
#
# One image serves both FastAPI apps; `BARAZA_APP` selects which. Two images
# built from identical dependency sets would drift apart the first time one was
# rebuilt and the other was not, and "the successor service is running a
# different build of the visibility boundary than the interview service" is not
# a sentence this project can afford to be true.
set -euo pipefail

readonly APP="${BARAZA_APP:?BARAZA_APP is unset: expected baraza.interview.service:app or baraza.successor.service:app}"
readonly PORT="${PORT:-8080}"

# One worker per container on purpose. Cloud Run scales by instance, and a
# second worker inside the container would double the memory floor for a surface
# that is idle most of the time — min-instances is 0 precisely so idle costs
# nothing.
echo "baraza service : ${APP} on :${PORT}"
exec uvicorn "${APP}" \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 1 \
  --no-server-header \
  --timeout-keep-alive 75
