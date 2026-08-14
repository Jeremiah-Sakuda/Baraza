"""``rejected`` is a tier and it retracts — everywhere, permanently.

The requirement is not "the claim is marked rejected". It is that the claim
leaves **the retrieval pool, the disputed ledger, and every future agenda**, and
does not come back. Three surfaces, so three assertions; one test per surface
would let the tier be honoured in the ledger and forgotten in the agenda, which
is the shape this failure actually takes.

"Permanently" is tested by trying to undo it the two ways a system like this
would accidentally undo it: re-ingesting the source that produced the claim, and
detecting a fresh contradiction that names it. Neither may resurrect it.

The claim stays in the fold as a tombstone. That is deliberate — the log is
auditable and a rejection is part of the history — but every accessor that gates
on ``in_retrieval_pool`` must exclude it.
"""

from __future__ import annotations

import json

from baraza.fold.graph import fold
from baraza.reconcile.agenda import AgendaGenerator
from baraza.reconcile.detect import build_block
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.claim import Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.event import EventType
from baraza.schema.visibility import Audience, Visibility

from baraza_testkit import (
    FakeLLMClient,
    asserted,
    claim,
    committed,
    detected,
    ms,
    rejected,
    visibility_set,
)

T0 = ms("2026-04-01T00:00:00Z")

AGENDA_RESPONSE = json.dumps(
    {
        "question": "The records give two signing ceilings. Which did you use?",
        "why_it_matters": "It decides who could commit the organization's money.",
    }
)


def _disputed_pair():
    from_constitution = claim(
        quote="The treasurer may sign for amounts up to five hundred.",
        object_literal="500",
        source_id="src:constitution-scan",
        locator="p.4 ¶2",
        valid_from="2025-07-01T00:00:00Z",
    )
    from_chat = claim(
        quote="anything over 250 has to go to the chair first",
        object_literal="250",
        source_id="src:chat-export",
        locator="msg:1743689400",
        valid_from="2025-07-01T00:00:00Z",
    )
    contradiction = Contradiction.create(
        subject_id="ent:treasurer",
        predicate_hint="signing authority",
        claim_ids=[from_constitution.claim_id, from_chat.claim_id],
        detected_at="2026-04-03T14:31:00Z",
        confidence=0.82,
        rationale="Two records give different ceilings over the same period.",
    )
    return from_constitution, from_chat, contradiction


def _log(a, b, contradiction):
    """Both claims committed and org-readable, and the disagreement on the ledger."""
    events = []
    for index, c in enumerate((a, b)):
        at = T0 + index * 10_000
        events.extend(
            [
                asserted(c, at=at),
                committed(c.claim_id, at=at + 100),
                visibility_set(c.claim_id, Visibility.ORG, at=at + 200),
            ]
        )
    events.append(detected(contradiction, at=T0 + 30_000))
    return events


def _agenda(state):
    client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
    return AgendaGenerator(client).generate(state, audience=Audience.ORG)


class TestBeforeRetraction:
    """The control. Without it, an empty ledger afterwards proves nothing."""

    def test_the_disagreement_is_live_on_every_surface(self):
        a, b, contradiction = _disputed_pair()
        state = fold(_log(a, b, contradiction))

        assert len(state.retrievable_claims()) == 2
        assert len(state.open_contradictions()) == 1
        assert len(DisputedLedger(state).rows(Audience.ORG)) == 1
        assert len(_agenda(state).items) == 1


