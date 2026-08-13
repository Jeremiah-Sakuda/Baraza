"""Chunking — grouping source units into extraction-sized pieces.

A chunk is what one extraction call sees. Two constraints shape the design:

**A chunk never crosses a source boundary.** Every claim extracted from a chunk
must be citable, and a chunk spanning two documents produces claims whose anchor
is ambiguous. Cheaper to make chunks smaller than to make citations
approximate.

**A chunk carries its units' locators, not just their text.** The extractor is
told which locator each line came from, so the anchor it returns is selected
from a closed set rather than generated. An extractor that cannot invent a
locator cannot fabricate a citation — the constraint is structural, and the
verification in ``make verify-anchors`` is the backstop, not the primary
defence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator, List, Optional

from baraza.ingest.sources import Source, SourceUnit
from baraza.schema.temporal import EpochMillis

__all__ = ["Chunk", "chunk_source", "DEFAULT_TARGET_CHARS", "DEFAULT_OVERLAP_UNITS"]

DEFAULT_TARGET_CHARS = 6000
"""Roughly 1.5k tokens of source text, leaving room in a ~3k-token extraction
call for the instruction, the locator table, and the response."""

DEFAULT_OVERLAP_UNITS = 1
"""One unit of overlap between adjacent chunks.

A claim whose subject appears in the last line of one chunk and whose object
appears in the first line of the next is otherwise unextractable. One unit is
enough for the formats in this corpus — chat messages and minutes paragraphs are
self-contained — and more would inflate the extraction bill for no recall.
"""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One extraction call's worth of source text."""

    chunk_id: str
    source_id: str
    units: List[SourceUnit]
    observed_at: EpochMillis
    """The chunk's instant: the latest unit instant it contains, falling back to
    the source's. Used for temporal gating on the claims it yields."""

    format_hint: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        """The chunk as the model sees it: locator-tagged lines.

        The locator prefix is the mechanism that keeps citations honest. The
        extraction prompt instructs the model to return one of these exact
        strings as the anchor, so the set of anchors it can produce is closed.
        """
        return "\n".join(f"[{u.locator}] {u.text}" for u in self.units)

    @property
    def locators(self) -> List[str]:
        return [u.locator for u in self.units]

    @property
    def char_count(self) -> int:
        return sum(len(u.text) for u in self.units)

    def unit(self, locator: str) -> Optional[SourceUnit]:
        for unit in self.units:
            if unit.locator == locator:
                return unit
        return None


def chunk_source(
    source: Source,
    *,
    target_chars: int = DEFAULT_TARGET_CHARS,
    overlap_units: int = DEFAULT_OVERLAP_UNITS,
) -> Iterator[Chunk]:
    """Group a source's units into chunks.

    Units are emitted in locator-registration order, which each reader
    guarantees is document order. A unit larger than ``target_chars`` becomes
    its own chunk rather than being split — splitting a unit would produce a
    quote that spans a locator boundary, and then the anchor no longer names the
    text.
    """
    units = list(source.units.values())
    if not units:
        return

    index = 0
    sequence = 0
    while index < len(units):
        batch: List[SourceUnit] = []
        size = 0
        while index < len(units):
            unit = units[index]
            unit_size = len(unit.text)
            if batch and size + unit_size > target_chars:
                break
            batch.append(unit)
            size += unit_size
            index += 1

        instants = [u.observed_at for u in batch if u.observed_at is not None]
        yield Chunk(
            chunk_id=f"{source.source_id}#c{sequence}",
            source_id=source.source_id,
            units=batch,
            observed_at=max(instants) if instants else source.observed_at,
            format_hint=source.fmt.value,
        )
        sequence += 1

        if index < len(units) and overlap_units:
            index = max(index - overlap_units, 0)
            # Guard against a pathological unit larger than the target, where
            # backing up would re-emit the same batch forever.
            if len(batch) <= overlap_units:
                index += overlap_units
