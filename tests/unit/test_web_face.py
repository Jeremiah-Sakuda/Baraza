"""The web face: session view, dossier, doctrine, approval queue, divergence.

Two properties are load-bearing and tested off the happy path:

* **The boundary renders.** The dossier and doctrine views on the public
  service must pass every read through ``readable_by(Audience.PUBLIC)`` — a
  private committed belief appears as a count, never as text — and the empty
  state must say *why* it is empty rather than look broken.
* **Nothing is fabricated.** A turn whose model backend is unreachable is a 503
  with the turn still recorded; a doctrine whose compiler is absent renders the
  absence, not a substitute policy.
"""

from __future__ import annotations

import sys
import types

import pytest
from fastapi.testclient import TestClient

from baraza.dossier import service as dossier_service
from baraza.fold.store import JsonlEventStore
from baraza.interview import service as interview_service
from baraza.reconcile.agenda import Agenda, AgendaItem
from baraza.schema.claim import Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.session import Session
from baraza.schema.visibility import Audience, Visibility
from baraza.web import views
from baraza_testkit import (
    FakeLLMClient,
    asserted,
    claim,
    committed,
    detected,
    ms,
    resolved,
    visibility_set,
)

T0 = ms("2026-08-01T00:00:00Z")
T1 = ms("2026-08-02T00:00:00Z")


# ------------------------------------------------------------------- fixtures


def _wire(service_module, tmp_path, responses=None):
    """Point a service module's per-instance runtime at a scratch log.

    The runtime is a module-level singleton by design (it is a cache, not
    state); tests re-point its handles rather than rebuilding the app.
    """
    runtime = service_module._runtime
    runtime._store = JsonlEventStore(tmp_path / "log.jsonl")
    runtime._client = FakeLLMClient(responses or {})
    runtime._state = None
    runtime._state_at = 0.0
    if hasattr(runtime, "_agendas"):
        runtime._agendas = {}
    return runtime


@pytest.fixture()
def public_runtime(tmp_path):
    return _wire(dossier_service, tmp_path)


@pytest.fixture()
def owner_runtime(tmp_path):
    return _wire(
        interview_service,
        tmp_path,
        responses={
            "divergence.v1": '{"divergence": null}',
            "follow_up.v1": '{"question": "SETTLED"}',
            "beliefs.v1": '{"beliefs": []}',
        },
    )


def _public_belief(**overrides):
    defaults = dict(
        quote="Never pad estimates; cite the source before the number.",
        hint="estimate discipline",
        visibility=Visibility.PUBLIC,
        tier=Tier.COMMITTED,
        locator="turn:t-9",
    )
    defaults.update(overrides)
    return claim(**defaults)


def _private_belief(**overrides):
    defaults = dict(
        quote="I decide visibility, not the agent.",
        hint="visibility authority",
        visibility=Visibility.PRIVATE,
        tier=Tier.COMMITTED,
        locator="turn:t-14",
    )
    defaults.update(overrides)
    return claim(**defaults)


def _seed_beliefs(store):
    """One published belief, one committed-but-private one."""
    public = _public_belief()
    private = _private_belief()
    store.append_many(
        [
            asserted(public, T0),
            asserted(private, T0),
            committed(public.claim_id, T0),
            committed(private.claim_id, T0),
            visibility_set(public.claim_id, Visibility.PUBLIC, T0),
            visibility_set(private.claim_id, Visibility.PRIVATE, T0),
        ]
    )
    return public, private


# ------------------------------------------------------------------ dossier


def test_dossier_empty_state_names_the_boundary(public_runtime):
    page = TestClient(dossier_service.app).get("/dossier")
    assert page.status_code == 200
    assert "the boundary working" in page.text
    assert "private" in page.text
    # Honest even when there is nothing to withhold.
    assert "No committed beliefs are being withheld" in page.text


def test_dossier_lists_public_belief_and_withholds_private(public_runtime):
    public, private = _seed_beliefs(public_runtime.store)
    page = TestClient(dossier_service.app).get("/dossier")

    assert "Never pad estimates" in page.text
    assert "turn:t-9" in page.text  # the anchor
    assert "learned 2026-04-01" in page.text  # learned_at, display only
    assert "committed" in page.text  # the tier
    # The private belief: counted, never quoted.
    assert "I decide visibility" not in page.text
    assert "1 further belief(s) are committed but not published" in page.text


