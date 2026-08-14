"""Contradictions — what the corpus disagrees with itself about.

A contradiction is detected **on write** (BAR-320): when a claim is asserted,
the reconciler retrieves at most twenty existing claims sharing its blocking key
(subject ∪ object entities ∪ ``predicate_hint``), gates them on epoch interval
overlap, and asks Gemini once whether any pair genuinely conflicts. There is no
O(n²) sweep over the corpus, and the arithmetic that makes that unnecessary is
stated in the README rather than implied.

The visibility rule that governs this file: a contradiction may **exist**
because of a claim the current audience cannot read. It may never **quote** that
claim to that audience. :meth:`Contradiction.render_for` is the only renderer,
and it substitutes a placeholder for every unreadable side.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from baraza.schema.claim import Claim
from baraza.schema.temporal import EpochMillis, to_epoch_millis
from baraza.schema.visibility import Audience, readable_by

__all__ = ["ContradictionStatus", "Contradiction", "RenderedContradiction"]


class ContradictionStatus(StrEnum):
    OPEN = "open"
    """On the ledger and eligible for the agenda."""

    RESOLVED = "resolved"
    """Answered in an interview and approved. Retired from every future agenda
    — this is the closed loop that makes each interview shorter than the last."""

    RETRACTED = "retracted"
    """One side was rejected, so the disagreement no longer exists."""


@dataclass(frozen=True, slots=True)
class RenderedContradiction:
    """Audience-safe projection, ready to become an interview question."""

    contradiction_id: str
    subject_id: str
    predicate_hint: str
    summary: str
    sides: list[str]
    fully_readable: bool
    """False when at least one side was redacted. The interviewer refuses to
    build a citation-grounded question from a partially redacted contradiction
    and downgrades it to an open-ended prompt instead."""


@dataclass(frozen=True, slots=True)
class Contradiction:
    """A detected disagreement between two or more claims."""

    contradiction_id: str
    subject_id: str
    predicate_hint: str
    claim_ids: list[str]
    detected_at: EpochMillis
    confidence: float
    rationale: str
    """Gemini's one-sentence account of *why* these conflict. Shown in the
    ledger so a human can audit the detector's reasoning rather than trust it."""

    status: ContradictionStatus = ContradictionStatus.OPEN
    resolved_at: EpochMillis | None = None
    resolving_session_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        *,
        subject_id: str,
        predicate_hint: str,
        claim_ids: Sequence[str],
        detected_at: Any,
        confidence: float,
        rationale: str,
        extra: dict[str, Any] | None = None,
    ) -> Contradiction:
        ordered = sorted(set(claim_ids))
        if len(ordered) < 2:
            raise ValueError(
                "a contradiction needs at least two distinct claims, got "
                f"{ordered!r}"
            )
        return Contradiction(
            contradiction_id=Contradiction.deterministic_id(
                subject_id=subject_id,
                predicate_hint=predicate_hint,
                claim_ids=ordered,
            ),
            subject_id=subject_id,
            predicate_hint=predicate_hint,
            claim_ids=ordered,
            detected_at=to_epoch_millis(detected_at, field="detected_at"),
            confidence=float(confidence),
            rationale=rationale,
            extra=dict(extra or {}),
        )

    @staticmethod
    def deterministic_id(
        *, subject_id: str, predicate_hint: str, claim_ids: Sequence[str]
    ) -> str:
        """Content-addressed, and stable under claim reordering.

        The same disagreement detected twice — on re-ingest, or from either
        side's write — collapses to one ledger row rather than two.
        """
        digest = hashlib.sha256(
            "\x1f".join(
                [subject_id, predicate_hint.strip().lower(), *sorted(claim_ids)]
            ).encode("utf-8")
        ).hexdigest()
        return f"ctr_{digest[:32]}"

    @property
    def is_open(self) -> bool:
        return self.status is ContradictionStatus.OPEN

    def render_for(
        self, claims: dict[str, Claim], audience: Audience
    ) -> RenderedContradiction:
        """Project to text that ``audience`` is permitted to see.

        Each side is rendered from its claim's quote if — and only if —
        ``readable_by`` allows it. Unreadable sides become a placeholder that
        acknowledges the conflict's existence without disclosing its content.
        That asymmetry is the point: the ledger stays honest about *how many*
        disagreements exist while the boundary stays closed about *what they
        say*.
        """
        sides: list[str] = []
        fully_readable = True

        for claim_id in self.claim_ids:
            claim = claims.get(claim_id)
            if claim is None:
                fully_readable = False
                sides.append("[claim not present in this fold]")
                continue
            if not readable_by(claim, audience):
                fully_readable = False
                sides.append(
                    "[a record outside your access asserts a conflicting value "
                    "here; counted, not quoted]"
                )
                continue
            quote = claim.quote_for(audience)
            if not quote:
                # Defensive: readable_by said yes but no text came back. Treat
                # as unreadable rather than rendering an empty citation.
                fully_readable = False
                sides.append("[citation unavailable]")
                continue
            sides.append(f"{claim.anchor.key()}: “{quote}”")

        return RenderedContradiction(
            contradiction_id=self.contradiction_id,
            subject_id=self.subject_id,
            predicate_hint=self.predicate_hint,
            summary=self.rationale if fully_readable else
            "Sources disagree here, but part of the record is outside your access.",
            sides=sides,
            fully_readable=fully_readable,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "subject_id": self.subject_id,
            "predicate_hint": self.predicate_hint,
            "claim_ids": list(self.claim_ids),
            "detected_at": self.detected_at,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "status": self.status.value,
            "resolved_at": self.resolved_at,
            "resolving_session_id": self.resolving_session_id,
            "extra": dict(self.extra),
        }

    @staticmethod
    def from_dict(payload: dict[str, Any]) -> Contradiction:
        return Contradiction(
            contradiction_id=payload["contradiction_id"],
            subject_id=payload["subject_id"],
            predicate_hint=payload.get("predicate_hint", ""),
            claim_ids=list(payload.get("claim_ids") or []),
            detected_at=to_epoch_millis(payload["detected_at"], field="detected_at"),
            confidence=float(payload.get("confidence", 0.0)),
            rationale=payload.get("rationale", ""),
            status=ContradictionStatus(
                payload.get("status", ContradictionStatus.OPEN.value)
            ),
            resolved_at=(
                None
                if payload.get("resolved_at") is None
                else to_epoch_millis(payload["resolved_at"], field="resolved_at")
            ),
            resolving_session_id=payload.get("resolving_session_id"),
            extra=dict(payload.get("extra") or {}),
        )
