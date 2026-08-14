"""The fold and the append-only store.

Three properties, each of which is a decision the fold could plausibly have made
the other way, and each of which would be invisible in a demo if it were wrong.

**Re-appending is a no-op, not a duplicate.** Event IDs are content hashes, so a
retried ingestion Job re-derives the same IDs and the second write collides. That
is what makes the nightly Job safe to retry, which is what makes the schedule
safe to run unattended.

**An unhandled event type raises.** Skipping it would let a schema change
produce a quietly incomplete graph — the exact failure an append-only log exists
to prevent. The fold is allowed to be unable to render a state; it is not
allowed to render a wrong one.

**A malformed visibility event tightens.** Fail-closed means the error path can
only ever narrow access, never widen it.
"""

from __future__ import annotations

import json
from enum import StrEnum

import pytest

from baraza.fold.graph import UnknownEventType, fold
from baraza.fold.store import JsonlEventStore
from baraza.schema.claim import Tier
from baraza.schema.event import Event
from baraza.schema.visibility import Visibility
from baraza_testkit import (
    asserted,
    claim,
    committed,
    heartbeat,
    ms,
    rejected,
    visibility_set,
)

T0 = ms("2026-04-01T00:00:00Z")


class _FutureEventType(StrEnum):
    """An event type a later schema change added and forgot to teach the fold."""

    CLAIM_ANNOTATED = "claim.annotated"