def test_dossier_reject_appends_retraction_and_row_disappears(public_runtime):
    public, _ = _seed_beliefs(public_runtime.store)
    client = TestClient(dossier_service.app)

    response = client.post("/api/dossier/reject", json={"claim_id": public.claim_id})
    assert response.status_code == 200
    assert response.json()["rejected"] == [public.claim_id]

    events = public_runtime.store.read_all()
    assert any(e.event_type.value == "claim.rejected" for e in events)
    assert "Never pad estimates" not in client.get("/dossier").text


def test_dossier_reject_refuses_a_belief_this_audience_cannot_read(public_runtime):
    _, private = _seed_beliefs(public_runtime.store)
    before = len(public_runtime.store.read_all())

    response = TestClient(dossier_service.app).post(
        "/api/dossier/reject", json={"claim_id": private.claim_id}
    )

    # Indistinguishable from a claim that does not exist: a logged-out request
    # must not be able to probe (or retract) what it cannot see.
    assert response.status_code == 404
    assert len(public_runtime.store.read_all()) == before


# ------------------------------------------------------------------ doctrine


class _hidden_modules:
    """Make ``import <name>`` fail for the duration, restoring afterwards.

    ``sys.modules[name] = None`` is the documented way to force ``ImportError``
    for an installed module — how the web face behaves when the doctrine lane's
    package is absent from a build is a property worth holding even now that
    the package exists.
    """

    def __init__(self, *names: str):
        self.names = names
        self.saved: dict[str, object] = {}

    def __enter__(self):
        for name in self.names:
            self.saved[name] = sys.modules.pop(name, None)
            sys.modules[name] = None  # type: ignore[assignment]
        return self

    def __exit__(self, *_):
        for name in self.names:
            real = self.saved[name]
            if real is None:
                del sys.modules[name]
            else:
                sys.modules[name] = real


def test_doctrine_degrades_honestly_when_the_compiler_is_absent(public_runtime):
    with _hidden_modules("baraza.doctrine", "baraza.doctrine.compiler"):
        page = TestClient(dossier_service.app).get("/doctrine")
    assert page.status_code == 200
    assert "not available on this surface" in page.text
    assert "fabricated" in page.text


def test_doctrine_renders_provenance_and_reads_quotes_through_the_predicate(
    public_runtime,
):
    public, private = _seed_beliefs(public_runtime.store)

    compiler = types.ModuleType("baraza.doctrine.compiler")
    compiler.compile_doctrine = lambda **_: {
        "rules": [
            {"text": "Cite the source before any number.", "claim_id": public.claim_id},
            {"text": "Visibility decisions rest with the user.", "claim_id": private.claim_id},
        ]
    }
    real = sys.modules.pop("baraza.doctrine.compiler", None)
    sys.modules["baraza.doctrine.compiler"] = compiler
    try:
        page = TestClient(dossier_service.app).get("/doctrine")
    finally:
        del sys.modules["baraza.doctrine.compiler"]
        if real is not None:
            sys.modules["baraza.doctrine.compiler"] = real

    assert "Cite the source before any number." in page.text
    assert public.claim_id in page.text
    assert "Never pad estimates" in page.text  # readable rule's quote
    # The private claim's rule renders — its quote does not. The compiler's
    # payload is never trusted for what this audience may read.
    assert "Visibility decisions rest with the user." in page.text
    assert "I decide visibility" not in page.text
    assert views.WITHHELD_PLACEHOLDER[:20] in page.text
    # No epoch boundary in this log: the panel says so instead of inventing an
    # empty diff.
    assert "No diff between epochs is available yet" in page.text


def test_doctrine_view_compiles_through_the_real_doctrine_lane(public_runtime):
    """End-to-end against the doctrine lane's actual compiler, if importable."""
    pytest.importorskip("baraza.doctrine.compiler")
    belief = claim(
        hint="estimation policy",
        quote="Never pad estimates; cite the source before the number.",
        visibility=Visibility.PUBLIC,
        tier=Tier.COMMITTED,
        locator="turn:t-9",
        extra={"rule_text": "Never pad estimates."},
    )
    public_runtime.store.append_many(
        [
            asserted(belief, T0),
            committed(belief.claim_id, T0),
            visibility_set(belief.claim_id, Visibility.PUBLIC, T0),
        ]
    )

    page = TestClient(dossier_service.app).get("/doctrine")

    assert page.status_code == 200
    assert "Never pad estimates." in page.text  # the compiled rule text
    assert belief.claim_id in page.text  # provenance: claim id
    assert "turn:t-9" in page.text  # provenance: anchor


