"""BAR-321 — the nightly reconciler's work pool, and the bug that emptied it.

The flagship autonomous behaviour of this system is a Cloud Run Job that wakes
up at 3am, looks at the claims nobody has adjudicated yet, and appends what it
finds. For that to be a workflow rather than a diagram, the set of claims it
looks at has to be non-empty on night two.

It was not. ``run_real`` selected its work with::

    fresh = [c for c in pool if c.observed_at > previous_heartbeat]

``previous_heartbeat`` is a wall-clock instant — last night. ``observed_at`` is
the instant the **document was authored**, which ``ingest/pipeline.py`` declares
from the corpus manifest precisely so that it is *not* ingest time::

    ``observed_at`` is declared in the corpus manifest rather than read from
    the filesystem: a file's mtime records when it was copied onto this
    machine, which has nothing to do with when the minutes were taken.

The corpus runs from 2016. Every claim in it is older than every heartbeat, so
once any heartbeat existed the comparison selected the empty set on every
subsequent night, forever. The job exited 0, reported success, made zero model
calls and found zero contradictions. Nothing failed; nothing happened.

The fix is not a better timestamp. It is to stop inferring: the reconciler now
appends a ``claim.adjudicated`` event for each claim it examines, and its pool
is ``retrievable_claims() - adjudicated_claim_ids``. A set difference over
recorded facts cannot go quietly empty, and it is the same ethic as the rest of
the system — the log is the truth, and nothing about the world is deduced from
a field that means something else.

These tests use the scripted fake client, so nothing here touches Vertex.
"""

from __future__ import annotations

import json

from baraza.fold.graph import fold
from baraza.fold.store import JsonlEventStore
from baraza.reconcile.job import resolve_scheduled, run_real, run_stub
from baraza.schema.event import EventType
from baraza_testkit import FakeLLMClient, asserted, claim, ms

NO_CONTRADICTIONS = json.dumps({"contradictions": []})

# Cloud Scheduler run IDs carry the scheduled instant; the job derives its
# heartbeat from the ID rather than the wall clock so retries are idempotent.
NIGHT_ONE = "reconcile-1780000000000"
NIGHT_TWO = "reconcile-1780086400000"
NIGHT_THREE = "reconcile-1780172800000"


def _client() -> FakeLLMClient:
    return FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})


def _store(tmp_path, name: str = "events.jsonl") -> JsonlEventStore:
    return JsonlEventStore(tmp_path / name)


def _archival_claim(**overrides):
    """A claim from a document authored in 2016 — i.e. most of the corpus."""
    defaults = dict(observed_at="2016-09-14T00:00:00Z", locator="p.1 ¶1")
    defaults.update(overrides)
    return claim(**defaults)


