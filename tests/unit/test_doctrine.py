"""The doctrine compiler and diff — WS3(b) and WS5(a).

What these tests hold the module to, in the compiler's own order of importance:

* the **belief boundary** — only committed, readable, belief-shaped claims
  compile; facts about the world never become instructions;
* **refusal to pick** — colliding committed rules suspend each other and
  surface as a ConflictNotice carrying both quotes, because a compiler that
  silently chose would be the approver with a model;
* **retraction is real** — reject, recompile, and the rule is provably gone
  and the fingerprint moved;
* the **diff names the causal claim** — a doctrine diff, never an output diff.

Byte-stability under log permutation and re-serialized offsets lives in
``tests/property/test_doctrine_stability.py``; these tests pin semantics.
"""

from __future__ import annotations

from typing import Any

from baraza.doctrine import (
    BELIEF_HINTS,
    Doctrine,
    render_system_prompt,
)
from baraza.doctrine import (
    compile as compile_doctrine,
)
from baraza.doctrine import (
    diff as doctrine_diff,
)
from baraza.fold.graph import GraphState, fold
from baraza.schema.claim import Claim, Provenance, Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.visibility import Audience, Visibility
from baraza_testkit import (
    asserted,
    claim,
    committed,
    ms,
    rejected,
    visibility_set,
)

BUILDER = "ent:the-builder"


def belief(
    *,
    quote: str,
    rule_text: str | None = None,
    predicate: str = "estimation_padding",
    hint: str = "estimation policy",
    literal: str = "never",
    turn: str = "turn:t-9",
    session: str = "ses:dogfood-01",
    observed_at: Any = "2026-08-24T10:00:00Z",
    valid_from: Any = None,
    valid_until: Any = None,
    tier: Tier = Tier.COMMITTED,
    visibility: Visibility | None = None,
    provenance: Provenance = Provenance.INTERVIEW,
) -> Claim:
    """A belief-shaped claim: the user's own statement about how to work."""
    extra = {"rule_text": rule_text} if rule_text else None
    return claim(
        subject=BUILDER,
        predicate=predicate,
        hint=hint,
        quote=quote,
        object_literal=literal,
        observed_at=observed_at,
        valid_from=valid_from,
        valid_until=valid_until,
        tier=tier,
        visibility=visibility,
        provenance=provenance,
        source_id=session,
        locator=turn,
        extra=extra,
    )


def state_of(*claims: Claim, contradictions: list[Contradiction] | None = None) -> GraphState:
    state = GraphState()
    for c in claims:
        state.claims[c.claim_id] = c
    for contradiction in contradictions or []:
        state.contradictions[contradiction.contradiction_id] = contradiction
    return state


NEVER_PAD = belief(
    quote="Never pad estimates. If it's three days, say three days.",
    rule_text="Never pad estimates.",
)


# --------------------------------------------------------- the belief boundary


class TestBeliefBoundary:
    def test_interview_provenance_compiles(self):
        doctrine = compile_doctrine(state_of(NEVER_PAD), audience=Audience.OWNER)
        assert [r.claim_id for r in doctrine.rules] == [NEVER_PAD.claim_id]

    def test_corpus_claim_with_belief_hint_compiles(self):
        mined = belief(
            quote="cite the source before the number, every time",
            rule_text="Cite the source before the number.",
            predicate="citation_order",
            hint="citation policy",
            literal="source-first",
            provenance=Provenance.CORPUS,
        )
        assert "citation policy" in BELIEF_HINTS
        doctrine = compile_doctrine(state_of(mined), audience=Audience.OWNER)
        assert [r.claim_id for r in doctrine.rules] == [mined.claim_id]

    def test_fact_shaped_corpus_claim_never_becomes_an_instruction(self):
        # Committed and readable, but "signing authority" is a fact about the
        # world. Promoting it would let a ledger entry silently become a rule.
        fact = claim(tier=Tier.COMMITTED)
        assert fact.predicate_hint not in BELIEF_HINTS
        doctrine = compile_doctrine(state_of(fact), audience=Audience.OWNER)
        assert doctrine.rules == ()
        assert doctrine.withheld == 0

    def test_hint_matching_is_exact_not_substring(self):
        # "policy" is a belief hint; "spending policy record" must not ride in
        # on containment — a boundary crossable by phrasing is not a boundary.
        near_miss = belief(
            quote="spent 40 on printing",
            hint="spending policy record",
            provenance=Provenance.CORPUS,
        )
        doctrine = compile_doctrine(state_of(near_miss), audience=Audience.OWNER)
        assert doctrine.rules == ()

    def test_uncommitted_belief_does_not_compile(self):
        pending = belief(quote="maybe stop using bullet points?", tier=Tier.PENDING)
        doctrine = compile_doctrine(state_of(pending), audience=Audience.OWNER)
        assert doctrine.rules == ()

    def test_unreadable_belief_is_withheld_not_rendered(self):
        # Default-private claim, compiled for ORG: counted, never quoted.
        doctrine = compile_doctrine(state_of(NEVER_PAD), audience=Audience.ORG)
        assert doctrine.rules == ()
        assert doctrine.withheld == 1
        prompt = render_system_prompt(doctrine)
        assert "Never pad" not in prompt
        assert "counted, not shown" in prompt