class TestRetraction:
    def _retracted(self):
        a, b, contradiction = _disputed_pair()
        events = _log(a, b, contradiction)
        events.append(rejected(a.claim_id, at=T0 + 40_000))
        return a, b, contradiction, fold(events)

    def test_it_leaves_the_retrieval_pool(self):
        a, b, _, state = self._retracted()

        assert state.claims[a.claim_id].tier is Tier.REJECTED
        assert state.claims[a.claim_id].in_retrieval_pool is False
        assert [c.claim_id for c in state.retrievable_claims()] == [b.claim_id]

    def test_it_leaves_the_blocking_pool_so_it_can_never_be_re_detected(self):
        a, b, _, state = self._retracted()
        assert build_block(b, state.claims.values()) == []
        assert build_block(b, state.retrievable_claims()) == []

    def test_it_leaves_the_ledger(self):
        _, _, _, state = self._retracted()

        assert state.open_contradictions() == []
        assert DisputedLedger(state).rows(Audience.ORG) == []
        assert DisputedLedger(state).summary(Audience.ORG)["open_total"] == 0

    def test_it_leaves_the_agenda(self):
        _, _, _, state = self._retracted()
        agenda = _agenda(state)

        assert agenda.items == []
        assert agenda.ledger_open_total == 0

    def test_the_tombstone_stays_in_the_log_for_audit(self):
        """Retraction is not deletion. The log is append-only and the rejection
        is itself part of the history."""
        a, _, _, state = self._retracted()
        assert a.claim_id in state.claims
        assert state.claims[a.claim_id].tier is Tier.REJECTED

    def test_it_is_not_a_visibility_decision(self):
        """A rejected claim is gone for *everyone*, including its own author.
        Conflating the two axes would let OWNER mode quietly resurrect it."""
        a, _, _, state = self._retracted()
        for audience in Audience:
            assert a.claim_id not in {
                c.claim_id for c in state.retrievable_claims()
            }
            assert DisputedLedger(state).rows(audience) == []


class TestPermanence:
    def test_re_ingesting_the_source_does_not_resurrect_it(self):
        """The realistic undo: the nightly Job re-reads the same document and
        re-derives the same content-addressed claim."""
        a, b, contradiction = _disputed_pair()
        events = _log(a, b, contradiction)
        events.append(rejected(a.claim_id, at=T0 + 40_000))
        events.append(asserted(a, at=T0 + 50_000))  # re-ingest, later stamp

        state = fold(events)
        assert state.claims[a.claim_id].tier is Tier.REJECTED
        assert state.open_contradictions() == []
        assert _agenda(state).items == []

    def test_a_fresh_contradiction_naming_it_never_reaches_the_ledger(self):
        """The other realistic undo: detection runs again and finds the rejected
        claim conflicting with something new."""
        a, b, contradiction = _disputed_pair()
        events = _log(a, b, contradiction)
        events.append(rejected(a.claim_id, at=T0 + 40_000))

        newcomer = claim(
            quote="the ceiling was raised to one thousand that spring",
            object_literal="1000",
            source_id="src:minutes-april",
            locator="p.3 ¶4",
            valid_from="2025-07-01T00:00:00Z",
        )
        later = Contradiction.create(
            subject_id="ent:treasurer",
            predicate_hint="signing authority",
            claim_ids=[a.claim_id, newcomer.claim_id],
            detected_at="2026-05-01T09:00:00Z",
            confidence=0.9,
            rationale="A third ceiling for the same period.",
        )
        events.extend(
            [
                asserted(newcomer, at=T0 + 60_000),
                committed(newcomer.claim_id, at=T0 + 60_100),
                visibility_set(newcomer.claim_id, Visibility.ORG, at=T0 + 60_200),
                detected(later, at=T0 + 70_000),
            ]
        )

        state = fold(events)
        assert later.contradiction_id in state.contradictions
        assert state.open_contradictions() == []
        assert _agenda(state).items == []

    def test_the_only_way_back_is_a_human_re_approval(self):
        """The boundary of "permanently", written down rather than left implicit.

        Omission never reinstates: no amount of re-ingestion, re-detection, or
        elapsed time moves the claim back into the pool. What *does* move it is
        a later ``claim.committed`` — the fold is last-write-wins on tier — and
        that event has exactly one writer in the whole system, the approval
        flow, which means reinstatement costs a human decision and leaves its
        own audit record.

        This is asserted rather than assumed because if the fold ever stops
        being last-write-wins, or if a second module learns to emit
        ``claim.committed``, the cost of reinstatement silently changes.
        """
        a, b, contradiction = _disputed_pair()
        events = _log(a, b, contradiction)
        events.append(rejected(a.claim_id, at=T0 + 40_000))
        state = fold(events)
        assert state.claims[a.claim_id].in_retrieval_pool is False

        events.append(committed(a.claim_id, at=T0 + 45_000))
        reinstated = fold(events)
        assert reinstated.claims[a.claim_id].tier is Tier.COMMITTED

        # There is no "reinstate" event type. Nothing can un-reject a claim by
        # meaning to; only the promotion path, doing its ordinary job, can.
        assert "claim.reinstated" not in {member.value for member in EventType}
