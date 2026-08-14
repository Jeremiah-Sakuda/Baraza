"""What happens at 3am.

The unattended path is a Cloud Run Job nobody is watching. Before this file
existed the answer to "one transient 503 on chunk 40 of 200" was: the exception
leaves the client, kills the container, Scheduler retries into the same weather,
and the night becomes a hole in the execution history that is this project's
primary evidence of autonomy.

Three layers are asserted here, and the ordering is the design:

**The client retries the failures worth retrying, and only those.** 429/503/504
and transport errors get another attempt. A 403 does not — retrying a missing
IAM binding spends the attempt deadline to arrive at the same answer more
slowly, and then reports a timeout for what was really a permissions bug.

**The pipeline survives a chunk it could not extract.** The failure is named in
the rejection summary, so a run that lost half its chunks cannot be mistaken for
a run that found nothing.

**The job survives a claim it could not adjudicate** — and, critically, does not
record that claim as examined, so the next night retries it. A skip that marked
the claim done would trade a transient failure for a permanent silent gap.

Nothing here sleeps for real: the backoff is exercised through an injected
``sleep`` that records what it was asked to wait.
"""

from __future__ import annotations

import json

import pytest

from baraza.fold.store import JsonlEventStore
from baraza.ingest.pipeline import IngestionPipeline, SourceSpec
from baraza.llm import RetryPolicy, VertexClient, is_retryable
from baraza.reconcile.job import run_real
from baraza.schema.event import EventType
from baraza_testkit import FakeLLMClient, asserted, claim, ms

T0 = ms("2026-04-01T00:00:00Z")


class Transient(RuntimeError):
    """An SDK error carrying an HTTP status, the way google-genai's do."""

    def __init__(self, code: int):
        super().__init__(f"simulated {code}")
        self.code = code


class DeadlineExceeded(RuntimeError):
    """A transport failure with no status code, matched by type name."""