class TestTheWorkPoolIsReadFromTheLog:
    """The regression. This is the test whose absence let the bug ship."""

    def test_a_claim_authored_in_2016_and_asserted_tonight_is_examined(
        self, tmp_path
    ):
        """The exact defect: old document, new assertion, previous heartbeat.

        Under the old ``observed_at > previous_heartbeat`` filter this claim was
        invisible to the reconciler forever, because a 2016 document is older
        than last night no matter when it was ingested.
        """
        store = _store(tmp_path)
        run_stub(store, run_id=NIGHT_ONE)  # a heartbeat now exists

        # Two claims about the same subject, so there is a real block to
        # adjudicate and the model is actually consulted — a pool that is
        # non-empty but never reaches the detector would be no better.
        old = _archival_claim()
        older = _archival_claim(
            observed_at="2018-03-02T00:00:00Z",
            locator="p.4 ¶2",
            quote="The treasurer may sign for amounts up to two thousand.",
            object_literal="2000",
        )
        # Asserted *after* last night's heartbeat, authored years before it.
        store.append(asserted(old, at=ms("2026-06-05T04:00:00Z")))
        store.append(asserted(older, at=ms("2026-06-05T04:00:01Z")))

        latest_heartbeat = max(fold(store.read_all()).heartbeats)
        assert old.observed_at < latest_heartbeat
        assert older.observed_at < latest_heartbeat

        result = run_real(
            store,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert result.claims_examined == 2
        # One bounded call per claim examined, per BAR-320. Zero here was the bug.
        assert result.model_calls == 2
        assert result.claims_adjudicated == 2

    def test_a_second_night_does_not_re_examine_what_the_first_examined(
        self, tmp_path
    ):
        """The property the broken filter was reaching for, now actually held.

        Bounded nightly cost is the point of on-write detection. Getting a
        non-empty pool by removing the filter entirely would be a regression in
        the other direction.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))

        first = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )
        second = run_real(
            store,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert first.claims_examined == 1
        assert second.claims_examined == 0
        assert second.model_calls == 0

    def test_a_claim_arriving_after_an_examined_night_is_picked_up(self, tmp_path):
        """Night three sees only the claim night two did not have."""
        store = _store(tmp_path)
        store.append(asserted(_archival_claim(locator="p.1 ¶1")))
        run_real(
            store,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        store.append(asserted(_archival_claim(locator="p.7 ¶3", quote="Quorum is nine.")))
        third = run_real(
            store,
            run_id=NIGHT_THREE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert third.claims_examined == 1

    def test_a_claim_already_carrying_an_adjudication_is_skipped(self, tmp_path):
        """Selection reads the log, not the JobResult of a previous process.

        A fresh store object with no in-memory carryover still skips the claim,
        which is what makes this work across container restarts.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        reopened = _store(tmp_path)
        again = run_real(
            reopened,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert again.claims_examined == 0


class TestAdjudicationIsRecordedNotInferred:
    def test_examining_a_claim_appends_an_adjudication_event(self, tmp_path):
        store = _store(tmp_path)
        subject = _archival_claim()
        store.append(asserted(subject))

        result = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        events = [
            e
            for e in store.read_all()
            if e.event_type is EventType.CLAIM_ADJUDICATED
        ]
        assert len(events) == 1
        assert events[0].payload["claim_id"] == subject.claim_id
        assert events[0].payload["run_id"] == NIGHT_ONE
        assert result.claims_adjudicated == 1

    def test_the_adjudication_is_labelled_as_a_scheduled_run(self, tmp_path):
        """A scheduled append is never counted as organic activity, anywhere.

        ``scheduled`` is passed explicitly. It used to be hardcoded True inside
        the job, so this test passed no matter how the run was started — which
        is exactly why the defect it now guards against went unnoticed.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
            scheduled=True,
        )

        adjudications = [
            e
            for e in store.read_all()
            if e.event_type is EventType.CLAIM_ADJUDICATED
        ]
        assert adjudications and all(e.scheduled for e in adjudications)
        assert all(e.actor == "reconcile-job" for e in adjudications)

    def test_the_fold_reports_adjudicated_claims(self, tmp_path):
        store = _store(tmp_path)
        subject = _archival_claim()
        store.append(asserted(subject))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert fold(store.read_all()).adjudicated_claim_ids == {subject.claim_id}

    def test_a_retracted_claim_is_never_examined(self, tmp_path):
        """Retraction removes a claim from the retrieval pool, so from the work.

        Asserted here because the new selection is a set difference against the
        pool; if the pool ever stopped honouring retraction, the reconciler
        would start spending model calls on claims that no longer exist.
        """
        from baraza_testkit import rejected

        store = _store(tmp_path)
        subject = _archival_claim()
        store.append(asserted(subject))
        store.append(rejected(subject.claim_id, at=ms("2026-06-05T05:00:00Z")))

        result = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        assert result.claims_examined == 0
        assert result.model_calls == 0


class TestRetriesAreIdempotent:
    """Cloud Run Jobs retry. A retried night must not double-count itself."""

    def test_re_running_the_same_run_id_appends_no_second_heartbeat(self, tmp_path):
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))

        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )
        before = len(store.read_all())
        retry = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        heartbeats = fold(store.read_all()).heartbeats
        assert len(heartbeats) == 1
        assert retry.events_appended == 0
        assert len(store.read_all()) == before

    def test_a_retry_that_reaches_the_same_claim_appends_one_adjudication(
        self, tmp_path
    ):
        """Content-addressed IDs make this free: same run, same instant, same ID.

        The retried run examines nothing, because the first attempt's
        adjudication is already in the log.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))

        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        adjudications = [
            e
            for e in store.read_all()
            if e.event_type is EventType.CLAIM_ADJUDICATED
        ]
        assert len(adjudications) == 1


