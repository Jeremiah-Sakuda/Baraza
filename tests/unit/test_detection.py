"""BAR-320 — on-write detection is blocked, gated, capped, and bounded.

The design claim is arithmetic: one bounded model call per claim written, not
one per pair. That claim is only true if four things hold, and each is asserted
here rather than described in a docstring.

* **Blocked.** Only claims sharing subject ∪ object ∪ ``predicate_hint`` enter
  the block. Everything else in the corpus is never looked at.
* **Retracted claims are gone.** A rejected claim leaves the retrieval pool, so
  it cannot contribute to a contradiction again.
* **Temporally gated.** The consecutive-fiscal-year pair — the single largest
  source of false positives — is removed before any model sees it, and it stays
  removed when the two boundary instants are serialized under different UTC
  offsets.
* **Capped.** Fifty candidates still submit twenty, and still cost one call.

No test in this module touches Vertex. The adjudicator is a scripted fake, so a
failure here is a failure in Baraza rather than in somebody's quota.
"""

from __future__ import annotations

import json

from baraza.reconcile.detect import MAX_RETRIEVED, ContradictionDetector, build_block
from baraza.schema.claim import Tier
from baraza.schema.temporal import intervals_overlap, to_epoch_millis
from baraza_testkit import FakeLLMClient, claim

NO_CONTRADICTIONS = json.dumps({"contradictions": []})

# Two consecutive fiscal years whose shared boundary is serialized under
# different offsets. As text, FY27's start sorts before FY26's end, which is
# exactly the reading that would fire the false positive.
FY26_START = "2025-07-01T00:00:00Z"
FY26_END = "2026-07-01T00:00:00Z"
FY27_START = "2026-06-30T19:00:00-05:00"
FY27_END = "2027-07-01T00:00:00Z"


def _signing_claim(**overrides):
    defaults = dict(
        subject="ent:treasurer",
        predicate="signing_threshold",
        hint="signing authority",
        valid_from=FY26_START,
        valid_until=FY26_END,
    )
    defaults.update(overrides)
    return claim(**defaults)


class TestBlocking:
    def test_same_subject_and_hint_is_in_the_block(self):
        new = _signing_claim(quote="a", locator="p.1")
        other = _signing_claim(quote="b", locator="p.2")
        assert build_block(new, [other]) == [other]

    def test_same_subject_different_hint_is_out(self):
        new = _signing_claim(quote="a", locator="p.1")
        unrelated = _signing_claim(
            quote="b", locator="p.2", hint="meeting time"
        )
        assert build_block(new, [unrelated]) == []

    def test_different_subject_is_out(self):
        new = _signing_claim(quote="a", locator="p.1")
        elsewhere = _signing_claim(
            quote="b", locator="p.2", subject="ent:social-committee"
        )
        assert build_block(new, [elsewhere]) == []

    def test_an_object_entity_match_is_enough(self):
        """Blocking is on subject ∪ object, so a claim pointing *at* the subject
        lands in the same block as one *about* it."""
        new = _signing_claim(quote="a", locator="p.1")
        pointing_at = _signing_claim(
            quote="b",
            locator="p.2",
            subject="ent:chair",
            object_id="ent:treasurer",
            object_literal=None,
        )
        assert build_block(new, [pointing_at]) == [pointing_at]

    def test_the_claim_never_blocks_with_itself(self):
        new = _signing_claim()
        assert build_block(new, [new]) == []

    def test_hint_matching_ignores_case_and_padding(self):
        new = _signing_claim(quote="a", locator="p.1")
        other = _signing_claim(quote="b", locator="p.2", hint="  Signing Authority ")
        assert build_block(new, [other]) == [other]

    def test_alias_edges_resolve_at_query_time(self):
        """Identity resolves at query time; the claims themselves are untouched."""
        new = _signing_claim(quote="a", locator="p.1")
        aliased = _signing_claim(
            quote="b", locator="p.2", subject="ent:club-treasurer"
        )
        assert build_block(new, [aliased]) == []
        assert build_block(
            new, [aliased], aliases={"ent:club-treasurer": "ent:treasurer"}
        ) == [aliased]
        # And the alias edge is non-destructive: the claim kept its own ID.
        assert aliased.subject_id == "ent:club-treasurer"


class TestRetractionLeavesTheBlock:
    def test_a_rejected_claim_is_excluded(self):
        new = _signing_claim(quote="a", locator="p.1")
        retracted = _signing_claim(quote="b", locator="p.2", tier=Tier.REJECTED)
        live = _signing_claim(quote="c", locator="p.3", tier=Tier.COMMITTED)

        block = build_block(new, [retracted, live])
        assert block == [live]
        assert retracted.in_retrieval_pool is False

    def test_detection_never_sees_a_rejected_claim(self):
        new = _signing_claim(quote="a", locator="p.1")
        retracted = _signing_claim(quote="b", locator="p.2", tier=Tier.REJECTED)
        client = FakeLLMClient()  # unscripted: a model call fails the test

        result = ContradictionDetector(client).detect(new, [retracted])

        assert result.block_size == 0
        assert result.skipped_reason == "empty block"
        assert client.calls == []


