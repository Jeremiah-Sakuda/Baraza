"""The dossier loop, closed: belief in, doctrine out, retraction real.

Every lane proved its own component; this file proves the seams between them
carry weight. One process, real components, no stand-ins except the model:

    user turn  →  BeliefExtractor (real gates)
               →  claim.asserted appended to a real JSONL store
               →  ApprovalFlow (the only promotion path)
               →  fold  →  doctrine compiler
               →  reject one belief  →  refold  →  recompile

What the end of the loop must show: every compiled rule carries the verbatim
quote and the ``turn:t-N`` anchor of the claim that put it there, and a
rejected belief is provably gone from the next compile — with the fingerprint
moved, so "the doctrine changed" is a checkable statement rather than a claim.

The model is a scripted fake. Whether a real model extracts judgment-shaped
beliefs from ordinary turns is the DECISION doc's honest gap #1 and is not
answered here; what is measured is *wiring* — that a belief which survives the
extraction gates travels the whole way to a cited rule and back out again.
No number this file produces may be published anywhere.
"""

from __future__ import annotations

import json

from baraza.doctrine import compile as compile_doctrine
from baraza.doctrine import render_system_prompt
from baraza.fold.graph import fold
from baraza.fold.store import JsonlEventStore
from baraza.ingest.extract import BELIEF_SCHEMA_NAME, USER_ENTITY_ID, extract_beliefs
from baraza.interview.approval import ApprovalFlow, ApprovalRequest, Decision
from baraza.schema.event import Event, EventType
from baraza.schema.visibility import Audience
from baraza_testkit import FakeLLMClient, ms

T_TURN = ms("2026-08-30T12:00:00Z")
T_APPROVE = ms("2026-08-30T12:30:00Z")
T_REJECT = ms("2026-08-31T09:00:00Z")

TURN_TEXT = (
    "Two rules before you continue. Cite the source before the number, unless "
    "the recipient is internal. And never pad estimates in internal documents."
)

EXTRACTION_RESPONSE = json.dumps(
    {
        "beliefs": [
            {
                "rule": "Cite the source before the number.",
                "condition": "unless the recipient is internal",
                "predicate_hint": "citation policy",
                "quote": (
                    "Cite the source before the number, unless the recipient "
                    "is internal."
                ),
            },
            {
                "rule": "Never pad estimates in internal documents.",
                "condition": None,
                "predicate_hint": "estimation policy",
                "quote": "never pad estimates in internal documents",
            },
        ]
    }
)


def _extract_and_assert(store: JsonlEventStore) -> list:
    """The belief lane's half: extract through the real gates, append."""
    client = FakeLLMClient(responses={BELIEF_SCHEMA_NAME: EXTRACTION_RESPONSE})
    claims = extract_beliefs(
        TURN_TEXT,
        session_id="ses-loop-1",
        turn_id="t-2",
        client=client,
        observed_at=T_TURN,
    )
    assert len(claims) == 2, "both scripted beliefs must survive the gates"
    for claim in claims:
        store.append(
            Event.create(
                event_type=EventType.CLAIM_ASSERTED,
                occurred_at=T_TURN,
                payload={"claim": claim.to_dict()},
                actor="interview",
            )
        )
    return claims


class TestBeliefToDoctrine:
    def test_committed_beliefs_compile_with_quote_and_anchor(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        claims = _extract_and_assert(store)

        # Promotion goes through the one path that can write claim.committed.
        ApprovalFlow(store).submit(
            [
                ApprovalRequest(claim=c, decision=Decision.APPROVE)
                for c in claims
            ],
            occurred_at=T_APPROVE,
            session_id="ses-loop-1",
        )

        doctrine = compile_doctrine(
            fold(store.read_all()), audience=Audience.OWNER
        )
        assert {r.claim_id for r in doctrine.rules} == {
            c.claim_id for c in claims
        }
        by_id = {r.claim_id: r for r in doctrine.rules}
        for claim in claims:
            rule = by_id[claim.claim_id]
            # The verbatim quote, through the boundary — never a paraphrase.
            assert rule.quote == claim.quote_for(Audience.OWNER)
            # The turn anchor: where in the session this rule came from.
            assert rule.anchor == "turn:t-2"
            assert rule.source_id == "interview:ses-loop-1"
            assert rule.learned_at == T_TURN

        # The rendered prompt carries provenance for every rule.
        prompt = render_system_prompt(doctrine)
        for claim in claims:
            assert claim.claim_id in prompt

    def test_reject_recompile_rule_gone_fingerprint_moved(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        claims = _extract_and_assert(store)
        ApprovalFlow(store).submit(
            [
                ApprovalRequest(claim=c, decision=Decision.APPROVE)
                for c in claims
            ],
            occurred_at=T_APPROVE,
            session_id="ses-loop-1",
        )
        before = compile_doctrine(fold(store.read_all()), audience=Audience.OWNER)
        assert len(before.rules) == 2

        # Retraction is an append-only event through the same approval path —
        # nothing is edited, nothing is deleted from the log.
        rejected = claims[0]
        ApprovalFlow(store).submit(
            [ApprovalRequest(claim=rejected, decision=Decision.REJECT)],
            occurred_at=T_REJECT,
            session_id="ses-loop-1",
        )

        after = compile_doctrine(fold(store.read_all()), audience=Audience.OWNER)
        assert rejected.claim_id not in {r.claim_id for r in after.rules}
        assert {r.claim_id for r in after.rules} == {claims[1].claim_id}
        assert after.fingerprint() != before.fingerprint(), (
            "a retracted rule must move the doctrine fingerprint, or the "
            "determinism replay could not distinguish the two epochs"
        )
        # And the retracted rule's wording is out of the rendered prompt.
        assert rejected.claim_id not in render_system_prompt(after)

    def test_extraction_authors_the_rule_text_the_compiler_renders(self, tmp_path):
        """The extractor→compiler wording seam.

        The compiler never phrases anything: the imperative wording rendered
        into the prompt is authored at extraction (``extra["rule_text"]``).
        Without it the compiler falls back to a mechanical rendering — legal,
        but this test pins that the seam actually carries the authored form.
        """
        store = JsonlEventStore(tmp_path / "events.jsonl")
        claims = _extract_and_assert(store)
        ApprovalFlow(store).submit(
            [
                ApprovalRequest(claim=c, decision=Decision.APPROVE)
                for c in claims
            ],
            occurred_at=T_APPROVE,
        )
        doctrine = compile_doctrine(fold(store.read_all()), audience=Audience.OWNER)
        rules = {r.claim_id: r.rule for r in doctrine.rules}
        conditional = next(c for c in claims if c.extra.get("condition"))
        unconditional = next(c for c in claims if not c.extra.get("condition"))
        assert rules[conditional.claim_id] == (
            "Cite the source before the number. "
            "(unless the recipient is internal)"
        )
        assert rules[unconditional.claim_id] == (
            "Never pad estimates in internal documents."
        )

    def test_beliefs_are_about_the_user_entity(self, tmp_path):
        """Blocking-key integrity: everything in this loop is about ent:user.

        Contradiction detection blocks on subject ∪ hint; a belief minted
        under a different subject would silently never collide with anything.
        """
        store = JsonlEventStore(tmp_path / "events.jsonl")
        for claim in _extract_and_assert(store):
            assert claim.subject_id == USER_ENTITY_ID
