"""The visibility boundary — asserted off the demo path.

The boundary is the product's headline property and the requirement says it must
hold under carelessness rather than under discipline. So these tests do not
exercise the happy path through the interviewer; they attack the predicate
directly with the inputs a careless caller actually produces: a bare string, a
value that is not in the enum, an object that never had the attribute, ``None``.

Every one of those must return ``False``. Not raise — return ``False``. A
boundary that raises can be caught and swallowed by a caller trying to be
robust, and the swallowed exception path is exactly where leaks live.

The lattice is written out pair by pair rather than derived from the same
clearance table the implementation uses. A test that recomputes the
implementation's arithmetic proves the arithmetic is self-consistent and nothing
else; sixteen literal assertions are the only form of this test that can
disagree with a wrong table.
"""

from __future__ import annotations

import json
from dataclasses import asdict

import pytest

from baraza.fold.graph import fold
from baraza.schema.claim import Claim, Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.visibility import (
    Audience,
    Visibility,
    filter_readable,
    readable_by,
    redacted_for,
)
from baraza.successor.librarian import REFUSAL_TEXT, Librarian

from baraza_testkit import FakeLLMClient, asserted, claim, committed, ms, visibility_set

PRIVATE_QUOTE = "The reserve account password was shared with the outgoing chair."
PUBLIC_QUOTE = "The treasurer may sign for amounts up to five hundred."


def _state_with(*specs):
    """Fold a state from (claim, visibility) pairs via the real event path.

    Constructing ``GraphState`` directly would let a test assert against a
    visibility the approval flow could never have produced. Going through
    ``claim.asserted`` → ``claim.committed`` → ``claim.visibility_set`` means
    the fixture is reachable in production.
    """
    base = ms("2026-04-01T00:00:00Z")
    events = []
    for index, (subject_claim, visibility) in enumerate(specs):
        at = base + index * 10_000
        events.append(asserted(subject_claim, at=at))
        events.append(committed(subject_claim.claim_id, at=at + 100))
        events.append(visibility_set(subject_claim.claim_id, visibility, at=at + 200))
    return fold(events)


# ------------------------------------------------------------- default private


class TestDefaultsPrivate:
    def test_a_claim_built_with_no_visibility_is_private(self):
        assert claim(visibility=None).visibility is Visibility.PRIVATE

    def test_a_stored_document_missing_the_field_reads_back_private(self):
        payload = claim().to_dict()
        del payload["visibility"]
        assert Claim.from_dict(payload).visibility is Visibility.PRIVATE

    def test_a_stored_document_with_a_garbage_value_reads_back_private(self):
        payload = claim(visibility=Visibility.PUBLIC).to_dict()
        payload["visibility"] = "everyone-obviously"
        assert Claim.from_dict(payload).visibility is Visibility.PRIVATE


# ------------------------------------------------------- the quote is not open


class TestQuoteIsUnreachable:
    def test_claim_has_no_attribute_named_quote(self):
        subject = claim()
        assert hasattr(subject, "quote") is False

    def test_reading_dot_quote_raises_at_the_access_site(self):
        subject = claim()
        with pytest.raises(AttributeError):
            subject.quote  # noqa: B018 — the raise is the assertion

    def test_quote_for_public_on_a_private_claim_is_none(self):
        subject = claim(quote=PRIVATE_QUOTE, visibility=Visibility.PRIVATE)
        assert subject.quote_for(Audience.PUBLIC) is None

    def test_quote_for_owner_on_a_private_claim_returns_the_text(self):
        subject = claim(quote=PRIVATE_QUOTE, visibility=Visibility.PRIVATE)
        assert subject.quote_for(Audience.OWNER) == PRIVATE_QUOTE

    def test_object_literal_is_gated_by_the_same_predicate(self):
        """The literal can carry the fact even when the quote is withheld, so it
        has to sit behind the same door."""
        subject = claim(
            quote=PRIVATE_QUOTE, object_literal="7 Elm", visibility=Visibility.PRIVATE
        )
        assert subject.object_for(Audience.PUBLIC) is None
        assert subject.object_for(Audience.OWNER) == "7 Elm"

    def test_digest_is_audience_independent_and_leaks_nothing(self):
        subject = claim(quote=PRIVATE_QUOTE, visibility=Visibility.PRIVATE)
        digest = subject.digest()
        assert PRIVATE_QUOTE not in digest
        assert digest == claim(
            quote=PRIVATE_QUOTE, visibility=Visibility.PUBLIC
        ).digest()


# ---------------------------------------------------------------- fails closed


class _NoVisibilityAtAll:
    """What a caller passes when they hand the predicate the wrong object."""


class _GarbageVisibility:
    visibility = "everyone-obviously"


class _NumericVisibility:
    visibility = 3


