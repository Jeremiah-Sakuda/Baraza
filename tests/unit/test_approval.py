"""The approval path — the only promoter, and the loop that closes.

Three claims are tested here, in the order they matter.

**Only the approval path emits ``claim.committed``.** Asserted twice, because
the two ways this breaks are different. Structurally: no module outside
``interview/approval.py`` may even reference the event type as a write.
Behaviourally: running extraction, detection, and a full interview turn appends
no promotion. In production the same rule is IAM — the extractor's service
account cannot write ``committed`` at all — and this is the local half of that
guarantee.

**Declining to choose a visibility is a valid outcome and it means private.** An
approver who clicks through without picking must not silently publish.

**Approving retires the question.** ``contradiction.resolved`` drops the
disagreement out of the ledger and out of every future agenda, so the next
interview is shorter than the last. That is asserted as a count going down
across two real agenda generations, not as an event having been emitted.
"""

from __future__ import annotations

import json
from pathlib import Path

from baraza.fold.graph import fold
from baraza.fold.store import JsonlEventStore
from baraza.interview.approval import ApprovalFlow, ApprovalRequest, Decision
from baraza.interview.interviewer import Interviewer
from baraza.interview.session_store import SessionStore
from baraza.reconcile.agenda import AgendaGenerator
from baraza.reconcile.detect import ContradictionDetector
from baraza.schema.claim import Tier
from baraza.schema.contradiction import Contradiction, ContradictionStatus
from baraza.schema.event import EventType
from baraza.schema.session import TurnKind, TurnRole
from baraza.schema.visibility import Audience, Visibility

from baraza_testkit import (
    FakeLLMClient,
    asserted,
    claim,
    committed,
    detected,
    ms,
    visibility_set,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "baraza"

T0 = ms("2026-04-01T00:00:00Z")

AGENDA_RESPONSE = json.dumps(
    {
        "question": "The records give two answers here. Which did you use?",
        "why_it_matters": "It decides who could commit the organization's money.",
    }
)
NO_CONTRADICTIONS = json.dumps({"contradictions": []})
NO_DIVERGENCE = json.dumps({"divergence": None})
NO_FOLLOW_UP = json.dumps({"question": "SETTLED"})


# --------------------------------------------------------- only one promoter


class TestOnlyTheApprovalPathPromotes:
    def test_no_other_module_references_the_promotion_event(self):
        """Structural, because the behavioural test can only cover paths it runs.

        ``schema/event.py`` defines the type and ``fold/graph.py`` reads it.
        Everything else that names it is a writer, and there may be exactly one.
        """
        allowed = {
            Path("schema/event.py"),
            Path("fold/graph.py"),
            Path("interview/approval.py"),
        }
        referencing = {
            path.relative_to(SRC)
            for path in SRC.rglob("*.py")
            if "CLAIM_COMMITTED" in path.read_text(encoding="utf-8")
        }
        assert referencing <= allowed
        assert Path("interview/approval.py") in referencing

    def test_ingest_and_reconcile_packages_cannot_name_it(self):
        for package in ("ingest", "reconcile", "successor"):
            for path in (SRC / package).rglob("*.py"):
                assert "CLAIM_COMMITTED" not in path.read_text(encoding="utf-8")

    def test_detection_appends_no_promotion(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        a = claim(quote="up to 500", locator="p.4", valid_from="2025-07-01")
        b = claim(
            quote="over 250 goes to the chair",
            locator="msg:1",
            valid_from="2025-07-01",
        )
        store.append(asserted(a, at=T0))
        store.append(asserted(b, at=T0 + 1_000))

        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})
        ContradictionDetector(client).detect(b, [a])

        assert _types(store) == {EventType.CLAIM_ASSERTED}

    def test_an_interview_turn_appends_no_promotion(self, tmp_path):
        """The claim minted from testimony arrives pending and private. Only an
        approver moves it, and only an approver chooses who may read it."""
        store = JsonlEventStore(tmp_path / "events.jsonl")
        state, contradiction, a, _ = _disputed_state()
        sessions = SessionStore(store)
        session = sessions.open(persona_id="persona-a", opened_at=T0)

        agenda = AgendaGenerator(
            FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        ).generate(state, audience=Audience.OWNER)

        interviewer = Interviewer(
            FakeLLMClient(
                {"divergence.v1": NO_DIVERGENCE, "follow_up.v1": NO_FOLLOW_UP}
            ),
            state,
        )
        plan = interviewer.opening_turn(agenda, session)
        turn = _turn_from(plan, session, index=1, at=T0 + 60_000)
        sessions.append_turn(turn)

        minted = interviewer.claim_from_answer(
            answer="We used five hundred the whole year, whatever the chat said.",
            item=agenda.items[0],
            session=session,
            turn=turn,
            occurred_at=T0 + 61_000,
        )

        assert minted is not None
        assert minted.tier is Tier.PENDING
        assert minted.visibility is Visibility.PRIVATE
        assert EventType.CLAIM_COMMITTED not in _types(store)