# ------------------------------------------------------------- session view


def _seed_session(runtime, *, with_resolved_item: bool) -> tuple[Session, Agenda]:
    """A session with two agenda items; optionally one already resolved."""
    a = claim(hint="estimate discipline", quote="Estimates are never padded.")
    b = claim(
        hint="review order",
        quote="Drafts are reviewed before they are sent.",
        locator="p.2 ¶1",
    )
    open_c = Contradiction.create(
        subject_id=a.subject_id,
        predicate_hint=a.predicate_hint,
        claim_ids=[a.claim_id, b.claim_id],
        detected_at=T0,
        confidence=0.9,
        rationale="The records disagree about padding.",
    )
    done_c = Contradiction.create(
        subject_id=b.subject_id,
        predicate_hint=b.predicate_hint,
        claim_ids=[a.claim_id, b.claim_id],
        detected_at=T0,
        confidence=0.8,
        rationale="The records disagree about review order.",
    )
    events = [asserted(a, T0), asserted(b, T0), detected(open_c, T0), detected(done_c, T0)]
    if with_resolved_item:
        events.append(resolved(done_c.contradiction_id, T1))
    runtime.store.append_many(events)

    from baraza.interview.session_store import SessionStore

    session = SessionStore(runtime.store).open(persona_id="builder", opened_at=T1)
    agenda = Agenda(
        items=[
            AgendaItem(
                item_id="item-001",
                contradiction_id=open_c.contradiction_id,
                subject_id=a.subject_id,
                predicate_hint=a.predicate_hint,
                question="Which estimate rule governs, and since when?",
                why_it_matters="It decides how every estimate is drafted.",
                score=1.0,
                stakes_label="high",
                fully_readable=True,
                cited_claim_ids=[a.claim_id],
            ),
            AgendaItem(
                item_id="item-002",
                contradiction_id=done_c.contradiction_id,
                subject_id=b.subject_id,
                predicate_hint=b.predicate_hint,
                question="Who reviews a draft before it goes out?",
                why_it_matters="It decides what may be sent unreviewed.",
                score=0.8,
                stakes_label="medium",
                fully_readable=True,
                cited_claim_ids=[b.claim_id],
            ),
        ],
        generated_at=T1,
        audience=Audience.OWNER,
    )
    runtime._agendas[session.session_id] = agenda
    return session, agenda


def test_session_view_shows_retirement_ticks(owner_runtime):
    session, _ = _seed_session(owner_runtime, with_resolved_item=True)
    page = TestClient(interview_service.app).get(f"/sessions/{session.session_id}/view")

    assert page.status_code == 200
    assert "Which estimate rule governs" in page.text
    assert "Who reviews a draft" in page.text
    assert "✓" in page.text  # the resolved item's tick
    assert "1 item(s) retired" in page.text


def test_partner_turn_is_recorded_even_when_extraction_finds_nothing(owner_runtime):
    session, _ = _seed_session(owner_runtime, with_resolved_item=False)
    client = TestClient(interview_service.app)

    response = client.post(
        f"/sessions/{session.session_id}/turns",
        json={"text": "Estimates should be padded fifteen percent to be safe."},
    )

    assert response.status_code == 200
    body = response.json()
    # The turn is in the append-only log regardless of what extraction did.
    assert any(
        e.event_type.value == "session.turn" for e in owner_runtime.store.read_all()
    )
    assert body["extracted_claim_ids"] == []
    assert body["notes"] == []  # the extractor ran; nothing degraded