class TestFailsClosed:
    def test_garbage_visibility_string(self):
        assert readable_by(_GarbageVisibility(), Audience.OWNER) is False

    def test_visibility_of_the_wrong_type(self):
        assert readable_by(_NumericVisibility(), Audience.OWNER) is False

    def test_object_missing_the_attribute_entirely(self):
        assert readable_by(_NoVisibilityAtAll(), Audience.OWNER) is False

    def test_none_as_the_claim(self):
        assert readable_by(None, Audience.OWNER) is False

    def test_garbage_audience_string(self):
        public = claim(visibility=Visibility.PUBLIC)
        assert readable_by(public, "root") is False

    def test_none_as_the_audience(self):
        public = claim(visibility=Visibility.PUBLIC)
        assert readable_by(public, None) is False

    def test_it_returns_false_rather_than_raising(self):
        """The failure mode this prevents: a caller wrapping the predicate in a
        try/except and treating the exception path as 'probably fine'."""
        for bad in (None, object(), _GarbageVisibility(), "a string"):
            assert readable_by(bad, Audience.PUBLIC) is False

    def test_the_serialized_form_is_still_honoured(self):
        """Failing closed must not mean failing closed on everything — a claim
        rehydrated with a legal string value still reads correctly."""

        class _Serialized:
            visibility = "org"

        assert readable_by(_Serialized(), Audience.ORG) is True
        assert readable_by(_Serialized(), Audience.PUBLIC) is False


# -------------------------------------------------------------- the lattice


class TestTheFullLattice:
    """Every (visibility, audience) pair, written out."""

    def _claim(self, visibility: Visibility) -> Claim:
        return claim(visibility=visibility)

    def test_public_claim(self):
        c = self._claim(Visibility.PUBLIC)
        assert readable_by(c, Audience.PUBLIC) is True
        assert readable_by(c, Audience.ORG) is True
        assert readable_by(c, Audience.SUCCESSOR) is True
        assert readable_by(c, Audience.OWNER) is True

    def test_org_claim(self):
        c = self._claim(Visibility.ORG)
        assert readable_by(c, Audience.PUBLIC) is False
        assert readable_by(c, Audience.ORG) is True
        assert readable_by(c, Audience.SUCCESSOR) is True
        assert readable_by(c, Audience.OWNER) is True

    def test_successor_claim(self):
        c = self._claim(Visibility.SUCCESSOR)
        assert readable_by(c, Audience.PUBLIC) is False
        assert readable_by(c, Audience.ORG) is False
        assert readable_by(c, Audience.SUCCESSOR) is True
        assert readable_by(c, Audience.OWNER) is True

    def test_private_claim(self):
        c = self._claim(Visibility.PRIVATE)
        assert readable_by(c, Audience.PUBLIC) is False
        assert readable_by(c, Audience.ORG) is False
        assert readable_by(c, Audience.SUCCESSOR) is False
        assert readable_by(c, Audience.OWNER) is True

    def test_the_public_audience_reads_exactly_one_tier(self):
        """Stated separately because the hosted demo instance reads as PUBLIC,
        and this is the row a logged-out judge exercises."""
        readable = [
            v
            for v in Visibility
            if readable_by(claim(visibility=v), Audience.PUBLIC)
        ]
        assert readable == [Visibility.PUBLIC]

    def test_filter_readable_projects_the_same_way(self):
        claims = [
            claim(visibility=v, quote=f"quote for {v.value}", locator=f"p.{i}")
            for i, v in enumerate(Visibility)
        ]
        kept = filter_readable(claims, Audience.SUCCESSOR)
        assert {c.visibility for c in kept} == {
            Visibility.PUBLIC,
            Visibility.ORG,
            Visibility.SUCCESSOR,
        }


# --------------------------------------------- counted but never quoted


class TestContradictionRendering:
    def _pair(self):
        readable = claim(
            quote=PUBLIC_QUOTE,
            object_literal="500",
            visibility=Visibility.PUBLIC,
            source_id="src:constitution-scan",
            locator="p.4 ¶2",
        )
        withheld = claim(
            quote=PRIVATE_QUOTE,
            object_literal="250",
            visibility=Visibility.PRIVATE,
            source_id="src:chat-export",
            locator="msg:1743689400",
        )
        contradiction = Contradiction.create(
            subject_id="ent:treasurer",
            predicate_hint="signing authority",
            claim_ids=[readable.claim_id, withheld.claim_id],
            detected_at="2026-04-03T14:31:00Z",
            confidence=0.82,
            rationale="Two records give different ceilings over the same period.",
        )
        claims = {readable.claim_id: readable, withheld.claim_id: withheld}
        return readable, withheld, contradiction, claims

    def test_the_unreadable_side_is_still_counted(self):
        _, withheld, contradiction, claims = self._pair()
        rendered = contradiction.render_for(claims, Audience.PUBLIC)

        # Both sides occupy a slot: the count of disagreements stays honest.
        assert len(rendered.sides) == 2
        assert len(contradiction.claim_ids) == 2
        assert withheld.claim_id in contradiction.claim_ids
        assert rendered.fully_readable is False

    def test_the_unreadable_side_is_never_quoted(self):
        _, _, contradiction, claims = self._pair()
        rendered = contradiction.render_for(claims, Audience.PUBLIC)

        blob = " ".join([rendered.summary, *rendered.sides])
        assert PRIVATE_QUOTE not in blob
        assert "250" not in blob
        assert PUBLIC_QUOTE in blob

    def test_the_summary_degrades_when_a_side_is_withheld(self):
        _, _, contradiction, claims = self._pair()
        public_view = contradiction.render_for(claims, Audience.PUBLIC)
        owner_view = contradiction.render_for(claims, Audience.OWNER)

        assert owner_view.fully_readable is True
        assert owner_view.summary == contradiction.rationale
        assert public_view.summary != contradiction.rationale

    def test_a_missing_claim_is_treated_as_unreadable_not_skipped(self):
        readable, withheld, contradiction, _ = self._pair()
        partial = {readable.claim_id: readable}
        rendered = contradiction.render_for(partial, Audience.OWNER)
        assert len(rendered.sides) == 2
        assert rendered.fully_readable is False

    def test_redacted_projection_carries_no_text(self):
        _, withheld, _, _ = self._pair()
        projection = redacted_for(withheld, Audience.PUBLIC)

        assert projection.readable is False
        assert projection.claim_id == withheld.claim_id
        # Every field, serialized: the projection must have nowhere to hide text.
        assert PRIVATE_QUOTE not in json.dumps(asdict(projection))
        assert "250" not in json.dumps(asdict(projection))
        assert PRIVATE_QUOTE not in projection.render()