# ---------------------------------------------------------- visibility default


class TestVisibilityDefault:
    def test_declining_to_choose_means_private(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        c = claim()
        store.append(asserted(c, at=T0))

        result = ApprovalFlow(store).submit(
            [ApprovalRequest(claim=c, decision=Decision.APPROVE, visibility=None)],
            occurred_at=T0 + 1_000,
        )

        assert result.visibility_choices[c.claim_id] == Visibility.PRIVATE.value
        state = fold(store.read_all())
        assert state.claims[c.claim_id].visibility is Visibility.PRIVATE
        assert state.claims[c.claim_id].tier is Tier.COMMITTED

    def test_the_choice_is_its_own_auditable_event(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        c = claim()
        store.append(asserted(c, at=T0))

        ApprovalFlow(store).submit(
            [
                ApprovalRequest(
                    claim=c, decision=Decision.APPROVE, visibility=Visibility.SUCCESSOR
                )
            ],
            occurred_at=T0 + 1_000,
        )

        kinds = _types(store)
        assert EventType.CLAIM_VISIBILITY_SET in kinds
        assert EventType.CLAIM_COMMITTED in kinds
        state = fold(store.read_all())
        assert state.claims[c.claim_id].visibility is Visibility.SUCCESSOR

    def test_a_deferred_claim_is_neither_promoted_nor_retracted(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        c = claim()
        store.append(asserted(c, at=T0))

        result = ApprovalFlow(store).submit(
            [ApprovalRequest(claim=c, decision=Decision.DEFER)],
            occurred_at=T0 + 1_000,
        )

        assert result.deferred == [c.claim_id]
        assert result.events_appended == 0
        assert fold(store.read_all()).claims[c.claim_id].tier is Tier.PENDING

    def test_a_rejection_writes_no_visibility_choice(self, tmp_path):
        """There is nothing to decide about who may read a claim that is gone."""
        store = JsonlEventStore(tmp_path / "events.jsonl")
        c = claim()
        store.append(asserted(c, at=T0))

        result = ApprovalFlow(store).submit(
            [
                ApprovalRequest(
                    claim=c, decision=Decision.REJECT, note="not what happened"
                )
            ],
            occurred_at=T0 + 1_000,
        )

        assert result.rejected == [c.claim_id]
        assert result.visibility_choices == {}
        assert EventType.CLAIM_VISIBILITY_SET not in _types(store)


# --------------------------------------------------------------- closed loop


class TestTheLoopCloses:
    def test_approval_emits_contradiction_resolved(self, tmp_path):
        store, state, contradiction, _, _ = _store_with_disputed_state(tmp_path)
        answer = claim(
            quote="We used five hundred all year.",
            source_id="interview:ses_test",
            locator="turn:t-1",
        )
        store.append(asserted(answer, at=T0 + 60_000))

        result = ApprovalFlow(store).submit(
            [
                ApprovalRequest(
                    claim=answer,
                    decision=Decision.APPROVE,
                    visibility=Visibility.ORG,
                    contradiction_id=contradiction.contradiction_id,
                )
            ],
            occurred_at=T0 + 61_000,
            session_id="ses_test",
        )

        assert result.contradictions_resolved == [contradiction.contradiction_id]
        assert EventType.CONTRADICTION_RESOLVED in _types(store)

        after = fold(store.read_all())
        resolved = after.contradictions[contradiction.contradiction_id]
        assert resolved.status is ContradictionStatus.RESOLVED
        assert resolved.resolving_session_id == "ses_test"
        assert after.open_contradictions() == []

    def test_the_next_agenda_is_shorter(self, tmp_path):
        """The property, measured the way the PRD states it: a count going down
        between two real generations, not an event having fired."""
        store, state, first_contradiction, _, _ = _store_with_disputed_state(
            tmp_path, disagreements=2
        )
        generator = AgendaGenerator(FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE}))

        before = generator.generate(fold(store.read_all()), audience=Audience.ORG)
        assert len(before.items) == 2
        assert before.retired_since_last == 0

        answer = claim(
            quote="We used five hundred all year.",
            source_id="interview:ses_test",
            locator="turn:t-1",
        )
        store.append(asserted(answer, at=T0 + 60_000))
        ApprovalFlow(store).submit(
            [
                ApprovalRequest(
                    claim=answer,
                    decision=Decision.APPROVE,
                    visibility=Visibility.ORG,
                    contradiction_id=first_contradiction.contradiction_id,
                )
            ],
            occurred_at=T0 + 61_000,
            session_id="ses_test",
        )

        after = generator.generate(fold(store.read_all()), audience=Audience.ORG)

        assert len(after.items) < len(before.items)
        assert len(after.items) == 1
        assert after.retired_since_last == 1
        assert first_contradiction.contradiction_id not in {
            item.contradiction_id for item in after.items
        }

    def test_nothing_but_an_answer_retires_an_item(self, tmp_path):
        """Deferring is not answering. The item has to come back."""
        store, _, contradiction, a, _ = _store_with_disputed_state(tmp_path)
        generator = AgendaGenerator(FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE}))

        ApprovalFlow(store).submit(
            [ApprovalRequest(claim=a, decision=Decision.DEFER)],
            occurred_at=T0 + 61_000,
        )

        agenda = generator.generate(fold(store.read_all()), audience=Audience.ORG)
        assert [item.contradiction_id for item in agenda.items] == [
            contradiction.contradiction_id
        ]


