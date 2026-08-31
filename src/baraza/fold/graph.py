"""The fold — the only graph renderer in Baraza.

Every rendered graph state is a fold over the event log. There is no mutable
graph store, no cache that can drift from the log, and no code path that mutates
a ``GraphState`` in place after it is built. If a graph looks wrong, the log is
the truth and the fold is the bug.

Determinism is the property that makes this safe, and it rests entirely on
BAR-309: events are ordered by ``(occurred_at_millis, event_id)``, never by an
ISO string. ``tests/property/test_fold_stability.py`` permutes the serialized
UTC offsets across the golden log and asserts the fold produces a byte-identical
graph — the test that would have caught the ported defect class.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from baraza.schema.claim import Claim, Tier
from baraza.schema.contradiction import Contradiction, ContradictionStatus
from baraza.schema.event import Event, EventType
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience, Visibility, filter_readable

__all__ = ["GraphState", "fold", "UnknownEventType"]


class UnknownEventType(RuntimeError):
    """The fold met an event type it does not handle.

    A hard error, deliberately. Silently skipping an unrecognized event would
    let a schema change produce a quietly incomplete graph, which is the failure
    mode an append-only log exists to prevent.
    """


@dataclass(slots=True)
class GraphState:
    """The folded world at a point in the log.

    Built only by :func:`fold`. Treat as read-only; mutate the log instead.
    """

    claims: dict[str, Claim] = field(default_factory=dict)
    contradictions: dict[str, Contradiction] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    """``alias_entity_id -> canonical_entity_id``. Non-destructive: identity
    resolves at query time via :meth:`resolve_entity`, and the original ID stays
    in every claim that used it."""

    heartbeats: list[EpochMillis] = field(default_factory=list)
    """BAR-021 nightly stub runs, kept separate from anything that could be
    reported as organic activity."""

    adjudicated_claim_ids: set[str] = field(default_factory=set)
    """Claims the nightly reconciler has already examined (BAR-321).

    Folded from ``claim.adjudicated`` events rather than inferred from a
    timestamp comparison. The reconciler's work pool is
    ``retrievable_claims() - adjudicated_claim_ids``, which is a set difference
    over recorded facts and therefore cannot go quietly empty the way a
    ``observed_at > last_heartbeat`` filter could."""

    last_event_at: EpochMillis | None = None
    event_count: int = 0

    # ------------------------------------------------------------- accessors

    def resolve_entity(self, entity_id: str) -> str:
        """Follow ``sameAs`` edges to a canonical ID, at query time.

        Cycle-safe: a malformed alias chain returns the last ID reached rather
        than looping. There are no destructive merges anywhere in the system.
        """
        seen: set[str] = set()
        current = entity_id
        while current in self.aliases and current not in seen:
            seen.add(current)
            current = self.aliases[current]
        return current

    def retrievable_claims(self) -> list[Claim]:
        """Claims still in the retrieval pool — i.e. not retracted.

        Visibility is *not* applied here; that is the caller's audience
        decision, made through ``filter_readable``. Keeping the two axes
        separate is what lets the reconciler count what it may not quote.
        """
        return [c for c in self.claims.values() if c.in_retrieval_pool]

    def committed_claims(self) -> list[Claim]:
        return [c for c in self.claims.values() if c.tier is Tier.COMMITTED]

    def readable_claims(self, audience: Audience) -> list[Claim]:
        """The successor-mode view: committed **and** readable, nothing else."""
        return filter_readable(self.committed_claims(), audience)

    def open_contradictions(self) -> list[Contradiction]:
        """Ledger contents: open only, and only where both sides survive.

        A contradiction whose claim was rejected is retracted here rather than
        lingering as a question about a claim that no longer exists.
        """
        live: list[Contradiction] = []
        for contradiction in self.contradictions.values():
            if not contradiction.is_open:
                continue
            sides = [self.claims.get(cid) for cid in contradiction.claim_ids]
            if any(c is None or not c.in_retrieval_pool for c in sides):
                continue
            live.append(contradiction)
        return sorted(
            live,
            key=lambda c: (-c.confidence, -c.detected_at, c.contradiction_id),
        )

    def fingerprint(self) -> str:
        """Order-independent digest of the folded state.

        The fold-stability property test compares this across permuted inputs.
        """
        import hashlib
        import json

        body = {
            "claims": sorted(
                (c.to_dict() for c in self.claims.values()),
                key=lambda d: d["claim_id"],
            ),
            "contradictions": sorted(
                (c.to_dict() for c in self.contradictions.values()),
                key=lambda d: d["contradiction_id"],
            ),
            "aliases": dict(sorted(self.aliases.items())),
            "heartbeats": sorted(self.heartbeats),
            "adjudicated": sorted(self.adjudicated_claim_ids),
        }
        return hashlib.sha256(
            json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()
        ).hexdigest()


def fold(events: Iterable[Event]) -> GraphState:
    """Fold an event log into a graph state.

    Ordering is on epoch millis with the event ID as tiebreaker, so the result
    is independent of the order events arrive in — from Firestore, from a JSONL
    replay, or from a partially retried Job.
    """
    ordered: Sequence[Event] = sorted(events, key=lambda e: e.order_key)
    state = GraphState()

    for event in ordered:
        _apply(state, event)
        state.last_event_at = event.occurred_at
        state.event_count += 1

    return state


def _apply(state: GraphState, event: Event) -> None:
    """Apply one event. Every branch is total; the default raises."""
    kind = event.event_type
    payload = event.payload

    if kind is EventType.CLAIM_ASSERTED:
        claim = Claim.from_dict(payload["claim"])
        # Deterministic IDs make re-assertion idempotent rather than duplicative.
        state.claims.setdefault(claim.claim_id, claim)
        return

    if kind is EventType.CLAIM_COMMITTED:
        _retier(state, payload["claim_id"], Tier.COMMITTED)
        return

    if kind is EventType.CLAIM_REJECTED:
        # Retraction. The claim stays in the fold as a tombstone so the log
        # remains auditable, but every accessor that gates on
        # `in_retrieval_pool` now excludes it: retrieval, ledger, agenda.
        _retier(state, payload["claim_id"], Tier.REJECTED)
        return

    if kind is EventType.CLAIM_VISIBILITY_SET:
        claim_id = payload["claim_id"]
        existing = state.claims.get(claim_id)
        if existing is None:
            return
        raw = payload.get("visibility")
        try:
            visibility = Visibility(raw)
        except (ValueError, TypeError):
            # Fail closed: an unparseable visibility event tightens rather than
            # loosens. This can only ever narrow access.
            visibility = Visibility.PRIVATE
        state.claims[claim_id] = _replace_claim(existing, visibility=visibility)
        return

    if kind is EventType.CLAIM_ADJUDICATED:
        # Idempotent by construction: a set. A retried Job that re-appends the
        # same adjudication changes nothing, and a claim examined on two
        # different nights is still examined exactly once as far as the fold is
        # concerned.
        state.adjudicated_claim_ids.add(payload["claim_id"])
        return

    if kind is EventType.CONTRADICTION_DETECTED:
        contradiction = Contradiction.from_dict(payload["contradiction"])
        state.contradictions.setdefault(
            contradiction.contradiction_id, contradiction
        )
        return

    if kind is EventType.CONTRADICTION_RESOLVED:
        cid = payload["contradiction_id"]
        existing_c = state.contradictions.get(cid)
        if existing_c is None:
            return
        state.contradictions[cid] = Contradiction(
            contradiction_id=existing_c.contradiction_id,
            subject_id=existing_c.subject_id,
            predicate_hint=existing_c.predicate_hint,
            claim_ids=list(existing_c.claim_ids),
            detected_at=existing_c.detected_at,
            confidence=existing_c.confidence,
            rationale=existing_c.rationale,
            status=ContradictionStatus.RESOLVED,
            resolved_at=event.occurred_at,
            resolving_session_id=payload.get("session_id"),
            extra=dict(existing_c.extra),
        )
        return

    if kind is EventType.ENTITY_ALIAS_LINKED:
        state.aliases[payload["alias_id"]] = payload["canonical_id"]
        return

    if kind is EventType.HEARTBEAT:
        state.heartbeats.append(event.occurred_at)
        return

    if kind in (
        EventType.SESSION_OPENED,
        EventType.SESSION_TURN,
        EventType.SESSION_CLOSED,
        EventType.SESSION_PROPOSED,
    ):
        # Session events are part of the same append-only log — that is what
        # makes a mid-stream kill survivable — but they do not shape the graph.
        # `session.proposed` in particular is evidence (who initiated, when,
        # with what agenda), not graph state: the agenda it carries was derived
        # from the fold, and folding it back in would make the fold circular.
        return

    raise UnknownEventType(
        f"fold has no handler for {kind!r}; a new event type must teach the "
        "fold before it may be appended"
    )


def _retier(state: GraphState, claim_id: str, tier: Tier) -> None:
    existing = state.claims.get(claim_id)
    if existing is None:
        return
    state.claims[claim_id] = _replace_claim(existing, tier=tier)


def _replace_claim(
    claim: Claim,
    *,
    tier: Tier | None = None,
    visibility: Visibility | None = None,
) -> Claim:
    """Rebuild a frozen claim with one field changed.

    Claims are immutable; the fold produces a new object rather than mutating,
    which keeps any previously returned state snapshot valid.
    """
    payload = claim.to_dict()
    if tier is not None:
        payload["tier"] = tier.value
    if visibility is not None:
        payload["visibility"] = visibility.value
    return Claim.from_dict(payload)