class Recorder:
    """A ``sleep`` that records rather than waits."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


# --------------------------------------------------------- what gets retried


class TestRetryClassification:
    @pytest.mark.parametrize("code", [429, 503, 504])
    def test_transient_statuses_are_retried(self, code):
        assert is_retryable(Transient(code)) is True

    @pytest.mark.parametrize("code", [400, 401, 403, 404, 409, 422, 500, 501])
    def test_everything_else_is_not(self, code):
        """500 is deliberately absent from the retry set.

        A 500 from Vertex on a well-formed request is rare and usually means the
        request itself is the problem; the SDK reports the recoverable cases as
        503/504. Retrying 500 was considered and rejected — it is the status a
        malformed schema comes back as.
        """
        assert is_retryable(Transient(code)) is False

    def test_transport_failures_without_a_status_are_retried_by_name(self):
        assert is_retryable(DeadlineExceeded("no status here")) is True

    def test_an_unrecognised_error_fails_closed(self):
        assert is_retryable(ValueError("something nobody anticipated")) is False


class TestRetryPolicy:
    def test_it_succeeds_on_the_second_attempt_without_the_caller_knowing(self):
        attempts = {"n": 0}

        def flaky():
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise Transient(503)
            return "ok"

        sleep = Recorder()
        policy = RetryPolicy(max_attempts=4, base_seconds=1.0)

        assert policy.run(flaky, describe="probe", sleep=sleep, jitter=lambda: 1.0) == "ok"
        assert attempts["n"] == 2
        assert sleep.waits == [1.0]

    def test_the_backoff_grows_and_is_jittered(self):
        policy = RetryPolicy(base_seconds=1.0, max_delay_seconds=8.0)

        full = [policy.delay_for(n, jitter=1.0) for n in (1, 2, 3, 4, 5)]
        assert full == [1.0, 2.0, 4.0, 8.0, 8.0], "not exponential, or not capped"

        # Full jitter: the delay is a random point in [0, ceiling], which is what
        # keeps a fleet of retrying containers from re-synchronising.
        assert policy.delay_for(3, jitter=0.0) == 0.0
        assert policy.delay_for(3, jitter=0.5) == 2.0

    def test_a_non_retryable_error_is_raised_immediately_and_unwrapped(self):
        sleep = Recorder()

        with pytest.raises(Transient):
            RetryPolicy().run(
                lambda: (_ for _ in ()).throw(Transient(403)),
                describe="probe",
                sleep=sleep,
            )
        assert sleep.waits == [], "a permission error was retried"

    def test_it_gives_up_after_max_attempts(self):
        attempts = {"n": 0}

        def always_503():
            attempts["n"] += 1
            raise Transient(503)

        sleep = Recorder()
        with pytest.raises(RuntimeError, match="failed after 3 attempt"):
            RetryPolicy(max_attempts=3).run(
                always_503, describe="probe", sleep=sleep, jitter=lambda: 1.0
            )
        assert attempts["n"] == 3
        assert len(sleep.waits) == 2

    def test_the_wall_clock_budget_stops_it_before_max_attempts(self):
        """The bound that matters at 3am.

        Ten attempts of exponential backoff can outlive the Job's own attempt
        deadline. The budget is what stops a degraded night from becoming a
        killed one.
        """
        elapsed = {"t": 0.0}
        sleep = Recorder()

        def clock():
            return elapsed["t"]

        def advance(seconds):
            sleep.waits.append(seconds)
            elapsed["t"] += seconds

        with pytest.raises(RuntimeError, match="within 5s"):
            RetryPolicy(max_attempts=10, base_seconds=2.0, budget_seconds=5.0).run(
                lambda: (_ for _ in ()).throw(Transient(429)),
                describe="probe",
                sleep=advance,
                jitter=lambda: 1.0,
                clock=clock,
            )
        assert sum(sleep.waits) <= 5.0


class TestTheClientCarriesThePolicy:
    def test_generate_retries_through_the_policy(self):
        """The wiring, asserted against a stub SDK rather than a live one."""
        calls = {"n": 0}

        class StubModels:
            def generate_content(self, **kwargs):
                calls["n"] += 1
                if calls["n"] < 2:
                    raise Transient(429)
                return type(
                    "R", (), {"text": '{"ok": true}', "usage_metadata": None}
                )()

        sleep = Recorder()
        client = VertexClient(project="p", location="l", sleep=sleep)
        client.retry = RetryPolicy(max_attempts=3, base_seconds=0.0)
        client._client = type("C", (), {"models": StubModels()})()

        response = client.generate(role="fast", prompt="hello")

        assert calls["n"] == 2
        assert response.source == "vertex"

    def test_a_request_timeout_is_configured_at_all(self):
        """An unbounded request is how a wedged connection holds a night open."""
        from baraza.llm import REQUEST_TIMEOUT_SECONDS

        assert 0 < REQUEST_TIMEOUT_SECONDS < 1800, (
            "the per-request timeout must be inside Scheduler's attemptDeadline"
        )


# ------------------------------------------------------ the unattended paths


class FlakyExtractionClient(FakeLLMClient):
    """Raises on the Nth extraction call and behaves on the others."""

    def __init__(self, *args, fail_on: int, error: Exception, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_on = fail_on
        self.error = error

    def generate(self, **kwargs):
        if len(self.calls) + 1 == self.fail_on:
            self.calls.append(None)  # counted, so the next call is not also N
            raise self.error
        return super().generate(**kwargs)


class TestThePipelineSurvivesABadChunk:
    def _sources(self, tmp_path) -> list[SourceSpec]:
        specs = []
        for index in range(3):
            path = tmp_path / f"notes-{index}.md"
            path.write_text(
                f"# Notes {index}\n\nThe treasurer signs for up to {index}00 dollars.\n",
                encoding="utf-8",
            )
            specs.append(
                SourceSpec(
                    path=path,
                    source_id=f"src:notes-{index}",
                    observed_at="2026-04-01T00:00:00Z",
                )
            )
        return specs

    def test_one_failed_chunk_costs_one_chunk(self, tmp_path):
        specs = self._sources(tmp_path)
        client = FlakyExtractionClient(
            {"claims.v1": json.dumps({"claims": []})},
            fail_on=2,
            error=Transient(503),
        )
        pipeline = IngestionPipeline(
            client=client,
            store=JsonlEventStore(tmp_path / "events.jsonl"),
            agent_extraction=False,
        )

        report = pipeline.run(specs)

        assert report.extraction.chunks_processed == 3, "the run stopped early"
        assert report.extraction.call_failures == 1
        assert "extraction-call-failed" in report.extraction.rejection_summary()

    def test_the_loss_is_named_in_the_report_rather_than_implied(self, tmp_path):
        specs = self._sources(tmp_path)
        client = FlakyExtractionClient(
            {"claims.v1": json.dumps({"claims": []})},
            fail_on=1,
            error=Transient(503),
        )
        pipeline = IngestionPipeline(
            client=client,
            store=JsonlEventStore(tmp_path / "events.jsonl"),
            agent_extraction=False,
        )

        rendered = "\n".join(pipeline.run(specs).describe())

        assert "lost to a failed extraction call" in rendered
        assert "extraction-call-failed" in rendered

    def test_a_call_failure_does_not_corrupt_the_rejection_rate(self, tmp_path):
        """A rate that can exceed 100% has stopped being a rate."""
        specs = self._sources(tmp_path)
        client = FlakyExtractionClient(
            {"claims.v1": json.dumps({"claims": []})},
            fail_on=1,
            error=Transient(503),
        )
        pipeline = IngestionPipeline(
            client=client,
            store=JsonlEventStore(tmp_path / "events.jsonl"),
            agent_extraction=False,
        )

        result = pipeline.run(specs).extraction
        assert result.rejection_rate is None or result.rejection_rate <= 1.0


class ExplodingDetectorClient(FakeLLMClient):
    """Raises on every adjudication call."""

    def generate(self, **kwargs):
        self.calls.append(None)
        raise Transient(503)


class TestTheNightlyJobSurvivesABadClaim:
    def _disputed_store(self, tmp_path) -> JsonlEventStore:
        store = JsonlEventStore(tmp_path / "events.jsonl")
        a = claim(quote="up to 500", locator="p.4", valid_from="2025-07-01")
        b = claim(
            quote="over 250 goes to the chair",
            locator="msg:1",
            valid_from="2025-07-01",
        )
        store.append(asserted(a, at=T0))
        store.append(asserted(b, at=T0 + 1_000))
        return store

    def test_the_job_completes_and_says_what_it_skipped(self, tmp_path):
        store = self._disputed_store(tmp_path)

        result = run_real(
            store,
            run_id="run-1774000000000",
            client=ExplodingDetectorClient(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert result.claims_skipped == 2
        assert result.contradictions_found == 0
        rendered = "\n".join(result.describe())
        assert "claims skipped" in rendered
        assert "detection-call-failed" in rendered

    def test_a_skipped_claim_is_not_recorded_as_examined(self, tmp_path):
        """The trade this must never make: a transient failure for a silent gap.

        If a claim the reconciler could not adjudicate were marked
        ``claim.adjudicated``, it would drop out of every future night's pool and
        the disagreement in it would never be found — and the job would report
        success on the way past.
        """
        store = self._disputed_store(tmp_path)

        run_real(
            store,
            run_id="run-1774000000000",
            client=ExplodingDetectorClient(),
            snapshot_dir=tmp_path / "snapshots",
        )

        types_written = {e.event_type for e in store.read_all()}
        assert EventType.CLAIM_ADJUDICATED not in types_written

        # And the proof that this matters: a second run, with a working client,
        # still examines both claims.
        second = run_real(
            store,
            run_id="run-1774086400000",
            client=FakeLLMClient({"contradictions.v1": json.dumps({"contradictions": []})}),
            snapshot_dir=tmp_path / "snapshots",
        )
        assert second.claims_examined == 2
        assert second.claims_skipped == 0

    def test_the_heartbeat_is_still_appended_on_a_degraded_night(self, tmp_path):
        """A night that did degraded work is still a night that ran."""
        store = self._disputed_store(tmp_path)

        run_real(
            store,
            run_id="run-1774000000000",
            client=ExplodingDetectorClient(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert any(e.event_type == EventType.HEARTBEAT for e in store.read_all())
