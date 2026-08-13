"""The append-only claim-event log.

The log is the system of record. The graph is a fold over it. There is no
mutable graph store anywhere in Baraza, and fixing bad data means appending a
superseding event — never editing or deleting one.

Three mechanisms hold that invariant:

* **Deterministic event IDs.** An event's ID is a content hash. Re-running a
  failed ingestion Job re-derives the same IDs, so ``create()``-only writes are
  idempotent: the second attempt collides and is a no-op rather than a
  duplicate.
* **``create()``-only writes.** The store exposes append and read. It does not
  expose update or delete, and the Firestore rules in ``deploy/firestore.rules``
  reject both at the database level, so a mistake in application code cannot
  mutate history even if it tries.
* **Total ordering on epoch millis** (BAR-309), tie-broken by event ID. The
  fold is therefore deterministic under any input permutation — the property
  the fold-stability test asserts.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional

from baraza.schema.temporal import EpochMillis, to_epoch_millis

__all__ = ["EventType", "Event", "AppendOnlyViolation"]


class EventType(str, Enum):
    """Every mutation the system can record.

    Adding a member here is a schema change: the fold must learn to handle it,
    and an unknown event type is a hard error in the fold rather than a skip.
    """

    CLAIM_ASSERTED = "claim.asserted"
    """A claim enters the log at tier ``pending``."""

    CLAIM_COMMITTED = "claim.committed"
    """The approval path promotes a claim. Only this path may promote."""

    CLAIM_REJECTED = "claim.rejected"
    """Retraction. Removes the claim from retrieval, ledger, and all agendas."""

    CLAIM_VISIBILITY_SET = "claim.visibility_set"
    """The approver's visibility choice, recorded as its own event so the
    boundary decision is auditable independently of the approval."""

    CONTRADICTION_DETECTED = "contradiction.detected"
    CONTRADICTION_RESOLVED = "contradiction.resolved"
    """Closes the loop: a resolved contradiction retires its own agenda item, so
    the next interview is shorter than the last."""

    ENTITY_ALIAS_LINKED = "entity.alias_linked"
    """A ``sameAs`` edge. Never a destructive merge — identity resolves at query
    time."""

    SESSION_OPENED = "session.opened"
    SESSION_TURN = "session.turn"
    SESSION_CLOSED = "session.closed"

    HEARTBEAT = "heartbeat"
    """BAR-021. The stub reconcile Job writes one of these per nightly run so
    execution history accumulates from day two. Always labelled as a scheduled
    run; never counted as organic activity."""


class AppendOnlyViolation(RuntimeError):
    """Raised when code attempts to mutate or delete a recorded event."""


def _canonical(payload: Dict[str, Any]) -> str:
    """Stable JSON for hashing: sorted keys, no incidental whitespace."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


@dataclass(frozen=True, slots=True)
class Event:
    """One immutable entry in the log."""

    event_id: str
    event_type: EventType
    occurred_at: EpochMillis
    payload: Dict[str, Any] = field(default_factory=dict)
    actor: str = "system"
    """Who or what appended this. Least-privilege service accounts map here:
    the extractor appends ``claim.asserted`` and nothing else, and cannot write
    ``claim.committed`` at all — enforced by IAM, asserted by a test."""

    scheduled: bool = False
    """True when the append came from a Cloud Scheduler run. Scheduler runs are
    labelled as such in any accounting; a scheduled job is never counted as
    organic activity."""

    # ---------------------------------------------------------------- factory

    @staticmethod
    def create(
        *,
        event_type: EventType,
        occurred_at: Any,
        payload: Optional[Dict[str, Any]] = None,
        actor: str = "system",
        scheduled: bool = False,
    ) -> "Event":
        """Build an event with a deterministic, content-addressed ID."""
        body = dict(payload or {})
        instant = to_epoch_millis(occurred_at, field="occurred_at")
        event_id = Event.deterministic_id(
            event_type=event_type,
            occurred_at=instant,
            payload=body,
            actor=actor,
        )
        return Event(
            event_id=event_id,
            event_type=event_type,
            occurred_at=instant,
            payload=body,
            actor=actor,
            scheduled=scheduled,
        )

    @staticmethod
    def deterministic_id(
        *,
        event_type: EventType,
        occurred_at: EpochMillis,
        payload: Dict[str, Any],
        actor: str,
    ) -> str:
        digest = hashlib.sha256(
            "\x1f".join(
                [event_type.value, str(occurred_at), actor, _canonical(payload)]
            ).encode("utf-8")
        ).hexdigest()
        return f"evt_{digest[:32]}"

    # ----------------------------------------------------------- ordering key

    @property
    def order_key(self) -> tuple[int, str]:
        """Total order over the log.

        Epoch millis first — never the ISO serialization — with the event ID as
        a deterministic tiebreaker so events sharing a millisecond fold in a
        stable order regardless of retrieval order.
        """
        return (self.occurred_at, self.event_id)

    # --------------------------------------------------------- serialization

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type.value,
            "occurred_at": self.occurred_at,
            "payload": dict(self.payload),
            "actor": self.actor,
            "scheduled": self.scheduled,
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Event":
        return Event(
            event_id=payload["event_id"],
            event_type=EventType(payload["event_type"]),
            occurred_at=to_epoch_millis(payload["occurred_at"], field="occurred_at"),
            payload=dict(payload.get("payload") or {}),
            actor=payload.get("actor", "system"),
            scheduled=bool(payload.get("scheduled", False)),
        )