# ------------------------------------------------------------ rule provenance


class TestRuleProvenance:
    def test_rule_carries_quote_anchor_claim_id_and_learned_at(self):
        doctrine = compile_doctrine(state_of(NEVER_PAD), audience=Audience.OWNER)
        (rule,) = doctrine.rules
        assert rule.rule == "Never pad estimates."
        assert rule.claim_id == NEVER_PAD.claim_id
        assert rule.quote == "Never pad estimates. If it's three days, say three days."
        assert rule.anchor == "turn:t-9"
        assert rule.source_id == "ses:dogfood-01"
        assert rule.learned_at == ms("2026-08-24T10:00:00Z")

    def test_rule_without_authored_wording_falls_back_to_claim_fields(self):
        bare = belief(quote="never pad estimates", rule_text=None)
        doctrine = compile_doctrine(state_of(bare), audience=Audience.OWNER)
        (rule,) = doctrine.rules
        # Plain and true beats fluent and invented: the compiler makes no
        # model call, so the fallback is mechanical and predictable.
        assert rule.rule == "estimation padding: never"

    def test_prompt_annotates_every_rule_with_claim_id_and_anchor(self):
        second = belief(
            quote="I decide visibility, not you.",
            rule_text="Never widen visibility without an explicit user decision.",
            predicate="visibility_choice",
            hint="visibility policy",
            literal="user-decides",
            turn="turn:t-14",
            observed_at="2026-08-25T10:00:00Z",
        )
        doctrine = compile_doctrine(state_of(NEVER_PAD, second), audience=Audience.OWNER)
        prompt = render_system_prompt(doctrine)
        for rule in doctrine.rules:
            assert f"[{rule.claim_id} | {rule.anchor}]" in prompt
            assert rule.quote in prompt

    def test_agreeing_restatements_deduplicate_to_first_statement(self):
        restated = belief(
            quote="again: never pad estimates",
            rule_text="Never pad estimates.",
            turn="turn:t-40",
            session="ses:dogfood-03",
            observed_at="2026-08-27T10:00:00Z",
        )
        doctrine = compile_doctrine(
            state_of(NEVER_PAD, restated), audience=Audience.OWNER
        )
        assert [r.claim_id for r in doctrine.rules] == [NEVER_PAD.claim_id]
        assert doctrine.rules[0].learned_at == ms("2026-08-24T10:00:00Z")


# ----------------------------------------------------------- refusal to pick


PAD_CLIENTS = belief(
    quote="just pad the client-facing ones by 15%",
    rule_text="Pad client-facing estimates by 15%.",
    literal="pad-client-facing-15",
    turn="turn:t-31",
    session="ses:dogfood-04",
    observed_at="2026-08-28T10:00:00Z",
)


