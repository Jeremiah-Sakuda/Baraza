"""The Scheduler-facing trigger service — the fix for the 403 in STOPPED-DEPLOY.md.

Cloud Scheduler could not call the Cloud Run Jobs Admin API directly: with every
documented grant in place and verified, admin-activity audit logs showed no
request authenticated as ``baraza-reconcile`` ever reaching the Run API from
Scheduler, while the same SA's own token against the identical URL started an
execution (2026-08-15, re-verified 2026-08-31 — see STOPPED-DEPLOY.md). The
failure was in Scheduler's OAuth token path for that target, not in any IAM
binding, so no further grant could fix it and none was made.

This service is the architectural replacement: Scheduler → OIDC → Cloud Run
*service* is the well-trodden path, and the service — deployed as
``baraza-trigger``, running as the ``baraza-reconcile`` SA — calls ``jobs.run``
itself with its runtime identity, which is exactly the call already proven to
work. No scope widens: the same SA does the same thing, one hop later.

**This path is the only writer of ``BARAZA_RUN_TRIGGER=cloud-scheduler``.** The
container override below is a constant; nothing a caller sends can change it,
and no other code in the repository sets that value. The honest ``scheduled``
flag on every event the job appends rests on this being true: reaching this
endpoint requires ``run.invoker`` on the ``baraza-trigger`` service, which
bootstrap grants only to the Scheduler's OIDC identity. A human who wants a
manual run uses ``gcloud run jobs execute`` and is labelled ``manual``.

Endpoint auth is Cloud Run IAM (the service has no public binding), not
application code — the platform rejects unauthenticated callers before this
process sees them, which is one fewer auth implementation to get wrong.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse

__all__ = ["create_app", "app", "run_url", "override_body"]

_METADATA_TOKEN_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/"
    "service-accounts/default/token"
)

RunJob = Callable[[], str]
"""Starts one execution of the reconcile Job; returns the execution name."""


def run_url(project: str, region: str, job: str) -> str:
    """The Jobs Admin API v2 ``:run`` URL.

    v2 rather than the v1 ``namespaces`` endpoint because it accepts
    ``overrides`` — the mechanism that labels the run as scheduled at the
    container level rather than only in Scheduler's own logs. ``region`` here
    is the Cloud Run region the Job lives in, which is unrelated to the Vertex
    model location.
    """
    return (
        f"https://run.googleapis.com/v2/projects/{project}/locations/{region}"
        f"/jobs/{job}:run"
    )


def override_body() -> dict[str, object]:
    """The constant container override every triggered execution carries.

    ``BARAZA_RUN_TRIGGER=cloud-scheduler`` is what makes
    ``job.resolve_scheduled()`` return True. It is a function returning a fresh
    dict — not a module-level constant — so no request handler can mutate the
    shared copy and quietly change what future runs are labelled as.
    """
    return {
        "overrides": {
            "containerOverrides": [
                {
                    "env": [
                        {"name": "BARAZA_RUN_TRIGGER", "value": "cloud-scheduler"}
                    ]
                }
            ]
        }
    }


def _access_token() -> str:
    """An access token for the service's runtime SA, from the metadata server.

    The metadata server is only reachable on GCP; locally this raises, which is
    correct — a local process must not be able to silently start production Job
    executions labelled as scheduled.
    """
    response = httpx.get(
        _METADATA_TOKEN_URL,
        headers={"Metadata-Flavor": "Google"},
        timeout=10.0,
    )
    response.raise_for_status()
    return str(response.json()["access_token"])


def _run_job_via_rest() -> str:
    """POST the ``:run`` call as the runtime SA. Returns the execution name.

    REST with a metadata-server token rather than a client library: the request
    is one POST, and this is byte-for-byte the call shape that was proven to
    start executions when made with this SA's token — keeping it identical
    keeps the STOPPED-DEPLOY.md evidence applicable to this code path.
    """
    project = os.environ["BARAZA_PROJECT_ID"]
    region = os.environ.get("BARAZA_JOB_REGION", "us-central1")
    job = os.environ.get("BARAZA_RECONCILE_JOB", "baraza-reconcile")

    response = httpx.post(
        run_url(project, region, job),
        headers={
            "Authorization": f"Bearer {_access_token()}",
            "Content-Type": "application/json",
        },
        content=json.dumps(override_body()),
        timeout=30.0,
    )
    response.raise_for_status()
    return str(response.json().get("name", ""))


def create_app(run_job: RunJob | None = None) -> FastAPI:
    """Build the app. ``run_job`` is injectable so tests never touch GCP."""
    execute = run_job or _run_job_via_rest
    application = FastAPI(title="baraza-trigger", docs_url=None, redoc_url=None)

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "baraza-trigger"}

    @application.post("/run-reconcile")
    def run_reconcile() -> JSONResponse:
        try:
            execution = execute()
        except Exception as exc:  # noqa: BLE001 - the Scheduler retry boundary
            # 502, not 500-and-a-stack-trace: the failure is downstream of this
            # service, and a non-2xx is precisely what tells Scheduler to apply
            # its retry policy instead of recording a green night that never ran.
            return JSONResponse(
                status_code=502,
                content={
                    "started": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
        return JSONResponse(
            status_code=200,
            content={
                "started": True,
                "execution": execution,
                "trigger": "cloud-scheduler",
            },
        )

    return application


app = create_app()
"""The uvicorn target: ``baraza.reconcile.trigger_service:app`` via
``deploy/entrypoint-service.sh``'s ``BARAZA_APP`` switch — same image as the
other services, so the trigger can never run a different build of the code it
triggers."""
