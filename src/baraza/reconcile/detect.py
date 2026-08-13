"""BAR-320 — on-write contradiction detection.

The arithmetic first, because it is the whole design.

A decade of a student organization's records yields on the order of 3,000
claims. An all-pairs contradiction sweep is ~4.5 million comparisons, and at one
model call per comparison it is not a system, it is a bill. So detection is
**on-write and blocked**:

1. A claim is asserted.
2. Retrieve only claims sharing its **blocking key** — subject entity ∪ object
   entities ∪ ``predicate_hint``, with alias edges resolved at query time.
   Typical block size in this corpus: single digits.
3. **Temporally gate** the block on epoch interval overlap (BAR-309). Two
   claims about consecutive fiscal years cannot contradict each other, and this
   gate removes the single largest source of false positives before any model
   sees them.
4. Cap the survivors at **20**, ranked by recency and confidence.
5. Make **one** call, ~3k tokens, asking which of the retrieved claims actually
   conflict with the new one.

That is one bounded call per claim written, not per pair. There is no sweep,
there is no vector database, and the top-k that does happen is brute force over
a few thousand in-memory claim vectors — which at this cardinality is
microseconds and does not deserve infrastructure.

**The boundary rule that governs this module.** The reconciler is permitted to
*count* a claim the current audience cannot read toward a contradiction's
existence. It is never permitted to render that claim's text into a question for
that audience. Detection therefore runs over the full retrieval pool while
rendering routes through ``Contradiction.render_for``, which redacts per
audience. Those are two different operations on purpose.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Set

from baraza.llm import LLMClient
from baraza.schema.claim import Claim
from baraza.schema.contradiction import Contradiction
from baraza.schema.temporal import intervals_overlap
from baraza.schema.visibility import Audience

__all__ = [
    "MAX_RETRIEVED",
    "DetectionResult",
    "ContradictionDetector",
    "build_block",
]

MAX_RETRIEVED = 20
"""Hard cap on claims entering a single adjudication call.

Not a tuning parameter — a cost and latency contract. Exceeding it would turn a
bounded per-write cost into an unbounded one, so the cap is asserted in
``tests/unit/test_detection.py`` rather than trusted.
"""

_SYSTEM = """\
You are an archivist adjudicating whether records disagree.

You will be given ONE new claim and a small set of existing claims about the \
same subject and relation. For each existing claim, decide whether it genuinely \
CONTRADICTS the new claim.

A genuine contradiction means both cannot be true of the same subject over the \
same period. Be strict:

* Different values for the same thing over the same period → contradiction.
* Different values over DIFFERENT periods → NOT a contradiction. This is the \
most common false positive; consecutive terms, fiscal years, and officer \
tenures are changes over time, not disagreements.
* A more specific statement refining a general one → NOT a contradiction.
* A statement about a different subject that merely uses similar words → NOT a \
contradiction.
* Silence is not disagreement. A record that does not mention something does \
not contradict one that does.

For each contradiction you find, give a one-sentence rationale naming the \
specific incompatibility. An archivist reading your rationale must be able to \
check it against the two quotes without trusting you.
"""

_PROMPT = """\
NEW CLAIM
  id:        {new_id}
  subject:   {new_subject}
  relation:  {new_predicate}
  asserts:   {new_object}
  period:    {new_period}
  quote:     "{new_quote}"

EXISTING CLAIMS ABOUT THE SAME SUBJECT AND RELATION
{candidates}

Return JSON only:

{{
  "contradictions": [
    {{
      "claim_id": "the id of the existing claim that conflicts",
      "confidence": 0.0 to 1.0,
      "rationale": "one sentence naming the specific incompatibility"
    }}
  ]
}}