class TestRefusalToPick:
    def test_conflicting_committed_rules_suspend_each_other(self):
        doctrine = compile_doctrine(
            state_of(NEVER_PAD, PAD_CLIENTS), audience=Audience.OWNER
        )
        assert doctrine.rules == ()
        (notice,) = doctrine.conflicts
        assert notice.origin == "structural"
        assert set(notice.claim_ids) == {NEVER_PAD.claim_id, PAD_CLIENTS.claim_id}

    def test_conflict_notice_carries_both_quotes(self):
        doctrine = compile_doctrine(
            state_of(NEVER_PAD, PAD_CLIENTS), audience=Audience.OWNER
        )
        (notice,) = doctrine.conflicts
        quotes = {side.quote for side in notice.sides}
        assert "Never pad estimates. If it's three days, say three days." in quotes
        assert "just pad the client-facing ones by 15%" in quotes
        prompt = render_system_prompt(doctrine)
        assert "UNRESOLVED CONFLICTS" in prompt
        assert "which governs" in prompt

    def test_non_overlapping_periods_are_history_not_a_dispute(self):
        superseded = belief(
            quote="Never pad estimates. If it's three days, say three days.",
            rule_text="Never pad estimates.",
            valid_until="2026-08-28T00:00:00Z",
        )
        current = belief(
            quote="just pad the client-facing ones by 15%",
            rule_text="Pad client-facing estimates by 15%.",
            literal="pad-client-facing-15",
            turn="turn:t-31",
            session="ses:dogfood-04",
            observed_at="2026-08-28T10:00:00Z",
            valid_from="2026-08-28T00:00:00Z",
        )
        doctrine = compile_doctrine(
            state_of(superseded, current), audience=Audience.OWNER
        )
        assert doctrine.conflicts == ()
        assert {r.claim_id for r in doctrine.rules} == {
            superseded.claim_id,
            current.claim_id,
        }

    def test_open_ledger_contradiction_suspends_across_blocking_keys(self):
        # Different hints, so the structural check cannot group them — but the
        # reconciler adjudicated them as colliding, and compiling either side
        # would act on a dispute the user has not resolved.
        review_first = belief(
            quote="never send before I've seen it",
            rule_text="Never send anything before the user has reviewed it.",
            predicate="send_review",
            hint="rule",
            literal="review-first",
            turn="turn:t-14",
        )
        routine_auto = belief(
            quote="just send the routine ones",
            rule_text="Send routine items without review.",
            predicate="send_routing",
            hint="routing",
            literal="auto-routine",
            turn="turn:t-52",
            session="ses:dogfood-05",
            observed_at="2026-08-29T10:00:00Z",
        )
        contradiction = Contradiction.create(
            subject_id=BUILDER,
            predicate_hint="rule",
            claim_ids=[review_first.claim_id, routine_auto.claim_id],
            detected_at=ms("2026-08-29T10:01:00Z"),
            confidence=0.9,
            rationale="One statement requires review before sending; the other waives it.",
        )
        doctrine = compile_doctrine(
            state_of(review_first, routine_auto, contradictions=[contradiction]),
            audience=Audience.OWNER,
        )
        assert doctrine.rules == ()
        (notice,) = doctrine.conflicts
        assert notice.origin == "ledger"
        assert "requires review" in notice.rationale

    def test_unreadable_side_counts_but_is_never_quoted(self):
        # The private side must still suspend the org-readable one — otherwise
        # visibility choices could quietly adjudicate a dispute — but its text
        # must not reach the ORG audience through the notice.
        org_side = belief(
            quote="just pad the client-facing ones by 15%",
            rule_text="Pad client-facing estimates by 15%.",
            literal="pad-client-facing-15",
            turn="turn:t-31",
            session="ses:dogfood-04",
            observed_at="2026-08-28T10:00:00Z",
            visibility=Visibility.ORG,
        )
        doctrine = compile_doctrine(state_of(NEVER_PAD, org_side), audience=Audience.ORG)
        assert doctrine.rules == ()
        (notice,) = doctrine.conflicts
        by_id = {side.claim_id: side for side in notice.sides}
        assert by_id[org_side.claim_id].quote == "just pad the client-facing ones by 15%"
        assert by_id[NEVER_PAD.claim_id].quote is None
        prompt = render_system_prompt(doctrine)
        assert "Never pad" not in prompt
        assert "counted, not quoted" in prompt


# ------------------------------------------------- retraction, through the log


class TestRetractionThroughTheLog:
    def build(self) -> list:
        pad = belief(
            quote="pad everything 20% to be safe",
            rule_text="Pad all estimates by 20%.",
            literal="pad-20",
            turn="turn:t-3",
            observed_at="2026-08-23T10:00:00Z",
            tier=Tier.PENDING,
        )
        keep = belief(
            quote="cite the source before the number",
            rule_text="Cite the source before the number.",
            predicate="citation_order",
            hint="citation policy",
            literal="source-first",
            turn="turn:t-14",
            observed_at="2026-08-24T10:00:00Z",
            tier=Tier.PENDING,
        )
        self.pad_id = pad.claim_id
        self.keep_id = keep.claim_id
        return [
            asserted(pad),
            asserted(keep),
            committed(pad.claim_id, "2026-08-24T20:00:00Z"),
            committed(keep.claim_id, "2026-08-24T20:00:01Z"),
        ]

    def test_reject_then_recompile_and_the_rule_is_provably_gone(self):
        events = self.build()
        before = compile_doctrine(fold(events), audience=Audience.OWNER)
        assert {r.claim_id for r in before.rules} == {self.pad_id, self.keep_id}

        events.append(rejected(self.pad_id, "2026-08-25T09:00:00Z"))
        after = compile_doctrine(fold(events), audience=Audience.OWNER)

        assert {r.claim_id for r in after.rules} == {self.keep_id}
        assert self.pad_id not in {r.claim_id for r in after.rules}
        assert after.fingerprint() != before.fingerprint()
        assert "Pad all estimates" not in render_system_prompt(after)

    def test_visibility_tightening_removes_the_rule_for_that_audience(self):
        events = self.build()
        events.append(visibility_set(self.keep_id, Visibility.ORG, "2026-08-24T21:00:00Z"))
        as_org = compile_doctrine(fold(events), audience=Audience.ORG)
        assert {r.claim_id for r in as_org.rules} == {self.keep_id}

        events.append(
            visibility_set(self.keep_id, Visibility.PRIVATE, "2026-08-24T22:00:00Z")
        )
        tightened = compile_doctrine(fold(events), audience=Audience.ORG)
        assert tightened.rules == ()
        assert tightened.withheld == 2


