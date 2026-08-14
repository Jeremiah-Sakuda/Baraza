"""GATE G3 — an unreadable claim can be counted but never quoted.

``tests/unit/test_visibility.py`` attacks the predicate itself. This module
attacks the other end: the six read paths AGENTS.md names — divergence
detection, the ledger, the agenda, the interviewer, the graph view, and
successor mode — asserting that each of them routes through ``readable_by``
rather than around it.

The distinction the tests are looking for is always the same one, and it is
asymmetric on purpose. The count of disagreements must stay honest even when
their contents cannot be shown, because a boundary that silently shrinks the
ledger makes the visibility choice look free when it is not. So: the row is
there, the agenda slot is there, the withheld count is there — and the text is
not, on any surface, in any prompt, in any log line.

Off the demo path means these fixtures never go near the replay corpus or the
cassettes. Every claim here is built for this test and the private one carries a
string that would be unmistakable if it ever appeared where it should not.
"""

from __future__ import annotations

import json

from baraza.fold.graph import fold
from baraza.interview.interviewer import Interviewer
from baraza.reconcile.agenda import AgendaGenerator
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.contradiction import Contradiction
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

T0 = ms("2026-04-01T00:00:00Z")

# If this string ever reaches a surface it should not, the test that finds it
# will not have to explain what went wrong.
SECRET = "LEAKED-PRIVATE-TESTIMONY-MARKER"

AGENDA_RESPONSE = json.dumps(
    {"question": "Which ceiling did you use?", "why_it_matters": "It gates spending."}
)


def _scenario():
    """One disagreement: a public record against a private piece of testimony."""
    public_side = claim(
        quote="The treasurer may sign for amounts up to five hundred.",
        object_literal="500",
        source_id="src:constitution-scan",
        locator="p.4 ¶2",
        valid_from="2025-07-01T00:00:00Z",
    )
    private_side = claim(
        quote=f"In practice the chair signed everything. {SECRET}",
        object_literal=SECRET,
        source_id="interview:ses_prior",
        locator="turn:t-9",
        valid_from="2025-07-01T00:00:00Z",
    )
    contradiction = Contradiction.create(
        subject_id="ent:treasurer",
        predicate_hint="signing authority",
        claim_ids=[public_side.claim_id, private_side.claim_id],
        detected_at="2026-04-03T14:31:00Z",
        confidence=0.9,
        rationale=f"The record says 500; testimony says otherwise. {SECRET}",
    )

    events = []
    for index, (c, visibility) in enumerate(
        ((public_side, Visibility.PUBLIC), (private_side, Visibility.PRIVATE))
    ):
        at = T0 + index * 10_000
        events.extend(
            [
                asserted(c, at=at),
                committed(c.claim_id, at=at + 100),
                visibility_set(c.claim_id, visibility, at=at + 200),
            ]
        )
    events.append(detected(contradiction, at=T0 + 30_000))
    return fold(events), contradiction, public_side, private_side


class TestTheLedger:
    def test_the_row_survives_for_an_audience_that_cannot_read_a_side(self):
        state, contradiction, _, _ = _scenario()
        rows = DisputedLedger(state).rows(Audience.ORG)

        assert len(rows) == 1
        assert rows[0].contradiction_id == contradiction.contradiction_id
        assert rows[0].rendered.fully_readable is False

    def test_no_rendered_line_carries_the_withheld_text(self):
        state, _, _, _ = _scenario()
        rows = DisputedLedger(state).rows(Audience.ORG)
        blob = "\n".join(rows[0].render_lines())

        assert SECRET not in blob
        assert "counted, not quoted" in blob

    def test_the_rationale_itself_is_withheld_when_a_side_is(self):
        """The adjudicator's rationale quotes both sides by construction, so it
        is as sensitive as the claim that produced it."""
        state, _, _, _ = _scenario()
        rows = DisputedLedger(state).rows(Audience.ORG)
        assert SECRET not in rows[0].rendered.summary

    def test_the_summary_counts_are_honest_about_what_is_hidden(self):
        state, _, _, _ = _scenario()
        summary = DisputedLedger(state).summary(Audience.ORG)

        assert summary["open_total"] == 1
        assert summary["redacted"] == 1
        assert summary["fully_readable"] == 0

    def test_the_owner_sees_the_same_row_with_its_text(self):
        """The control: redaction is per audience, not a blanket suppression."""
        state, _, _, _ = _scenario()
        rows = DisputedLedger(state).rows(Audience.OWNER)

        assert rows[0].rendered.fully_readable is True
        assert SECRET in "\n".join(rows[0].render_lines())