Return an empty list if nothing genuinely conflicts. An empty list is the \
correct and common answer.
"""


@dataclass(slots=True)
class DetectionResult:
    """One detection pass over one newly written claim."""

    claim_id: str
    block_size: int = 0
    after_temporal_gate: int = 0
    submitted: int = 0
    contradictions: List[Contradiction] = field(default_factory=list)
    model_calls: int = 0
    skipped_reason: Optional[str] = None

    def describe(self) -> str:
        if self.skipped_reason:
            return (
                f"  {self.claim_id[:16]}… block={self.block_size} "
                f"→ skipped ({self.skipped_reason})"
            )
        return (
            f"  {self.claim_id[:16]}… block={self.block_size} "
            f"→ gated={self.after_temporal_gate} "
            f"→ submitted={self.submitted} "
            f"→ found={len(self.contradictions)} "
            f"({self.model_calls} model call{'s' if self.model_calls != 1 else ''})"
        )


def build_block(
    new_claim: Claim,
    pool: Iterable[Claim],
    *,
    aliases: Optional[Dict[str, str]] = None,
) -> List[Claim]:
    """Retrieve candidates sharing the new claim's blocking key.

    Blocking is on subject ∪ object entities ∪ ``predicate_hint``, with alias
    edges resolved **at query time** — never by rewriting the claims. Two claims
    written about ``ent:treasurer`` and ``ent:club-treasurer`` land in the same
    block if a confirmed ``sameAs`` edge connects them, and stop doing so the
    moment a superseding event removes it.
    """
    alias_map = aliases or {}

    def canonical(entity_id: Optional[str]) -> Optional[str]:
        if entity_id is None:
            return None
        seen: Set[str] = set()
        current = entity_id
        while current in alias_map and current not in seen:
            seen.add(current)
            current = alias_map[current]
        return current

    target_entities = {
        e for e in (canonical(new_claim.subject_id), canonical(new_claim.object_id)) if e
    }
    target_hint = new_claim.predicate_hint.strip().lower()

    block: List[Claim] = []
    for candidate in pool:
        if candidate.claim_id == new_claim.claim_id:
            continue
        # Retraction is checked here, not at render time: a rejected claim
        # leaves the retrieval pool permanently, so it can never contribute to
        # a contradiction again.
        if not candidate.in_retrieval_pool:
            continue
        if candidate.predicate_hint.strip().lower() != target_hint:
            continue
        candidate_entities = {
            e
            for e in (canonical(candidate.subject_id), canonical(candidate.object_id))
            if e
        }
        if not (candidate_entities & target_entities):
            continue
        block.append(candidate)
    return block


class ContradictionDetector:
    """One bounded model call per claim written."""

    def __init__(self, client: LLMClient, *, max_retrieved: int = MAX_RETRIEVED):
        self.client = client
        self.max_retrieved = max_retrieved

    def detect(
        self,
        new_claim: Claim,
        pool: Sequence[Claim],
        *,
        aliases: Optional[Dict[str, str]] = None,
    ) -> DetectionResult:
        result = DetectionResult(claim_id=new_claim.claim_id)

        block = build_block(new_claim, pool, aliases=aliases)
        result.block_size = len(block)
        if not block:
            result.skipped_reason = "empty block"
            return result

        # Temporal gate. Claims whose validity intervals cannot overlap cannot
        # contradict each other, and removing them here is what keeps the
        # FY24/FY25 pair out of the ledger without asking a model about it.
        gated = [
            candidate
            for candidate in block
            if intervals_overlap(
                new_claim.valid_from,
                new_claim.valid_until,
                candidate.valid_from,
                candidate.valid_until,
            )
        ]
        result.after_temporal_gate = len(gated)
        if not gated:
            result.skipped_reason = "no temporal overlap"
            return result

        # Rank and cap. Recency first — a recent record is more likely to be the
        # one an interview should ask about — then confidence in the extraction.
        ranked = sorted(
            gated,
            key=lambda c: (-c.observed_at, c.claim_id),
        )[: self.max_retrieved]
        result.submitted = len(ranked)

        candidates_text = "\n".join(
            f"""  - id: {c.claim_id}
    asserts: {c.object_literal or c.object_id}
    period:  {_period(c)}
    quote:   "{_full_quote(c)}\""""
            for c in ranked
        )

        prompt = _PROMPT.format(
            new_id=new_claim.claim_id,
            new_subject=new_claim.subject_id,
            new_predicate=new_claim.predicate,
            new_object=new_claim.object_literal or new_claim.object_id,
            new_period=_period(new_claim),
            new_quote=_full_quote(new_claim),
            candidates=candidates_text,
        )

        response = self.client.generate(
            role="reasoning",
            prompt=prompt,
            system=_SYSTEM,
            schema_name="contradictions.v1",
            temperature=0.0,
        )
        result.model_calls = 1

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError):
            # A malformed adjudication is a missed contradiction, not a false
            # one. Failing closed here is the safe direction: the ledger stays
            # honest, and the claim is re-examined on the next nightly run.
            result.skipped_reason = "adjudication response unparseable"
            return result

        by_id = {c.claim_id: c for c in ranked}
        for finding in payload.get("contradictions") or []:
            other = by_id.get(finding.get("claim_id"))
            if other is None:
                # The model named a claim that was not in the prompt. Discard
                # rather than repair — a hallucinated id is a signal, not noise.
                continue
            result.contradictions.append(
                Contradiction.create(
                    subject_id=new_claim.subject_id,
                    predicate_hint=new_claim.predicate_hint,
                    claim_ids=[new_claim.claim_id, other.claim_id],
                    detected_at=max(new_claim.observed_at, other.observed_at),
                    confidence=float(finding.get("confidence", 0.0)),
                    rationale=str(finding.get("rationale", "")).strip(),
                    extra={"detector": "on-write", "block_size": result.block_size},
                )
            )
        return result


def _period(claim: Claim) -> str:
    """Human-readable interval for the prompt. Serialization, not comparison."""
    from baraza.schema.temporal import to_iso

    start = to_iso(claim.valid_from) if claim.valid_from is not None else "unbounded"
    end = to_iso(claim.valid_until) if claim.valid_until is not None else "unbounded"
    return f"{start} .. {end}"


def _full_quote(claim: Claim) -> str:
    """The quote, for the detector's own reasoning.

    Detection runs as the ``OWNER`` audience because the reconciler must be able
    to count every claim in the pool, including private ones. This is the single
    place that is true, it is deliberate, and it is why rendering is a separate
    operation: ``Contradiction.render_for`` re-applies the boundary for whoever
    is actually going to read the question.
    """
    return (claim.quote_for(Audience.OWNER) or "").replace('"', "'")