# -------------------------------------------------------------------- the diff


def _doctrine(*claims: Claim, contradictions: list[Contradiction] | None = None) -> Doctrine:
    return compile_doctrine(
        state_of(*claims, contradictions=contradictions), audience=Audience.OWNER
    )


CITE_FIRST = belief(
    quote="cite the source before the number",
    rule_text="Cite the source before the number.",
    predicate="citation_order",
    hint="citation policy",
    literal="source-first",
    turn="turn:t-14",
    observed_at="2026-08-25T10:00:00Z",
)


class TestDoctrineDiff:
    def test_added_rule_names_its_causal_claim(self):
        result = doctrine_diff(_doctrine(NEVER_PAD), _doctrine(NEVER_PAD, CITE_FIRST))
        (entry,) = result.added
        assert entry.causal_claim_id == CITE_FIRST.claim_id
        assert result.removed == ()
        assert result.changed == ()
        assert result.unchanged_count == 1

    def test_removed_rule_names_its_causal_claim(self):
        result = doctrine_diff(_doctrine(NEVER_PAD, CITE_FIRST), _doctrine(NEVER_PAD))
        (entry,) = result.removed
        assert entry.causal_claim_id == CITE_FIRST.claim_id
        assert "no longer among the committed, readable beliefs" in entry.note

    def test_replacement_on_the_same_question_is_a_change(self):
        # Old belief retracted, new belief committed, same subject and hint:
        # the policy on that question moved from one governing claim to another.
        replacement = belief(
            quote="fine — pad client-facing estimates by 15%, never internal ones",
            rule_text="Pad client-facing estimates by 15%; never pad internal ones.",
            literal="pad-client-facing-15",
            turn="turn:t-60",
            session="ses:dogfood-06",
            observed_at="2026-08-30T10:00:00Z",
        )
        result = doctrine_diff(_doctrine(NEVER_PAD), _doctrine(replacement))
        (entry,) = result.changed
        assert entry.causal_claim_id == replacement.claim_id
        assert entry.old.claim_id == NEVER_PAD.claim_id
        assert result.added == () and result.removed == ()

    def test_conflict_opening_is_reported_and_explains_the_removal(self):
        result = doctrine_diff(
            _doctrine(NEVER_PAD), _doctrine(NEVER_PAD, PAD_CLIENTS)
        )
        (opened,) = result.conflicts_opened
        assert set(opened.claim_ids) == {NEVER_PAD.claim_id, PAD_CLIENTS.claim_id}
        (removed,) = result.removed
        assert removed.rule.claim_id == NEVER_PAD.claim_id
        assert "suspended by an unresolved conflict" in removed.note

    def test_identical_doctrines_diff_empty(self):
        result = doctrine_diff(
            _doctrine(NEVER_PAD, CITE_FIRST), _doctrine(NEVER_PAD, CITE_FIRST)
        )
        assert result.is_empty
        assert result.old_fingerprint == result.new_fingerprint
        assert any("no change" in line for line in result.render())

    def test_render_and_json_carry_the_same_causal_claims(self):
        result = doctrine_diff(_doctrine(NEVER_PAD), _doctrine(NEVER_PAD, CITE_FIRST))
        lines = "\n".join(result.render())
        assert CITE_FIRST.claim_id in lines
        assert "turn:t-14" in lines
        payload = result.to_dict()
        assert payload["changes"][0]["causal_claim_id"] == CITE_FIRST.claim_id
        assert payload["old_fingerprint"] != payload["new_fingerprint"]