class TestTemporalGate:
    def test_the_fiscal_year_pair_does_not_survive_the_gate(self):
        fy26 = _signing_claim(quote="up to 500", locator="p.4")
        fy27 = _signing_claim(
            quote="up to 250",
            locator="p.9",
            valid_from=FY27_START,
            valid_until=FY27_END,
        )
        client = FakeLLMClient()  # unscripted: reaching the model is the failure

        result = ContradictionDetector(client).detect(fy27, [fy26])

        assert result.block_size == 1
        assert result.after_temporal_gate == 0
        assert result.skipped_reason == "no temporal overlap"
        assert result.model_calls == 0
        assert result.contradictions == []
        assert client.calls == []

    def test_the_boundary_would_have_overlapped_under_a_string_comparison(self):
        """Why this pair is the fixture: as text it looks like an overlap.

        ``2026-06-30T19:00:00-05:00`` sorts before ``2026-07-01T00:00:00Z``, so
        a string comparison concludes FY27 began before FY26 ended and reports a
        contradiction between two officers who never served at the same time.
        """
        assert FY27_START < FY26_END  # the naive reading: overlap
        assert to_epoch_millis(FY27_START) == to_epoch_millis(FY26_END)
        assert (
            intervals_overlap(
                to_epoch_millis(FY26_START),
                to_epoch_millis(FY26_END),
                to_epoch_millis(FY27_START),
                to_epoch_millis(FY27_END),
            )
            is False
        )

    def test_genuinely_concurrent_claims_do_survive_the_gate(self):
        """The gate must not be a blanket suppressor."""
        a = _signing_claim(quote="up to 500", locator="p.4")
        b = _signing_claim(quote="up to 250", locator="msg:1743689400")
        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})

        result = ContradictionDetector(client).detect(b, [a])

        assert result.after_temporal_gate == 1
        assert result.submitted == 1
        assert result.model_calls == 1

    def test_an_open_ended_claim_still_reaches_the_adjudicator(self):
        still_in_force = _signing_claim(
            quote="the ceiling has always been 500",
            locator="p.4",
            valid_from=FY26_START,
            valid_until=None,
        )
        later = _signing_claim(
            quote="up to 250",
            locator="p.9",
            valid_from=FY27_START,
            valid_until=FY27_END,
        )
        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})

        result = ContradictionDetector(client).detect(later, [still_in_force])
        assert result.after_temporal_gate == 1


class TestTheCap:
    def _fifty_candidates(self):
        return [
            _signing_claim(
                quote=f"ceiling was {400 + index} that year",
                locator=f"msg:{1743689400 + index}",
                observed_at=f"2026-03-{(index % 28) + 1:02d}T10:00:00Z",
            )
            for index in range(50)
        ]

    def test_fifty_candidates_submit_at_most_twenty(self):
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        pool = self._fifty_candidates()
        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})

        result = ContradictionDetector(client).detect(new, pool)

        assert result.block_size == 50
        assert result.after_temporal_gate == 50
        assert result.submitted <= 20
        assert result.submitted == MAX_RETRIEVED

    def test_the_cost_is_one_call_regardless_of_block_size(self):
        """The BAR-320 arithmetic: bounded per write, not per pair."""
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})

        result = ContradictionDetector(client).detect(new, self._fifty_candidates())

        assert result.model_calls == 1
        assert len(client.calls) == 1

    def test_only_the_submitted_claims_appear_in_the_prompt(self):
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        pool = self._fifty_candidates()
        client = FakeLLMClient({"contradictions.v1": NO_CONTRADICTIONS})

        ContradictionDetector(client).detect(new, pool)

        prompt = client.calls_for("contradictions.v1")[0].prompt
        mentioned = sum(1 for c in pool if c.claim_id in prompt)
        assert mentioned == MAX_RETRIEVED


class TestAdjudicationResponse:
    def test_a_hallucinated_claim_id_is_discarded(self):
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        real = _signing_claim(quote="ceiling was 500", locator="p.4")
        client = FakeLLMClient(
            {
                "contradictions.v1": json.dumps(
                    {
                        "contradictions": [
                            {
                                "claim_id": "clm_0000000000000000000000000000dead",
                                "confidence": 0.99,
                                "rationale": "invented",
                            }
                        ]
                    }
                )
            }
        )

        result = ContradictionDetector(client).detect(new, [real])

        assert result.submitted == 1
        assert result.contradictions == []

    def test_a_real_finding_becomes_a_contradiction(self):
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        real = _signing_claim(quote="ceiling was 500", locator="p.4")
        client = FakeLLMClient(
            {
                "contradictions.v1": json.dumps(
                    {
                        "contradictions": [
                            {
                                "claim_id": real.claim_id,
                                "confidence": 0.8,
                                "rationale": "Two ceilings for one period.",
                            }
                        ]
                    }
                )
            }
        )

        result = ContradictionDetector(client).detect(new, [real])

        assert len(result.contradictions) == 1
        found = result.contradictions[0]
        assert sorted(found.claim_ids) == sorted([new.claim_id, real.claim_id])
        assert found.confidence == 0.8

    def test_a_mix_of_real_and_hallucinated_keeps_only_the_real(self):
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        real = _signing_claim(quote="ceiling was 500", locator="p.4")
        client = FakeLLMClient(
            {
                "contradictions.v1": json.dumps(
                    {
                        "contradictions": [
                            {"claim_id": "clm_not_in_the_prompt", "confidence": 1.0,
                             "rationale": "invented"},
                            {"claim_id": real.claim_id, "confidence": 0.7,
                             "rationale": "Two ceilings for one period."},
                        ]
                    }
                )
            }
        )

        result = ContradictionDetector(client).detect(new, [real])
        assert len(result.contradictions) == 1

    def test_an_unparseable_response_fails_closed(self):
        """A malformed adjudication is a missed contradiction, never a fabricated
        one: the ledger stays honest and the claim is re-examined tonight."""
        new = _signing_claim(quote="ceiling was 250", locator="p.9")
        real = _signing_claim(quote="ceiling was 500", locator="p.4")
        client = FakeLLMClient({"contradictions.v1": "not json at all"})

        result = ContradictionDetector(client).detect(new, [real])

        assert result.contradictions == []
        assert result.skipped_reason == "adjudication response unparseable"