# ------------------------------------------------------------------ helpers


def _types(store):
    return {event.event_type for event in store.read_all()}


def _turn_from(plan, session, *, index, at):
    from baraza.schema.session import Turn

    return Turn.create(
        session_id=session.session_id,
        index=index,
        role=TurnRole.AGENT,
        kind=plan.kind if plan.kind else TurnKind.AGENDA,
        text=plan.text,
        occurred_at=at,
        agenda_item_id=plan.agenda_item_id,
        contradiction_id=plan.contradiction_id,
        cited_claim_ids=plan.cited_claim_ids,
    )


def _disputed_events(disagreements=1):
    """One or two live disagreements, each between two org-readable claims."""
    events = []
    contradictions = []
    for index in range(disagreements):
        a = claim(
            subject=f"ent:role-{index}",
            hint=f"signing authority {index}",
            quote=f"ceiling was 500 in year {index}",
            object_literal="500",
            source_id="src:constitution-scan",
            locator=f"p.{index}",
            valid_from="2025-07-01T00:00:00Z",
        )
        b = claim(
            subject=f"ent:role-{index}",
            hint=f"signing authority {index}",
            quote=f"ceiling was 250 in year {index}",
            object_literal="250",
            source_id="src:chat-export",
            locator=f"msg:{index}",
            valid_from="2025-07-01T00:00:00Z",
        )
        contradiction = Contradiction.create(
            subject_id=a.subject_id,
            predicate_hint=a.predicate_hint,
            claim_ids=[a.claim_id, b.claim_id],
            detected_at="2026-04-03T14:31:00Z",
            confidence=0.8 - index * 0.1,
            rationale="Two ceilings for one period.",
        )
        contradictions.append((contradiction, a, b))
        for offset, c in enumerate((a, b)):
            at = T0 + index * 20_000 + offset * 1_000
            events.extend(
                [
                    asserted(c, at=at),
                    committed(c.claim_id, at=at + 100),
                    visibility_set(c.claim_id, Visibility.ORG, at=at + 200),
                ]
            )
        events.append(detected(contradiction, at=T0 + index * 20_000 + 5_000))
    return events, contradictions


def _disputed_state(disagreements=1):
    events, contradictions = _disputed_events(disagreements)
    contradiction, a, b = contradictions[0]
    return fold(events), contradiction, a, b


def _store_with_disputed_state(tmp_path, disagreements=1):
    store = JsonlEventStore(tmp_path / "events.jsonl")
    events, contradictions = _disputed_events(disagreements)
    store.append_many(events)
    contradiction, a, b = contradictions[0]
    return store, fold(store.read_all()), contradiction, a, b
