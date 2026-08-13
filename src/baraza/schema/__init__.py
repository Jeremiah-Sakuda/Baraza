"""Authoritative data models.

Import claims, events, sessions, contradictions, and the two invariant modules
from here. ``temporal`` and ``visibility`` live in this package rather than a
``common/`` sibling because they are part of the model's contract, not utility
code: an instant that is not epoch-normalized and a claim whose visibility was
never set are both schema violations, not helper-function mistakes.
"""

from baraza.schema.claim import Anchor, CitationError, Claim, Provenance, Tier
from baraza.schema.contradiction import (
    Contradiction,
    ContradictionStatus,
    RenderedContradiction,
)
from baraza.schema.event import AppendOnlyViolation, Event, EventType
from baraza.schema.session import Session, SessionStatus, Turn, TurnKind, TurnRole
from baraza.schema.temporal import (
    EpochMillis,
    TemporalError,
    intervals_overlap,
    to_epoch_millis,
    to_iso,
)
from baraza.schema.visibility import (
    Audience,
    RedactedClaim,
    Visibility,
    filter_readable,
    readable_by,
    redacted_for,
)

__all__ = [
    "Anchor",
    "AppendOnlyViolation",
    "Audience",
    "CitationError",
    "Claim",
    "Contradiction",
    "ContradictionStatus",
    "EpochMillis",
    "Event",
    "EventType",
    "Provenance",
    "RedactedClaim",
    "RenderedContradiction",
    "Session",
    "SessionStatus",
    "TemporalError",
    "Tier",
    "Turn",
    "TurnKind",
    "TurnRole",
    "Visibility",
    "filter_readable",
    "intervals_overlap",
    "readable_by",
    "redacted_for",
    "to_epoch_millis",
    "to_iso",
]
