"""The hosted ledger and agenda must inherit the visibility boundary."""

from __future__ import annotations

from baraza.fold.graph import fold
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.contradiction import Contradiction
from baraza.schema.visibility import Audience, Visibility
from baraza.successor.service import _render_agenda_page, _render_ledger_page
from baraza_testkit import asserted, claim, committed, detected, ms, visibility_set


def _state_with_partially_private_dispute():
    public = claim(
        quote="The budget workbook records a travel allocation of 7150.",
        object_literal="7150",
        visibility=Visibility.PUBLIC,
        source_id="src:budget",
        locator="Budget!B12",
    )
    private = claim(
        quote="The private exit note says the allocation was reduced to 4000.",
        object_literal="4000",
        visibility=Visibility.PRIVATE,
        source_id="src:exit-note",
        locator="turn:3",
    )
    contradiction = Contradiction.create(
        subject_id=public.subject_id,
        predicate_hint=public.predicate_hint,
        claim_ids=[public.claim_id, private.claim_id],
        detected_at=ms("2026-05-03T00:00:00Z"),
        confidence=0.9,
        rationale="The two records give different allocations.",
    )
    return fold(
        [
            asserted(public),
            asserted(private),
            committed(public.claim_id, ms("2026-05-02T00:00:00Z")),
            committed(private.claim_id, ms("2026-05-02T00:00:00Z")),
            visibility_set(public.claim_id, Visibility.PUBLIC, ms("2026-05-02T00:01:00Z")),
            detected(contradiction, ms("2026-05-03T00:00:00Z")),
        ]
    )


def test_public_ledger_counts_a_private_side_without_rendering_it():
    state = _state_with_partially_private_dispute()

    html = _render_ledger_page(state)

    assert "The budget workbook records a travel allocation of 7150." in html
    assert "The private exit note says the allocation was reduced to 4000." not in html
    assert "outside your access" in html


def test_public_agenda_refuses_to_make_a_prompt_from_partial_evidence():
    state = _state_with_partially_private_dispute()

    assert not DisputedLedger(state).rows(Audience.PUBLIC)[0].rendered.fully_readable
    html = _render_agenda_page(state)

    assert "No public agenda items yet." in html
    assert "The private exit note says the allocation was reduced to 4000." not in html