def test_partner_turn_states_extraction_absence_instead_of_hiding_it(owner_runtime):
    session, _ = _seed_session(owner_runtime, with_resolved_item=False)

    # A build where the extraction lane exposes no turn-level symbol at all.
    empty = types.ModuleType("baraza.ingest.extract")
    real = sys.modules.pop("baraza.ingest.extract", None)
    sys.modules["baraza.ingest.extract"] = empty
    try:
        response = TestClient(interview_service.app).post(
            f"/sessions/{session.session_id}/turns",
            json={"text": "Cite the source before the number, always."},
        )
    finally:
        del sys.modules["baraza.ingest.extract"]
        if real is not None:
            sys.modules["baraza.ingest.extract"] = real

    assert response.status_code == 200
    body = response.json()
    assert body["extracted_claim_ids"] == []
    assert any("not wired" in note for note in body["notes"])


def test_partner_turn_answers_503_when_the_backend_is_unreachable(owner_runtime):
    session, _ = _seed_session(owner_runtime, with_resolved_item=False)

    def _down(**_):
        raise ConnectionError("backend unreachable")

    broken = types.ModuleType("baraza.ingest.extract")
    broken.claims_from_turn = _down
    real = sys.modules.pop("baraza.ingest.extract", None)
    sys.modules["baraza.ingest.extract"] = broken
    try:
        response = TestClient(interview_service.app).post(
            f"/sessions/{session.session_id}/turns",
            json={"text": "Route anything ambiguous back to me before acting."},
        )
    finally:
        del sys.modules["baraza.ingest.extract"]
        if real is not None:
            sys.modules["baraza.ingest.extract"] = real

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert "recorded" in detail
    assert "fabricated" in detail
    # Honest failure direction: the turn IS in the log, the reply is not.
    events = owner_runtime.store.read_all()
    assert any(e.event_type.value == "session.turn" for e in events)


def test_extracted_beliefs_land_pending_and_reach_the_approval_queue(owner_runtime):
    session, _ = _seed_session(owner_runtime, with_resolved_item=False)
    belief = claim(
        hint="routing rule",
        quote="Anything ambiguous is routed back to me before acting.",
        locator="turn:t-2",
    )

    extractor = types.ModuleType("baraza.ingest.extract")
    extractor.claims_from_turn = lambda **_: [belief]
    real = sys.modules.pop("baraza.ingest.extract", None)
    sys.modules["baraza.ingest.extract"] = extractor
    try:
        client = TestClient(interview_service.app)
        response = client.post(
            f"/sessions/{session.session_id}/turns",
            json={"text": "Anything ambiguous is routed back to me before acting."},
        )
        assert response.status_code == 200
        assert response.json()["extracted_claim_ids"] == [belief.claim_id]

        queue = client.get("/approvals")
    finally:
        del sys.modules["baraza.ingest.extract"]
        if real is not None:
            sys.modules["baraza.ingest.extract"] = real

    # Pending, private, awaiting ratification — with the default that leaks nothing.
    assert "Anything ambiguous is routed back to me" in queue.text
    assert "private (default)" in queue.text
    folded = interview_service._runtime.state(force=True)
    assert folded.claims[belief.claim_id].tier is Tier.PENDING


# ------------------------------------------------------------- adjudication


def _seed_divergence(runtime):
    """A committed old belief and a pending new statement, in open contradiction."""
    old = claim(
        hint="estimate discipline",
        quote="Never pad estimates.",
        tier=Tier.PENDING,
        locator="turn:t-9",
    )
    new = claim(
        hint="estimate discipline",
        quote="Pad the estimates to be safe.",
        tier=Tier.PENDING,
        locator="turn:t-31",
    )
    contradiction = Contradiction.create(
        subject_id=old.subject_id,
        predicate_hint=old.predicate_hint,
        claim_ids=[old.claim_id, new.claim_id],
        detected_at=T1,
        confidence=0.95,
        rationale="Both rules cannot govern the same estimate.",
    )
    runtime.store.append_many(
        [
            asserted(old, T0),
            asserted(new, T1),
            committed(old.claim_id, T0),
            detected(contradiction, T1),
        ]
    )
    return old, new, contradiction