class TestIdempotence:
    def test_the_same_claim_asserted_twice_yields_one_event_id(self):
        c = claim()
        first = asserted(c, at=T0)
        again = asserted(c, at=T0)
        assert first.event_id == again.event_id

    def test_re_appending_folds_to_the_same_state(self):
        c = claim()
        once = fold([asserted(c, at=T0)])
        twice = fold([asserted(c, at=T0), asserted(c, at=T0)])

        assert once.fingerprint() == twice.fingerprint()
        assert len(twice.claims) == 1

    def test_re_asserting_does_not_reset_a_promoted_claim(self):
        """The retry path must not walk a committed claim back to pending."""
        c = claim()
        state = fold(
            [
                asserted(c, at=T0),
                committed(c.claim_id, at=T0 + 1_000),
                asserted(c, at=T0),  # the retry
            ]
        )
        assert state.claims[c.claim_id].tier is Tier.COMMITTED

    def test_the_store_reports_the_duplicate_rather_than_writing_it(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        event = asserted(claim(), at=T0)

        assert store.append(event) is True
        assert store.append(event) is False
        assert len(store.read_all()) == 1

    def test_a_fresh_store_object_sees_the_same_duplicate(self, tmp_path):
        """Idempotence has to survive process restart, not just object lifetime —
        a retried Cloud Run Job is a new process."""
        path = tmp_path / "events.jsonl"
        event = asserted(claim(), at=T0)
        assert JsonlEventStore(path).append(event) is True
        assert JsonlEventStore(path).append(event) is False
        assert len(JsonlEventStore(path).read_all()) == 1

    def test_the_store_exposes_no_mutation_surface(self):
        for forbidden in ("update", "delete", "overwrite", "set"):
            assert not hasattr(JsonlEventStore, forbidden)


class TestUnknownEventType:
    def test_the_fold_raises_rather_than_skipping(self):
        stray = Event(
            event_id="evt_futureschemachange0000000000000",
            event_type=_FutureEventType.CLAIM_ANNOTATED,
            occurred_at=T0,
            payload={"claim_id": "clm_whatever"},
        )
        with pytest.raises(UnknownEventType) as caught:
            fold([stray])
        assert "claim.annotated" in str(caught.value)

    def test_the_stray_event_does_not_silently_shrink_the_graph(self):
        """The failure mode being prevented: a fold that returns a state which
        looks fine and is missing something."""
        c = claim()
        stray = Event(
            event_id="evt_futureschemachange0000000000000",
            event_type=_FutureEventType.CLAIM_ANNOTATED,
            occurred_at=T0 + 5_000,
            payload={},
        )
        with pytest.raises(UnknownEventType):
            fold([asserted(c, at=T0), stray])

    def test_an_unknown_type_cannot_even_be_rehydrated(self):
        payload = asserted(claim(), at=T0).to_dict()
        payload["event_type"] = "claim.annotated"
        with pytest.raises(ValueError):
            Event.from_dict(payload)


class TestVisibilityEvents:
    def _state(self, raw_value):
        c = claim(visibility=Visibility.ORG)
        return c, fold(
            [
                asserted(c, at=T0),
                visibility_set(c.claim_id, raw_value, at=T0 + 1_000),
            ]
        )

    def test_a_garbage_value_fails_closed_to_private(self):
        c, state = self._state("everyone-obviously")
        assert state.claims[c.claim_id].visibility is Visibility.PRIVATE

    def test_a_null_value_fails_closed_to_private(self):
        c, state = self._state(None)
        assert state.claims[c.claim_id].visibility is Visibility.PRIVATE

    def test_a_numeric_value_fails_closed_to_private(self):
        c, state = self._state(3)
        assert state.claims[c.claim_id].visibility is Visibility.PRIVATE

    def test_a_legal_value_is_applied(self):
        c, state = self._state(Visibility.SUCCESSOR)
        assert state.claims[c.claim_id].visibility is Visibility.SUCCESSOR

    def test_the_error_path_can_only_narrow(self):
        """Fail-closed stated as the property rather than as three cases: a
        malformed event never leaves the claim more readable than it was."""
        c = claim(visibility=Visibility.PUBLIC)
        state = fold(
            [
                asserted(c, at=T0),
                visibility_set(c.claim_id, "public-plus-plus", at=T0 + 1_000),
            ]
        )
        assert state.claims[c.claim_id].visibility is Visibility.PRIVATE

    def test_a_visibility_event_for_an_unknown_claim_is_ignored(self):
        state = fold([visibility_set("clm_never_asserted", Visibility.ORG, at=T0)])
        assert state.claims == {}


class TestOrdering:
    def test_events_sharing_a_millisecond_fold_deterministically(self):
        """The tiebreaker is the event ID, so two events stamped identically
        cannot fold differently depending on which arrived first."""
        a = claim(quote="first", locator="p.1")
        b = claim(quote="second", locator="p.2")
        forward = fold([asserted(a, at=T0), asserted(b, at=T0)])
        backward = fold([asserted(b, at=T0), asserted(a, at=T0)])
        assert forward.fingerprint() == backward.fingerprint()

    def test_last_write_wins_on_instant_not_on_arrival(self):
        c = claim()
        later_first = fold(
            [
                asserted(c, at=T0),
                rejected(c.claim_id, at=T0 + 2_000),
                committed(c.claim_id, at=T0 + 1_000),
            ]
        )
        assert later_first.claims[c.claim_id].tier is Tier.REJECTED


class TestAccounting:
    def test_heartbeats_are_kept_apart_from_claims(self):
        """A scheduled run is never counted as organic activity, so it does not
        land anywhere a claim count is read from."""
        c = claim()
        state = fold([asserted(c, at=T0), heartbeat(T0 + 1_000)])

        assert state.heartbeats == [T0 + 1_000]
        assert len(state.claims) == 1
        assert len(state.retrievable_claims()) == 1

    def test_the_store_counts_scheduled_runs_separately(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        store.append(asserted(claim(), at=T0))
        store.append(heartbeat(T0 + 1_000))
        store.append(heartbeat(T0 + 2_000))

        assert store.count_scheduled() == 2
        assert len(store.read_all()) == 3


class TestTornWrites:
    def test_a_partial_final_line_is_skipped_not_fatal(self, tmp_path):
        """The signature of a process killed mid-write. The event was never
        durably committed, so dropping it is correct — and the kill-survival
        test depends on this being a skip rather than a crash."""
        path = tmp_path / "events.jsonl"
        store = JsonlEventStore(path)
        store.append(asserted(claim(), at=T0))

        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"event_id": "evt_partial", "event_ty')

        assert len(JsonlEventStore(path).read_all()) == 1

    def test_a_torn_line_that_is_not_last_is_fatal(self, tmp_path):
        """Corruption in the middle of the log is not a kill signature, and
        accepting it would mean folding a log with a hole in it."""
        path = tmp_path / "events.jsonl"
        store = JsonlEventStore(path)
        store.append(asserted(claim(), at=T0))

        with open(path, "a", encoding="utf-8") as handle:
            handle.write('{"event_id": "evt_partial", "event_ty\n')
            handle.write(json.dumps(heartbeat(T0 + 1_000).to_dict()) + "\n")

        with pytest.raises(json.JSONDecodeError):
            JsonlEventStore(path).read_all()