class TestTheAgenda:
    def test_the_item_is_downgraded_not_dropped(self):
        """Dropping it would let the boundary silently shrink the agenda, which
        would make the visibility choice look free."""
        state, contradiction, _, _ = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        agenda = AgendaGenerator(client).generate(state, audience=Audience.ORG)

        assert len(agenda.items) == 1
        item = agenda.items[0]
        assert item.contradiction_id == contradiction.contradiction_id
        assert item.fully_readable is False

    def test_the_downgraded_question_carries_no_quotes_and_no_citations(self):
        state, _, _, _ = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        agenda = AgendaGenerator(client).generate(state, audience=Audience.ORG)
        item = agenda.items[0]

        assert SECRET not in item.question
        assert SECRET not in item.why_it_matters
        assert item.cited_claim_ids == []

    def test_no_model_call_is_made_for_a_redacted_item(self):
        """The withheld text must not reach the model either. A generated
        question is an output, but a prompt is a disclosure."""
        state, _, _, _ = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        AgendaGenerator(client).generate(state, audience=Audience.ORG)

        assert client.calls == []

    def test_the_agenda_says_out_loud_how_much_it_downgraded(self):
        state, _, _, _ = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        agenda = AgendaGenerator(client).generate(state, audience=Audience.ORG)

        described = "\n".join(agenda.describe())
        assert "1 item(s) downgraded" in described
        assert SECRET not in described


class TestTheInterviewer:
    def test_divergence_never_quotes_an_unreadable_claim(self):
        """The leak this prevents is specific: contradicting someone by reading
        them a private record discloses the record."""
        state, _, _, private_side = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        agenda = AgendaGenerator(client).generate(state, audience=Audience.OWNER)
        item = agenda.items[0]
        assert private_side.claim_id in item.cited_claim_ids

        # The interviewer is now talking to someone who may not read that side.
        interviewer_client = FakeLLMClient(
            {
                "divergence.v1": json.dumps(
                    {
                        "divergence": {
                            "claim_id": private_side.claim_id,
                            "confidence": 0.9,
                            "rationale": "differs",
                        }
                    }
                )
            }
        )
        interviewer = Interviewer(interviewer_client, state, audience=Audience.ORG)
        finding = interviewer.check_divergence(
            "We always used the five hundred ceiling, every single time.", item
        )

        assert finding is None
        # And the claim never entered the prompt in the first place.
        for call in interviewer_client.calls:
            assert SECRET not in call.prompt

    def test_a_readable_side_still_produces_the_divergence_moment(self):
        """The control. If the boundary suppressed everything, the product's
        headline moment would never fire and the test above would be vacuous."""
        state, _, public_side, _ = _scenario()
        client = FakeLLMClient({"agenda_item.v1": AGENDA_RESPONSE})
        agenda = AgendaGenerator(client).generate(state, audience=Audience.OWNER)
        item = agenda.items[0]

        interviewer_client = FakeLLMClient(
            {
                "divergence.v1": json.dumps(
                    {
                        "divergence": {
                            "claim_id": public_side.claim_id,
                            "confidence": 0.8,
                            "rationale": "The record gives a different ceiling.",
                        }
                    }
                )
            }
        )
        finding = Interviewer(
            interviewer_client, state, audience=Audience.ORG
        ).check_divergence(
            "The ceiling was two fifty for the whole year, I am sure of it.", item
        )

        assert finding is not None
        assert finding.conflicting_claim_id == public_side.claim_id
        assert SECRET not in finding.render()


class TestTheGraphView:
    def test_readable_claims_is_committed_and_readable_and_nothing_else(self):
        state, _, public_side, private_side = _scenario()

        successor_view = state.readable_claims(Audience.SUCCESSOR)
        assert [c.claim_id for c in successor_view] == [public_side.claim_id]

        owner_view = state.readable_claims(Audience.OWNER)
        assert {c.claim_id for c in owner_view} == {
            public_side.claim_id,
            private_side.claim_id,
        }

    def test_the_retrieval_pool_is_a_different_axis_from_visibility(self):
        """The reconciler must be able to count what it may not quote, which is
        only possible if retraction and visibility are separate gates."""
        state, _, _, private_side = _scenario()

        assert private_side.claim_id in {
            c.claim_id for c in state.retrievable_claims()
        }
        assert private_side.claim_id not in {
            c.claim_id for c in state.readable_claims(Audience.ORG)
        }
