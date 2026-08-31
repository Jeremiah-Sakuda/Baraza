"""The Scheduler-facing trigger service, and the true story of the 403.

For sixteen days Cloud Scheduler's calls to the Jobs Admin API failed
PERMISSION_DENIED while every documented grant sat verified in place. The
working theory — recorded in STOPPED-DEPLOY.md at the time and now **disproven** (full postmortem: docs/deploy-postmortem.md) — blamed
Scheduler's OAuth token minting. The real cause only surfaced when this
service's own call failed the same way and returned a response body Scheduler
never showed:

    Permission 'run.jobs.runWithOverrides' denied

``:run`` with a ``containerOverrides`` body requires ``run.jobs.runWithOverrides``
— a *separate* permission from ``run.jobs.run``, and one ``roles/run.invoker``
does not carry. Every diagnostic that "proved the SA could run the Job" had
posted an **empty body**, exercising only ``run.jobs.run``; every real trigger
carried the override. The theory survived because the control and the
experiment differed in the one byte that mattered. Bootstrap now grants the
custom role ``baraza_job_trigger`` (exactly ``run.jobs.run`` +
``run.jobs.runWithOverrides``) on the Job.

The hop is retained on its merits rather than as a workaround: with this
service as the only caller granted the override permission, the
``cloud-scheduler`` label is hard-coded server-side below — a constant no
Scheduler-config edit can spoof — which is a stronger honesty guarantee than a
mutable message body. Scheduler → OIDC → service is also the auth path whose
failures produce readable logs, which is what broke the case.

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