def test_that_governs_retracts_the_new_statement_and_retires_the_dispute(owner_runtime):
    old, new, contradiction = _seed_divergence(owner_runtime)
    response = TestClient(interview_service.app).post(
        "/sessions/sess-x/divergence",
        json={
            "choice": "that_governs",
            "new_claim_id": new.claim_id,
            "old_claim_id": old.claim_id,
            "contradiction_id": contradiction.contradiction_id,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert new.claim_id in body["rejected"]
    assert old.claim_id in body["committed"]
    assert contradiction.contradiction_id in body["contradictions_resolved"]

    state = owner_runtime.state(force=True)
    assert state.claims[new.claim_id].tier is Tier.REJECTED
    assert state.claims[old.claim_id].tier is Tier.COMMITTED
    assert not state.open_contradictions()


def test_this_governs_commits_the_new_statement_and_retracts_the_old(owner_runtime):
    old, new, contradiction = _seed_divergence(owner_runtime)
    response = TestClient(interview_service.app).post(
        "/sessions/sess-x/divergence",
        json={
            "choice": "this_governs",
            "new_claim_id": new.claim_id,
            "old_claim_id": old.claim_id,
            "contradiction_id": contradiction.contradiction_id,
        },
    )

    assert response.status_code == 200
    state = owner_runtime.state(force=True)
    assert state.claims[new.claim_id].tier is Tier.COMMITTED
    assert state.claims[old.claim_id].tier is Tier.REJECTED


def test_splitting_into_a_conditional_requires_the_users_wording(owner_runtime):
    old, new, contradiction = _seed_divergence(owner_runtime)
    response = TestClient(interview_service.app).post(
        "/sessions/sess-x/divergence",
        json={
            "choice": "both_conditional",
            "new_claim_id": new.claim_id,
            "old_claim_id": old.claim_id,
            "contradiction_id": contradiction.contradiction_id,
        },
    )
    # The conditional's wording is the user's, not the system's to invent.
    assert response.status_code == 422
    state = owner_runtime.state(force=True)
    assert state.claims[new.claim_id].tier is Tier.PENDING


def test_conditional_split_supersedes_the_statement_and_retires_the_dispute(
    owner_runtime,
):
    old, new, contradiction = _seed_divergence(owner_runtime)
    wording = "Never pad internal estimates; pad client-facing ones fifteen percent."
    response = TestClient(interview_service.app).post(
        "/sessions/sess-x/divergence",
        json={
            "choice": "both_conditional",
            "new_claim_id": new.claim_id,
            "old_claim_id": old.claim_id,
            "contradiction_id": contradiction.contradiction_id,
            "conditional_text": wording,
        },
    )

    assert response.status_code == 200
    committed_ids = response.json()["committed"]
    assert len(committed_ids) == 1
    state = owner_runtime.state(force=True)
    conditional = state.claims[committed_ids[0]]
    assert conditional.quote_for(Audience.OWNER) == wording
    assert conditional.extra.get("supersedes") == new.claim_id
    assert not state.open_contradictions()


# ------------------------------------------------------------ pure renderers


def test_divergence_card_renders_both_quotes_and_all_three_actions():
    card = views.render_divergence_card(
        {
            "contradiction_id": "ctr-1",
            "rationale": "Both rules cannot govern the same estimate.",
            "old_quote": "Never pad estimates.",
            "old_anchor": "interview:s1#turn:t-9",
            "old_claim_id": "clm_old",
            "new_quote": "Pad the estimates to be safe.",
            "new_anchor": "interview:s2#turn:t-31",
            "new_claim_id": "clm_new",
        },
        session_id="s2",
    )
    assert "Never pad estimates." in card
    assert "Pad the estimates to be safe." in card
    assert "interview:s1#turn:t-9" in card
    assert "This governs" in card
    assert "That governs" in card
    assert "split into a conditional" in card.lower()


def test_divergence_card_withholds_an_unreadable_old_quote():
    card = views.render_divergence_card(
        {
            "rationale": "A conflict exists with a record this audience may not read.",
            "old_quote": None,
            "old_anchor": "",
            "old_claim_id": "clm_old",
            "new_quote": "Pad the estimates to be safe.",
            "new_anchor": "interview:s2#turn:t-31",
            "new_claim_id": "clm_new",
        },
        session_id="s2",
    )
    assert views.WITHHELD_PLACEHOLDER in card


def test_approval_queue_empty_state_says_nothing_was_decided_for_you(owner_runtime):
    page = TestClient(interview_service.app).get("/approvals")
    assert "Nothing awaits ratification" in page.text
    assert "nothing was decided for you" in page.text
