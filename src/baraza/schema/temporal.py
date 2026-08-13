"""BAR-309 — temporal normalization.

Every temporal comparison anywhere in Baraza operates on integer epoch
milliseconds, UTC. ISO-8601 strings are a serialization format and are never a
comparison key.

This is a ported defect class, not a stylistic preference. In a sibling
portfolio an ISO-string sort inside ``resolve()`` allowed a revoked grant to
remain active under mixed UTC offsets while byte-stability tests stayed green:
``"2025-05-01T09:00:00-05:00"`` sorts before ``"2025-05-01T08:00:00Z"`` as a
string, but is the *later* instant. Baraza's corpus mixes GroupMe epoch
timestamps, scanned-PDF dates, and interview ``ts`` values, which reproduces
exactly those conditions.

The module exposes one normalizer and a small set of comparison helpers. Nothing
else in the codebase is permitted to compare instants.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Final, Optional, Union

__all__ = [
    "EpochMillis",
    "TemporalError",
    "to_epoch_millis",
    "to_epoch_millis_optional",
    "to_iso",
    "intervals_overlap",
    "MIN_INSTANT",
    "MAX_INSTANT",
]

# An epoch-millis instant. Integer, UTC. The only comparison key in the system.
EpochMillis = int

# Open interval sentinels. ``valid_from=None`` means "since the beginning of the
# record"; ``valid_until=None`` means "still in force". Both normalize to these
# so that overlap arithmetic never special-cases None.
MIN_INSTANT: Final[EpochMillis] = -(2**62)
MAX_INSTANT: Final[EpochMillis] = 2**62

TemporalInput = Union[int, float, str, datetime, date, None]


class TemporalError(ValueError):
    """A value could not be normalized to an unambiguous instant.

    Raised rather than guessed. A wrong instant is a silent correctness defect;
    a raised error is a loud one.
    """


# Plausible epoch-seconds band: 1970-01-01 .. 2286-11-20. Values inside it are
# read as seconds, values above it as milliseconds. Bare integers in the corpus
# (GroupMe exports) are seconds; our own serialized values are millis.
_EPOCH_SECONDS_CEILING: Final[int] = 10_000_000_000

# ISO-8601 with an explicit offset or a trailing Z. Anything else is ambiguous.
_HAS_OFFSET: Final[re.Pattern[str]] = re.compile(
    r"(?:[Zz]|[+-]\d{2}:?\d{2})$"
)
_DATE_ONLY: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def to_epoch_millis(value: TemporalInput, *, field: str = "instant") -> EpochMillis:
    """Normalize any supported temporal representation to integer epoch millis, UTC.

    Accepted:
      * ``int``/``float`` — epoch seconds below ``_EPOCH_SECONDS_CEILING``,
        epoch millis at or above it.
      * ``str`` — ISO-8601 **carrying an explicit offset or Z**, or a bare
        ``YYYY-MM-DD`` date (interpreted as 00:00:00Z, the documented
        convention for scanned-document dates that carry no time).
      * ``datetime`` — must be timezone-aware.
      * ``date`` — interpreted as 00:00:00Z.

    Rejected, loudly:
      * naive ``datetime`` objects
      * ISO strings with no offset (e.g. ``"2026-04-14T19:30:00"``)
      * ``None``

    ``field`` names the offending field in the error message so an ingestion
    failure points at a corpus location rather than at this function.
    """
    if value is None:
        raise TemporalError(f"{field}: instant is required, got None")

    if isinstance(value, bool):  # bool is an int subclass; never a timestamp
        raise TemporalError(f"{field}: bool is not a timestamp")

    if isinstance(value, int) or isinstance(value, float):
        magnitude = abs(value)
        if magnitude < _EPOCH_SECONDS_CEILING:
            return int(round(value * 1000))
        return int(round(value))

    if isinstance(value, datetime):
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise TemporalError(
                f"{field}: naive datetime {value!r} has no offset; "
                "attach a timezone at the parse site, not here"
            )
        return int(round(value.timestamp() * 1000))

    if isinstance(value, date):
        return int(
            datetime(value.year, value.month, value.day, tzinfo=timezone.utc).timestamp()
            * 1000
        )

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise TemporalError(f"{field}: empty string is not an instant")

        if _DATE_ONLY.match(raw):
            parsed = datetime.fromisoformat(raw).replace(tzinfo=timezone.utc)
            return int(round(parsed.timestamp() * 1000))

        if not _HAS_OFFSET.search(raw):
            raise TemporalError(
                f"{field}: ISO string {raw!r} carries no UTC offset. "
                "An offsetless local time is ambiguous and BAR-309 forbids "
                "guessing one; record the offset at the source."
            )

        normalized = raw[:-1] + "+00:00" if raw[-1] in "Zz" else raw
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError as exc:  # pragma: no cover - message passthrough
            raise TemporalError(f"{field}: unparseable ISO-8601 {raw!r}") from exc
        return int(round(parsed.timestamp() * 1000))

    raise TemporalError(f"{field}: unsupported temporal type {type(value).__name__}")


def to_epoch_millis_optional(
    value: TemporalInput,
    *,
    default: EpochMillis,
    field: str = "instant",
) -> EpochMillis:
    """Normalize, substituting ``default`` for ``None``.

    Used for open interval bounds, where ``None`` is meaningful rather than
    missing. Every other absent instant is an error.
    """
    if value is None:
        return default
    return to_epoch_millis(value, field=field)


def to_iso(instant: EpochMillis) -> str:
    """Serialize epoch millis back to ISO-8601 UTC.

    Serialization only. Never feed the output of this function into a
    comparison.
    """
    return (
        datetime.fromtimestamp(instant / 1000, tz=timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def intervals_overlap(
    a_from: Optional[EpochMillis],
    a_until: Optional[EpochMillis],
    b_from: Optional[EpochMillis],
    b_until: Optional[EpochMillis],
) -> bool:
    """Half-open interval overlap on epoch values — the BAR-320 temporal gate.

    Intervals are ``[from, until)``. Two claims can only contradict each other
    if the periods they assert overlap: a treasurer's FY24 signing authority and
    their successor's FY25 authority are not a contradiction, and that
    false-positive pair is a planted fixture.

    ``None`` bounds are open and normalize to the sentinels, so an
    still-in-force claim overlaps everything after its start.
    """
    a_start = a_from if a_from is not None else MIN_INSTANT
    a_end = a_until if a_until is not None else MAX_INSTANT
    b_start = b_from if b_from is not None else MIN_INSTANT
    b_end = b_until if b_until is not None else MAX_INSTANT

    if a_start > a_end or b_start > b_end:
        raise TemporalError(
            f"inverted interval: [{a_start}, {a_end}) vs [{b_start}, {b_end})"
        )

    return a_start < b_end and b_start < a_end