# ------------------------------------------------------- successor mode


class TestLibrarianWithholding:
    QUESTION = "who holds the reserve account password for the treasurer"

    def _claims(self):
        visible = claim(
            subject="ent:treasurer",
            predicate="reserve_account",
            hint="reserve account access",
            quote="Reserve account access sits with the treasurer role.",
            object_literal="treasurer role",
            visibility=Visibility.SUCCESSOR,
            tier=Tier.PENDING,
            source_id="src:minutes-april",
            locator="p.2 ¶1",
        )
        hidden_a = claim(
            subject="ent:treasurer",
            predicate="reserve_account",
            hint="reserve account access",
            quote=PRIVATE_QUOTE,
            object_literal="outgoing chair",
            source_id="src:chat-export",
            locator="msg:1743689401",
        )
        hidden_b = claim(
            subject="ent:treasurer",
            predicate="reserve_account",
            hint="reserve account access",
            quote="The password itself is written in the back of the ledger.",
            object_literal="back of the ledger",
            source_id="src:chat-export",
            locator="msg:1743689402",
        )
        return visible, hidden_a, hidden_b

    def test_only_unreadable_matches_produces_a_refusal_with_an_honest_count(self):
        _, hidden_a, hidden_b = self._claims()
        state = _state_with(
            (hidden_a, Visibility.PRIVATE), (hidden_b, Visibility.PRIVATE)
        )
        client = FakeLLMClient()  # unscripted: any model call is a test failure
        answer = Librarian(client, state, audience=Audience.SUCCESSOR).ask(
            self.QUESTION
        )

        assert answer.refused is True
        assert answer.text == REFUSAL_TEXT
        assert answer.withheld == 2
        assert answer.readable == 0
        assert client.calls == []

        rendered = "\n".join(answer.render())
        assert "2 further record(s)" in rendered
        assert PRIVATE_QUOTE not in rendered
        assert "back of the ledger" not in rendered

    def test_a_readable_match_answers_and_still_reports_the_withheld_count(self):
        visible, hidden_a, hidden_b = self._claims()
        state = _state_with(
            (visible, Visibility.SUCCESSOR),
            (hidden_a, Visibility.PRIVATE),
            (hidden_b, Visibility.PRIVATE),
        )
        client = FakeLLMClient(
            {
                "librarian.v1": json.dumps(
                    {
                        "answer": "Reserve account access sits with the treasurer role.",
                        "claim_ids": [visible.claim_id],
                    }
                )
            }
        )
        answer = Librarian(client, state, audience=Audience.SUCCESSOR).ask(
            self.QUESTION
        )

        assert answer.refused is False
        assert answer.withheld == 2
        assert [c.claim_id for c in answer.citations] == [visible.claim_id]

        rendered = "\n".join(answer.render())
        assert PRIVATE_QUOTE not in rendered
        assert "back of the ledger" not in rendered

        # The withheld claims must not have reached the model either.
        prompt = client.calls_for("librarian.v1")[0].prompt
        assert PRIVATE_QUOTE not in prompt
        assert "back of the ledger" not in prompt

    def test_a_hallucinated_citation_is_dropped_and_the_answer_refused(self):
        visible, hidden_a, _ = self._claims()
        state = _state_with(
            (visible, Visibility.SUCCESSOR), (hidden_a, Visibility.PRIVATE)
        )
        client = FakeLLMClient(
            {
                "librarian.v1": json.dumps(
                    {
                        "answer": "It is the outgoing chair.",
                        "claim_ids": [hidden_a.claim_id],
                    }
                )
            }
        )
        answer = Librarian(client, state, audience=Audience.SUCCESSOR).ask(
            self.QUESTION
        )

        # The model cited a claim it was never shown. Citing it would leak; not
        # citing it leaves the answer uncited, and uncited synthesis is refused.
        assert answer.refused is True
        assert answer.citations == []
        assert "outgoing chair" not in "\n".join(answer.render())
