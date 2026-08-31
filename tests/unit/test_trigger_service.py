"""The trigger service — Scheduler's OIDC target that starts the reconcile Job.

Two properties matter and both are honesty properties:

* the container override that labels a run ``cloud-scheduler`` is a constant
  of this code path — the only one in the repository — so the ``scheduled``
  flag downstream means what it says;
* a failure to start the Job surfaces as a non-2xx, because a 200 on a night
  that never ran would give Scheduler a green history over an empty log.

Everything runs against the injected fake; nothing here reaches GCP or the
metadata server.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from baraza.reconcile.trigger_service import create_app, override_body, run_url


def _client(run_job=None) -> TestClient:
    return TestClient(create_app(run_job=run_job))


class TestHealth:
    def test_healthz_is_reachable_without_touching_the_jobs_api(self):
        calls = []
        client = _client(run_job=lambda: calls.append(1) or "never")

        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert calls == []


class TestRunReconcile:
    def test_a_post_starts_exactly_one_execution(self):
        calls = []

        def run_job() -> str:
            calls.append(1)
            return "projects/p/locations/r/jobs/baraza-reconcile/executions/x-1"

        response = _client(run_job).post("/run-reconcile")

        assert response.status_code == 200
        assert len(calls) == 1
        body = response.json()
        assert body["started"] is True
        assert body["execution"].endswith("/executions/x-1")
        assert body["trigger"] == "cloud-scheduler"

    def test_a_jobs_api_failure_is_a_non_2xx_so_scheduler_retries(self):
        def run_job() -> str:
            raise RuntimeError("run.googleapis.com said 503")

        response = _client(run_job).post("/run-reconcile")

        assert response.status_code == 502
        body = response.json()
        assert body["started"] is False
        assert "503" in body["error"]

    def test_get_on_the_run_endpoint_is_rejected(self):
        # Scheduler POSTs; anything else is a mistake, not a trigger.
        response = _client(lambda: "never").get("/run-reconcile")
        assert response.status_code == 405


class TestOverrideBody:
    def test_the_override_labels_the_run_as_scheduler_triggered(self):
        body = override_body()
        env = body["overrides"]["containerOverrides"][0]["env"]
        assert env == [{"name": "BARAZA_RUN_TRIGGER", "value": "cloud-scheduler"}]

    def test_each_caller_gets_a_fresh_dict(self):
        # A shared mutable constant would let one handler's mutation relabel
        # every future run. The function contract is a fresh copy per call.
        first = override_body()
        first["overrides"]["containerOverrides"][0]["env"][0]["value"] = "manual"
        assert (
            override_body()["overrides"]["containerOverrides"][0]["env"][0]["value"]
            == "cloud-scheduler"
        )

    def test_no_other_env_rides_along(self):
        # The override is the label and nothing else. Anything more would be a
        # second configuration channel for the Job hiding inside the trigger.
        env = override_body()["overrides"]["containerOverrides"][0]["env"]
        assert len(env) == 1


class TestRunUrl:
    def test_composes_the_v2_run_endpoint(self):
        assert run_url("p-1", "us-central1", "baraza-reconcile") == (
            "https://run.googleapis.com/v2/projects/p-1/locations/us-central1"
            "/jobs/baraza-reconcile:run"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