class TestTheDifferentialIsRebuiltFromTheLog:
    """BAR-323 — and the second way the nightly job could report nothing.

    ``run_real`` used to read last night's ledger back from ``out/snapshots/``.
    A Cloud Run Job execution gets a fresh, empty filesystem and ``deploy/``
    mounts no volume, so that directory is empty on every deployed night:
    ``diff_lines`` was ``None`` every time, in the one place BAR-323 is meant to
    produce evidence. It looked fine locally, because a developer's ``out/``
    persists between runs — which is exactly the shape of bug that ships.

    The fix folds the log twice instead of storing anything. Every test here
    passes a **fresh, empty** ``snapshot_dir`` to the second run, standing in for
    the new container, so a regression to reading from disk fails them.
    """

    def _contradicting_adjudicator(self, claim_id: str) -> FakeLLMClient:
        return FakeLLMClient(
            {
                "contradictions.v1": json.dumps(
                    {
                        "contradictions": [
                            {
                                "claim_id": claim_id,
                                "confidence": 0.9,
                                "rationale": (
                                    "Both set a signing threshold for the same "
                                    "unbounded period, at different amounts."
                                ),
                            }
                        ]
                    }
                )
            }
        )

    def test_a_fresh_container_still_produces_a_differential(self, tmp_path):
        """The regression. Night two shares no filesystem with night one."""
        store = _store(tmp_path)
        first = _archival_claim()
        store.append(asserted(first))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        store.append(
            asserted(
                _archival_claim(
                    locator="p.9 ¶2",
                    quote="The treasurer may sign for amounts up to two thousand.",
                    object_literal="2000",
                )
            )
        )

        second_dir = tmp_path / "container-two"
        second = run_real(
            store,
            run_id=NIGHT_TWO,
            client=self._contradicting_adjudicator(first.claim_id),
            snapshot_dir=second_dir,
        )

        # Nothing from night one is reachable on tonight's disk.
        assert list(second_dir.glob("*.json")) == [second_dir / f"{NIGHT_TWO}.json"]
        assert second.diff_lines is not None
        assert second.contradictions_found == 1

    def test_the_differential_names_what_this_run_added(self, tmp_path):
        """Non-``None`` is not enough — an always-empty diff is the same lie."""
        store = _store(tmp_path)
        first = _archival_claim()
        store.append(asserted(first))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        store.append(
            asserted(
                _archival_claim(
                    locator="p.9 ¶2",
                    quote="The treasurer may sign for amounts up to two thousand.",
                    object_literal="2000",
                )
            )
        )
        second = run_real(
            store,
            run_id=NIGHT_TWO,
            client=self._contradicting_adjudicator(first.claim_id),
            snapshot_dir=tmp_path / "container-two",
        )

        text = "\n".join(second.diff_lines)
        assert "contradictions added   1" in text
        assert "contradictions retired 0" in text

    def test_the_baseline_excludes_what_tonight_found(self, tmp_path):
        """The subtle half of the same bug.

        The detector dates a contradiction to the later of its two claims'
        ``observed_at`` — a *document authoring* instant, years below any run
        instant. Stamping the event with it filed tonight's discovery in 2016,
        which put it on the wrong side of the prefix cut and would have made the
        differential permanently empty rather than permanently ``None``.
        """
        store = _store(tmp_path)
        first = _archival_claim()
        store.append(asserted(first))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        store.append(
            asserted(
                _archival_claim(
                    locator="p.9 ¶2",
                    quote="The treasurer may sign for amounts up to two thousand.",
                    object_literal="2000",
                )
            )
        )
        run_real(
            store,
            run_id=NIGHT_TWO,
            client=self._contradicting_adjudicator(first.claim_id),
            snapshot_dir=tmp_path / "container-two",
        )

        found = [
            e
            for e in store.read_all()
            if e.event_type is EventType.CONTRADICTION_DETECTED
        ]
        assert len(found) == 1
        # Filed under the night that found it, not the year the paper was written.
        night_two_instant = max(fold(store.read_all()).heartbeats)
        assert found[0].occurred_at == night_two_instant
        assert found[0].payload["contradiction"]["detected_at"] < found[0].occurred_at

    def test_the_first_night_ever_has_no_differential(self, tmp_path):
        """``None`` is the honest answer when there is nothing to compare to.

        An empty baseline would render night one as a night on which the agent
        looked and found nothing, which is the opposite of what happened.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))

        first = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        assert first.diff_lines is None

    def test_a_retry_diffs_against_last_night_not_against_itself(self, tmp_path):
        """Heartbeat IDs are content-addressed, so a retry meets its own.

        Without excluding the current run's heartbeat, the retried run would
        take its baseline from tonight and report "nothing changed" on exactly
        the nights where the first attempt failed part-way.
        """
        store = _store(tmp_path)
        first = _archival_claim()
        store.append(asserted(first))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        store.append(
            asserted(
                _archival_claim(
                    locator="p.9 ¶2",
                    quote="The treasurer may sign for amounts up to two thousand.",
                    object_literal="2000",
                )
            )
        )
        adjudicator = self._contradicting_adjudicator(first.claim_id)
        run_real(
            store,
            run_id=NIGHT_TWO,
            client=adjudicator,
            snapshot_dir=tmp_path / "container-two",
        )
        retry = run_real(
            store,
            run_id=NIGHT_TWO,
            client=adjudicator,
            snapshot_dir=tmp_path / "container-two-retry",
        )

        assert retry.diff_lines is not None
        # Still measured against night one, so the contradiction the first
        # attempt appended is still reported as this night's work.
        text = "\n".join(retry.diff_lines)
        assert f"{NIGHT_ONE} → {NIGHT_TWO}" in text
        assert "contradictions added   1" in text

    def test_the_rebuilt_baseline_is_labelled_from_the_prior_heartbeat(
        self, tmp_path
    ):
        """The diff's honesty check has to survive the reconstruction.

        ``is_genuine_overnight`` requires both sides scheduled and most of a day
        apart. Reconstructing the baseline must not quietly assert either — both
        come off the prior heartbeat event.
        """
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
            scheduled=True,
        )
        second = run_real(
            store,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "container-two",
            scheduled=True,
        )

        text = "\n".join(second.diff_lines)
        assert f"differential ledger: {NIGHT_ONE} → {NIGHT_TWO}" in text
        assert "elapsed              1.0 day(s)" in text
        assert "both runs scheduled  True" in text
        assert "NOT a genuine overnight differential" not in text

    def test_an_unscheduled_prior_run_is_not_dressed_up_as_overnight(
        self, tmp_path
    ):
        """A hand-run baseline must fail the honesty check, not pass it."""
        from baraza_testkit import heartbeat

        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        store.append(heartbeat(ms("2026-05-28T04:26:40Z"), scheduled=False))

        result = run_real(
            store,
            run_id=NIGHT_TWO,
            client=_client(),
            snapshot_dir=tmp_path / "container-two",
        )

        text = "\n".join(result.diff_lines)
        assert "both runs scheduled  False" in text
        assert "NOT a genuine overnight differential" in text

    def test_the_snapshot_file_is_still_written_for_a_human(self, tmp_path):
        """Kept as an output artifact. Nothing reads it back; it is not evidence."""
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        result = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "container-one",
        )

        assert result.snapshot_path.exists()
        assert json.loads(result.snapshot_path.read_text())["run_id"] == NIGHT_ONE


class TestReporting:
    def test_the_summary_states_what_was_examined_and_recorded(self, tmp_path):
        """A night that did nothing must be legible as a night that did nothing."""
        store = _store(tmp_path)
        store.append(asserted(_archival_claim()))
        result = run_real(
            store,
            run_id=NIGHT_ONE,
            client=_client(),
            snapshot_dir=tmp_path / "snapshots",
        )

        text = "\n".join(result.describe())
        assert "claims examined        1" in text
        assert "adjudications recorded 1" in text


class TestAManualRunIsNeverCountedAsAScheduledOne:
    """The inverse of the rule this project keeps stating.

    "A scheduled job is never counted as organic activity" was enforced. Its
    inverse was not, and the flag sat hardcoded ``True`` on every append the Job
    made. The first live deployment produced the proof: a
    ``gcloud run jobs execute`` wrote ``scheduled=True`` into Firestore while
    the container log two lines above read ``baraza trigger : manual``.

    That direction is the one that costs something. BAR-410 puts a nightly-run
    count on camera, and a handful of manual test executions labelled scheduled
    inflates it silently — the number stays plausible, which is precisely why
    nobody would have questioned it.
    """

    def test_trigger_resolution(self, monkeypatch):
        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "cloud-scheduler")
        assert resolve_scheduled() is True

        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "manual")
        assert resolve_scheduled() is False

    def test_an_unset_trigger_resolves_to_manual(self, monkeypatch):
        """Defaulting the other way would let a missing variable inflate the count."""
        monkeypatch.delenv("BARAZA_RUN_TRIGGER", raising=False)
        assert resolve_scheduled() is False

    def test_an_unrecognised_trigger_resolves_to_manual(self, monkeypatch):
        """Anything that is not Cloud Scheduler is manual. Fails toward under-counting."""
        for value in ("", "cron", "github-actions", "scheduler", "true"):
            monkeypatch.setenv("BARAZA_RUN_TRIGGER", value)
            assert resolve_scheduled() is False, f"{value!r} was counted as scheduled"

    def test_a_manual_stub_run_writes_an_unscheduled_heartbeat(self, tmp_path, monkeypatch):
        """The exact defect, reproduced against the real code path."""
        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "manual")
        store = _store(tmp_path)
        run_stub(store, run_id=NIGHT_ONE)

        heartbeats = [
            e for e in store.read_all() if e.event_type is EventType.HEARTBEAT
        ]
        assert len(heartbeats) == 1
        assert heartbeats[0].scheduled is False
        assert heartbeats[0].payload["trigger"] == "manual"

    def test_a_scheduled_stub_run_writes_a_scheduled_heartbeat(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "cloud-scheduler")
        store = _store(tmp_path)
        run_stub(store, run_id=NIGHT_ONE)

        heartbeats = [
            e for e in store.read_all() if e.event_type is EventType.HEARTBEAT
        ]
        assert heartbeats[0].scheduled is True
        assert heartbeats[0].payload["trigger"] == "cloud-scheduler"

    def test_the_nightly_count_excludes_manual_runs(self, tmp_path, monkeypatch):
        """What BAR-410 actually puts on camera.

        Three executions, two of them scheduled. ``count_scheduled`` must say
        two. Under the old hardcoded flag it said three.
        """
        store = _store(tmp_path)

        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "cloud-scheduler")
        run_stub(store, run_id="nightly-1780000000000")
        run_stub(store, run_id="nightly-1780086400000")

        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "manual")
        run_stub(store, run_id="manual-1780172800000")

        assert len([e for e in store.read_all() if e.event_type is EventType.HEARTBEAT]) == 3
        assert store.count_scheduled() == 2
