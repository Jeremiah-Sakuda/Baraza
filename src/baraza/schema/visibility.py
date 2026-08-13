"""The visibility boundary — Baraza's headline property.

This module defines ``readable_by(claim, audience)`` **once**. Every read path
in the system routes through it: divergence detection, the disputed ledger, the
interview agenda, the interviewer's question renderer, the graph view, and
successor mode. There is no second implementation, no local shortcut, and no
"just this once" direct field access.

Two rules make the boundary hold under carelessness rather than under
discipline:

1. **Default private.** ``visibility`` is set at append time and is never unset.
   A claim constructed without an explicit visibility is ``PRIVATE``, which is
   the tier that leaks nothing.

2. **Fail closed by construction.** The claim's quote is not a readable
   attribute. It is reachable only through ``quote_for(audience)``, which
   consults this predicate. Code that forgets the audience does not silently
   read the text — it raises ``AttributeError`` at the access site. An
   unrecognized audience or visibility value returns ``False`` rather than
   raising, because a boundary that crashes open under bad input is worse than
   one that denies.

The reconciler is permitted to *count* an unreadable claim toward a
contradiction's existence — that is what ``redacted_for`` is for. It is never
permitted to render that claim's text into a question posed to a different
audience.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Iterable, List, Optional, Protocol, TypeVar

if TYPE_CHECKING:  # pragma: no cover
    from baraza.schema.claim import Claim

__all__ = [
    "Visibility",
    "Audience",
    "readable_by",
    "filter_readable",
    "redacted_for",
    "RedactedClaim",
    "VisibilityBoundaryError",
]


class Visibility(str, Enum):
    """How widely a claim may be rendered. Ordered least- to most-permissive."""

    PRIVATE = "private"
    """Author and the approval path only. The default at append time."""

    SUCCESSOR = "successor"
    """The named successor role, plus everything PRIVATE allows."""

    ORG = "org"
    """Any authenticated member of the organization, plus the above."""

    PUBLIC = "public"
    """Anyone, including a logged-out judge on the hosted instance."""


class Audience(str, Enum):
    """Who is asking. Never inferred — always passed explicitly."""

    OWNER = "owner"
    """The claim's author, and the approval UI acting on their behalf."""

    SUCCESSOR = "successor"
    """Successor mode: the incoming officer reading the handover."""

    ORG = "org"
    """A member of the organization who is not the author or successor."""

    PUBLIC = "public"
    """Unauthenticated. The hosted demo instance reads as this."""


class VisibilityBoundaryError(RuntimeError):
    """Raised when a caller reaches for protected text without an audience."""


# The lattice, written once. Higher clearance reads everything at or below it.
_CLEARANCE: dict[Audience, int] = {
    Audience.PUBLIC: 0,
    Audience.ORG: 1,
    Audience.SUCCESSOR: 2,
    Audience.OWNER: 3,
}

_REQUIRED: dict[Visibility, int] = {
    Visibility.PUBLIC: 0,
    Visibility.ORG: 1,
    Visibility.SUCCESSOR: 2,
    Visibility.PRIVATE: 3,
}


class _HasVisibility(Protocol):
    visibility: Visibility


def readable_by(claim: "_HasVisibility", audience: Audience) -> bool:
    """The predicate. The only one.

    Returns ``True`` iff ``audience`` may see the claim's rendered text.

    Fails closed on every unrecognized input: an audience that is not an
    ``Audience``, a visibility that is not a ``Visibility``, a claim missing the
    attribute entirely. None of those raise — a boundary that raises can be
    caught and swallowed by a caller trying to be robust, and the swallowed
    exception path is exactly where leaks live.
    """
    visibility = getattr(claim, "visibility", None)

    # Tolerate the serialized form (a bare string) without tolerating garbage.
    if isinstance(visibility, str) and not isinstance(visibility, Visibility):
        try:
            visibility = Visibility(visibility)
        except ValueError:
            return False
    if not isinstance(visibility, Visibility):
        return False

    if isinstance(audience, str) and not isinstance(audience, Audience):
        try:
            audience = Audience(audience)
        except ValueError:
            return False
    if not isinstance(audience, Audience):
        return False

    return _CLEARANCE[audience] >= _REQUIRED[visibility]


T = TypeVar("T", bound=_HasVisibility)


def filter_readable(claims: Iterable[T], audience: Audience) -> List[T]:
    """Project a claim collection down to what ``audience`` may read.

    Every list that reaches a rendering surface passes through here.
    """
    return [c for c in claims if readable_by(c, audience)]


@dataclass(frozen=True, slots=True)
class RedactedClaim:
    """A claim stripped of everything that could leak, retaining only what the
    reconciler needs in order to *count* it.

    Carries no quote, no object literal, and no anchor text — only the
    structural coordinates that let a contradiction be detected and reported as
    existing. Rendering a ``RedactedClaim`` into a question produces a
    placeholder, never prose.
    """

    claim_id: str
    subject_id: str
    predicate_hint: str
    valid_from: Optional[int]
    valid_until: Optional[int]
    readable: bool = False

    def render(self) -> str:
        """What the interviewer is allowed to say about an unreadable claim."""
        return (
            "[a record you do not have access to asserts something conflicting "
            "here; it has been counted but not quoted]"
        )


def redacted_for(claim: "Claim", audience: Audience) -> RedactedClaim:
    """Counting-safe projection of a claim for a given audience.

    ``readable`` records whether the full claim *would* have been legible, so a
    caller can branch without re-deriving the predicate and without touching
    protected text.
    """
    return RedactedClaim(
        claim_id=claim.claim_id,
        subject_id=claim.subject_id,
        predicate_hint=claim.predicate_hint,
        valid_from=claim.valid_from,
        valid_until=claim.valid_until,
        readable=readable_by(claim, audience),
    )
