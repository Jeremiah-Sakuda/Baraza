"""The approval flow — the only path that promotes a claim, and the only place a
visibility choice is made.

Three things happen here and nowhere else:

**Promotion.** ``claim.committed`` is written only by this module — no other
module in the tree constructs that event type. Neither ``baraza.ingest`` nor
``baraza.reconcile`` imports this one; the reconcile Job's entrypoint does not
load it at all. (The deployed ingest Job enters through ``baraza.cli``, which
imports ``ApprovalFlow`` for the local demo flow, so there the isolation is the
path taken rather than the module being absent. Said here rather than left for a
reader to discover.) ``deploy/firestore.rules`` denies the event type on
``create`` for every caller that rules govern.

Not IAM: Firestore permissions are per-operation and cannot be conditioned on an
``event_type`` field, so all writers hold the same append role — see
``deploy/README.md``. A claim reaches ``committed`` because a human approved it,
or it does not reach it at all.

**The visibility choice.** The approver picks who may read the claim, and the
choice is recorded as its own event so the boundary decision is auditable
separately from the approval. Default remains ``private``: an approval that
declines to choose does not silently publish.

**Closing the loop.** Approving an answer to an agenda item emits
``contradiction.resolved``, which drops the disagreement out of
``open_contradictions``, out of the ledger, and out of every future agenda. This
is what makes the next interview shorter than the last, and it happens as a
consequence of approval rather than as a separate bookkeeping step somebody has
to remember.

**Rejection retracts.** ``claim.rejected`` is not a soft flag. The claim leaves
the retrieval pool, the ledger, and every future agenda, permanently.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from baraza.fold.store import EventStore
from baraza.schema.claim import Claim
from baraza.schema.event import Event, EventType
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience, Visibility

__all__ = ["Decision", "ApprovalRequest", "ApprovalResult", "ApprovalFlow"]


class Decision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    DEFER = "defer"
    """Left pending. Reappears on the next agenda — deferral is not rejection,
    and conflating the two would silently discard facts the officer simply
    wasn't sure about."""


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """One claim put to an approver, with the visibility choice attached."""

    claim: Claim
    decision: Decision
    visibility: Visibility | None = None
    """``None`` on approve means the claim keeps ``private``. The approver
    declining to choose is a valid outcome and resolves to the tier that leaks
    nothing."""

    approver_id: str = "officer"
    contradiction_id: str | None = None
    note: str = ""
    edited_text: str | None = None
    """If the approver corrected the wording, the corrected text. Recorded as a
    superseding claim rather than an edit — the log is append-only, so a
    correction is a new claim citing the same turn, and the original stays
    visible in the history."""


@dataclass(slots=True)
class ApprovalResult:
    committed: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    contradictions_resolved: list[str] = field(default_factory=list)
    visibility_choices: dict[str, str] = field(default_factory=dict)
    events_appended: int = 0

    def describe(self) -> list[str]:
        lines = [
            f"approval: {len(self.committed)} committed, "
            f"{len(self.rejected)} rejected, {len(self.deferred)} deferred",
        ]
        if self.visibility_choices:
            tally: dict[str, int] = {}
            for choice in self.visibility_choices.values():
                tally[choice] = tally.get(choice, 0) + 1
            rendered = ", ".join(f"{k}={v}" for k, v in sorted(tally.items()))
            lines.append(f"  visibility chosen: {rendered}")
        if self.contradictions_resolved:
            lines.append(
                f"  {len(self.contradictions_resolved)} disagreement(s) retired "
                "— they will not appear on any future agenda"
            )
        return lines


class ApprovalFlow:
    """The promotion path. The only one."""

    def __init__(self, store: EventStore):
        self.store = store

    def submit(
        self,
        requests: list[ApprovalRequest],
        *,
        occurred_at: EpochMillis,
        session_id: str | None = None,
    ) -> ApprovalResult:
        result = ApprovalResult()

        for request in requests:
            claim = request.claim

            if request.decision is Decision.DEFER:
                result.deferred.append(claim.claim_id)
                continue

            if request.decision is Decision.REJECT:
                if self._append(
                    EventType.CLAIM_REJECTED,
                    occurred_at,
                    {
                        "claim_id": claim.claim_id,
                        "approver_id": request.approver_id,
                        "note": request.note,
                    },
                    result,
                ):
                    result.rejected.append(claim.claim_id)
                continue

            # ---- approve -------------------------------------------------

            target = claim
            # The approver is the claim's owner for this comparison — they are
            # editing their own testimony, so OWNER is the correct audience and
            # the read still routes through the predicate rather than around it.
            original_text = claim.quote_for(Audience.OWNER)
            if request.edited_text and request.edited_text.strip() != original_text:
                # A correction is a NEW claim citing the same turn, appended
                # alongside the original. The log is append-only; nothing is
                # edited in place, and the original remains inspectable.
                target = Claim.create(
                    subject_id=claim.subject_id,
                    predicate=claim.predicate,
                    predicate_hint=claim.predicate_hint,
                    quote=request.edited_text.strip(),
                    anchor=claim.anchor,
                    observed_at=occurred_at,
                    object_literal=request.edited_text.strip()[:200],
                    valid_from=claim.valid_from,
                    valid_until=claim.valid_until,
                    provenance=claim.provenance,
                    author_id=request.approver_id,
                    session_id=claim.session_id,
                    extra={**claim.extra, "supersedes": claim.claim_id},
                )
                self._append(
                    EventType.CLAIM_ASSERTED,
                    occurred_at,
                    {"claim": target.to_dict()},
                    result,
                )

            if self._append(
                EventType.CLAIM_COMMITTED,
                occurred_at,
                {
                    "claim_id": target.claim_id,
                    "approver_id": request.approver_id,
                    "note": request.note,
                },
                result,
            ):
                result.committed.append(target.claim_id)

            # The visibility choice, as its own auditable event.
            chosen = request.visibility or Visibility.PRIVATE
            if self._append(
                EventType.CLAIM_VISIBILITY_SET,
                occurred_at,
                {
                    "claim_id": target.claim_id,
                    "visibility": chosen.value,
                    "approver_id": request.approver_id,
                },
                result,
            ):
                result.visibility_choices[target.claim_id] = chosen.value

            # Close the loop.
            if request.contradiction_id and self._append(
                EventType.CONTRADICTION_RESOLVED,
                occurred_at,
                {
                    "contradiction_id": request.contradiction_id,
                    "session_id": session_id,
                    "resolving_claim_id": target.claim_id,
                },
                result,
            ):
                result.contradictions_resolved.append(request.contradiction_id)

        return result

    def _append(
        self,
        event_type: EventType,
        occurred_at: EpochMillis,
        payload: dict[str, object],
        result: ApprovalResult,
    ) -> bool:
        written = self.store.append(
            Event.create(
                event_type=event_type,
                occurred_at=occurred_at,
                payload=payload,
                actor="approval",
            )
        )
        if written:
            result.events_appended += 1
        return written
