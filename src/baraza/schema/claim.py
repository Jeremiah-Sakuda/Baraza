"""The claim — Baraza's unit of institutional memory.

A claim is one assertion, carrying the citation that justifies it. Citations are
load-bearing: ``quote`` is mandatory, the anchor must reference a real
registered source location, and a fabricated or unresolvable anchor is a stop
condition rather than a warning.

The quote is deliberately **not** a plain attribute. It is stored under
``_quote_protected`` and reachable only through :meth:`Claim.quote_for`, which
routes through ``readable_by``. Code that writes ``claim.quote`` raises
``AttributeError`` at the access site instead of silently rendering private
testimony to the wrong audience. ``scripts/compliance.py`` additionally fails
the build if ``_quote_protected`` is referenced anywhere outside
``src/baraza/schema/``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from baraza.schema.temporal import EpochMillis, to_epoch_millis, to_epoch_millis_optional
from baraza.schema.visibility import Audience, Visibility, readable_by

__all__ = ["Tier", "Provenance", "Anchor", "Claim", "CitationError"]


class Tier(str, Enum):
    """A claim's standing in the record.

    ``REJECTED`` is a tier and it **retracts**: a rejected claim leaves the
    retrieval pool, the disputed ledger, and every future agenda, permanently.
    It is not a soft flag and it is not reversible by omission — reinstating a
    rejected claim requires a superseding event that says so.
    """

    PENDING = "pending"
    COMMITTED = "committed"
    REJECTED = "rejected"


class Provenance(str, Enum):
    """Where the claim came from. Extractors may only produce ``CORPUS``."""

    CORPUS = "corpus"
    INTERVIEW = "interview"


class CitationError(ValueError):
    """A claim carries no quote, or an anchor that does not resolve.

    Per AGENTS.md this is a stop condition. It is raised at construction so an
    uncited claim can never reach the log in the first place.
    """


@dataclass(frozen=True, slots=True)
class Anchor:
    """A pointer into a registered source location.

    ``source_id`` names a document in the ingestion registry. ``locator`` is
    format-specific and human-checkable: ``"p.4 ¶2"`` for a scanned PDF,
    ``"msg:1713470400"`` for a chat export, ``"Sheet1!B14"`` for a spreadsheet,
    ``"turn:t-14"`` for interview testimony.
    """

    source_id: str
    locator: str
    checksum: Optional[str] = None
    """SHA-256 of the source bytes at ingest time. ``make verify-anchors``
    re-resolves every anchor and compares; drift is a failure, not a warning."""

    def key(self) -> str:
        return f"{self.source_id}#{self.locator}"


@dataclass(frozen=True, slots=True)
class Claim:
    """One citation-bearing assertion.

    Construct through :meth:`create` rather than the raw initializer — it
    normalizes instants, enforces the citation requirement, and applies the
    private-by-default visibility rule.
    """

    claim_id: str
    subject_id: str
    predicate: str
    predicate_hint: str
    object_id: Optional[str]
    object_literal: Optional[str]
    _quote_protected: str
    anchor: Anchor
    observed_at: EpochMillis
    valid_from: Optional[EpochMillis]
    valid_until: Optional[EpochMillis]
    tier: Tier
    visibility: Visibility
    provenance: Provenance
    author_id: Optional[str] = None
    session_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # ---------------------------------------------------------------- factory

    @staticmethod
    def create(
        *,
        subject_id: str,
        predicate: str,
        predicate_hint: str,
        quote: str,
        anchor: Anchor,
        observed_at: Any,
        object_id: Optional[str] = None,
        object_literal: Optional[str] = None,
        valid_from: Any = None,
        valid_until: Any = None,
        tier: Tier = Tier.PENDING,
        visibility: Optional[Visibility] = None,
        provenance: Provenance = Provenance.CORPUS,
        author_id: Optional[str] = None,
        session_id: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> "Claim":
        """Build a claim, enforcing every construction-time invariant."""
        if not quote or not quote.strip():
            raise CitationError(
                f"claim on subject {subject_id!r} predicate {predicate!r} carries "
                "no quote. Citations are load-bearing; an uncited claim is a stop "
                "condition, not a degraded claim."
            )
        if not anchor.source_id or not anchor.locator:
            raise CitationError(
                f"claim on subject {subject_id!r} carries an incomplete anchor "
                f"{anchor!r}. Anchors reference only real, registered source "
                "locations."
            )
        if object_id is None and object_literal is None:
            raise ValueError(
                f"claim on subject {subject_id!r} predicate {predicate!r} has "
                "neither an object entity nor an object literal"
            )

        # BAR-002 default: visibility is set at append time, never unset, and
        # the unset case resolves to the tier that leaks nothing.
        resolved_visibility = Visibility.PRIVATE if visibility is None else visibility

        observed = to_epoch_millis(observed_at, field="observed_at")
        v_from = (
            None
            if valid_from is None
            else to_epoch_millis(valid_from, field="valid_from")
        )
        v_until = (
            None
            if valid_until is None
            else to_epoch_millis(valid_until, field="valid_until")
        )
        if v_from is not None and v_until is not None and v_from > v_until:
            raise ValueError(
                f"claim on {subject_id!r} has valid_from after valid_until "
                f"({v_from} > {v_until})"
            )

        claim_id = Claim.deterministic_id(
            subject_id=subject_id,
            predicate=predicate,
            object_key=object_id or object_literal or "",
            anchor_key=anchor.key(),
            quote=quote,
        )

        return Claim(
            claim_id=claim_id,
            subject_id=subject_id,
            predicate=predicate,
            predicate_hint=predicate_hint,
            object_id=object_id,
            object_literal=object_literal,
            _quote_protected=quote.strip(),
            anchor=anchor,
            observed_at=observed,
            valid_from=v_from,
            valid_until=v_until,
            tier=tier,
            visibility=resolved_visibility,
            provenance=provenance,
            author_id=author_id,
            session_id=session_id,
            extra=dict(extra or {}),
        )

    @staticmethod
    def deterministic_id(
        *,
        subject_id: str,
        predicate: str,
        object_key: str,
        anchor_key: str,
        quote: str,
    ) -> str:
        """Content-addressed claim ID.

        Deterministic so that re-ingesting the same corpus produces the same log
        — a precondition for the fold-stability property test and for
        idempotent replays of a failed ingestion Job.
        """
        digest = hashlib.sha256(
            "\x1f".join(
                [subject_id, predicate, object_key, anchor_key, quote.strip()]
            ).encode("utf-8")
        ).hexdigest()
        return f"clm_{digest[:32]}"

    # ------------------------------------------------------- guarded readers

    def quote_for(self, audience: Audience) -> Optional[str]:
        """The only way to read the quote.

        Returns the text if ``audience`` may see it, otherwise ``None``. A
        caller that ignores the ``None`` renders an empty citation, which the
        interviewer treats as a missing citation and refuses — the failure is
        visible rather than silent.
        """
        if not readable_by(self, audience):
            return None
        return self._quote_protected

    def object_for(self, audience: Audience) -> Optional[str]:
        """The object literal, under the same predicate."""
        if not readable_by(self, audience):
            return None
        return self.object_literal

    def digest(self) -> str:
        """Audience-independent fingerprint of the quote, safe to log.

        Lets traces and audit logs prove which text was used without
        reproducing it — OpenTelemetry spans carry this, never the quote.
        """
        return hashlib.sha256(self._quote_protected.encode("utf-8")).hexdigest()[:16]

    # ------------------------------------------------------------ predicates

    @property
    def in_retrieval_pool(self) -> bool:
        """Whether the claim may be retrieved at all.

        Independent of visibility: this is the *retraction* axis. A rejected
        claim is gone from retrieval, the ledger, and every future agenda
        regardless of who is asking.
        """
        return self.tier is not Tier.REJECTED

    @property
    def blocking_key(self) -> str:
        """The BAR-320 blocking key: subject plus normalized predicate hint.

        Contradiction detection is on-write and blocked; there is no O(n²)
        sweep over the corpus.
        """
        return f"{self.subject_id}|{self.predicate_hint.strip().lower()}"

    # --------------------------------------------------------- serialization

    def to_dict(self) -> Dict[str, Any]:
        """Firestore/JSON representation.

        Instants serialize as integer millis, never as ISO strings — the stored
        form is the comparison form, so a reader cannot accidentally sort text.
        """
        return {
            "claim_id": self.claim_id,
            "subject_id": self.subject_id,
            "predicate": self.predicate,
            "predicate_hint": self.predicate_hint,
            "object_id": self.object_id,
            "object_literal": self.object_literal,
            "quote": self._quote_protected,
            "anchor": {
                "source_id": self.anchor.source_id,
                "locator": self.anchor.locator,
                "checksum": self.anchor.checksum,
            },
            "observed_at": self.observed_at,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
            "tier": self.tier.value,
            "visibility": self.visibility.value,
            "provenance": self.provenance.value,
            "author_id": self.author_id,
            "session_id": self.session_id,
            "extra": dict(self.extra),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Claim":
        """Rehydrate from storage.

        Note the visibility default applies here too: a stored document missing
        the field reads back as ``PRIVATE``, not as unset.
        """
        anchor_payload = payload.get("anchor") or {}
        anchor = Anchor(
            source_id=anchor_payload.get("source_id", ""),
            locator=anchor_payload.get("locator", ""),
            checksum=anchor_payload.get("checksum"),
        )
        raw_visibility = payload.get("visibility")
        try:
            visibility = (
                Visibility(raw_visibility) if raw_visibility else Visibility.PRIVATE
            )
        except ValueError:
            visibility = Visibility.PRIVATE

        return Claim(
            claim_id=payload["claim_id"],
            subject_id=payload["subject_id"],
            predicate=payload["predicate"],
            predicate_hint=payload.get("predicate_hint", ""),
            object_id=payload.get("object_id"),
            object_literal=payload.get("object_literal"),
            _quote_protected=payload["quote"],
            anchor=anchor,
            observed_at=to_epoch_millis(payload["observed_at"], field="observed_at"),
            valid_from=(
                None
                if payload.get("valid_from") is None
                else to_epoch_millis(payload["valid_from"], field="valid_from")
            ),
            valid_until=(
                None
                if payload.get("valid_until") is None
                else to_epoch_millis(payload["valid_until"], field="valid_until")
            ),
            tier=Tier(payload.get("tier", Tier.PENDING.value)),
            visibility=visibility,
            provenance=Provenance(payload.get("provenance", Provenance.CORPUS.value)),
            author_id=payload.get("author_id"),
            session_id=payload.get("session_id"),
            extra=dict(payload.get("extra") or {}),
        )
