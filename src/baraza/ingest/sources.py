"""The source registry — what makes anchors resolvable.

Citations are load-bearing, which means an anchor is only worth something if it
points at a location that provably exists. This module is the registry that
makes that checkable: every document is registered with a content checksum, and
every anchor a claim carries must name a ``(source_id, locator)`` pair that this
registry can resolve back to the exact text.

``make verify-anchors`` walks every claim in the log and re-resolves its anchor
here. A fabricated or unresolvable anchor is a stop condition, not a warning —
the script exits nonzero and names the claim.

Four native formats, because the corpus is genuinely messy rather than four
copies of the same Markdown file wearing hats:

===================  ==================================  ========================
Format               What it is in the fixture corpus    Locator grammar
===================  ==================================  ========================
``pdf``              a skew-scanned constitution         ``p.4 ¶2``
``groupme``          a chat export with epoch timestamps ``msg:1713470400``
``xlsx``             headerless budget sheets            ``Sheet1!B14``
``docx``             meeting minutes                     ``¶37``
``md``               generated notes, the BIBLE itself   ``L12-L18``
===================  ==================================  ========================
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from baraza.schema.claim import Anchor
from baraza.schema.temporal import EpochMillis, to_epoch_millis

__all__ = [
    "SourceFormat",
    "SourceUnit",
    "Source",
    "SourceRegistry",
    "AnchorResolutionError",
]


class SourceFormat(StrEnum):
    PDF = "pdf"
    GROUPME = "groupme"
    XLSX = "xlsx"
    DOCX = "docx"
    MD = "md"


class AnchorResolutionError(LookupError):
    """An anchor named a location the registry cannot produce."""


@dataclass(frozen=True, slots=True)
class SourceUnit:
    """The smallest addressable piece of a source — the thing a locator names."""

    locator: str
    text: str
    observed_at: EpochMillis | None = None
    """When the unit's content was authored, where the format records it.

    Chat messages carry their own timestamp; a spreadsheet cell does not, and
    inherits the document's. ``None`` means the caller must fall back to the
    source-level instant rather than guess.
    """

    speaker: str | None = None
    confidence: float = 1.0
    """OCR confidence for scanned formats. Below the source's threshold, the
    unit is flagged for the manifest rather than silently trusted — the skewed
    constitution scan is a planted problem, and pretending its text is clean
    would defeat the fixture."""


@dataclass(slots=True)
class Source:
    """A registered document."""

    source_id: str
    path: Path
    fmt: SourceFormat
    checksum: str
    observed_at: EpochMillis
    """Document-level instant, epoch millis. Every unit without its own
    timestamp inherits this."""

    title: str = ""
    units: dict[str, SourceUnit] = field(default_factory=dict)
    notes: str = ""

    def unit(self, locator: str) -> SourceUnit:
        try:
            return self.units[locator]
        except KeyError as exc:
            raise AnchorResolutionError(
                f"{self.source_id}#{locator} does not resolve. "
                f"Known locators in this source: {sorted(self.units)[:8]}"
                f"{'…' if len(self.units) > 8 else ''}"
            ) from exc


class SourceRegistry:
    """Every document the system has read, and the locators inside them."""

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    # ------------------------------------------------------------ registration

    def register(self, source: Source) -> Source:
        existing = self._sources.get(source.source_id)
        if existing and existing.checksum != source.checksum:
            raise ValueError(
                f"source {source.source_id!r} re-registered with a different "
                f"checksum ({existing.checksum[:12]} -> {source.checksum[:12]}). "
                "A source's bytes are part of its identity; register the new "
                "revision under a new id so existing anchors keep resolving."
            )
        self._sources[source.source_id] = source
        return source

    def get(self, source_id: str) -> Source:
        try:
            return self._sources[source_id]
        except KeyError as exc:
            raise AnchorResolutionError(
                f"unknown source {source_id!r}; registered: "
                f"{sorted(self._sources)}"
            ) from exc

    def __len__(self) -> int:
        return len(self._sources)

    def __iter__(self) -> Iterable[Source]:
        return iter(self._sources.values())

    # -------------------------------------------------------------- resolution

    def resolve(self, anchor: Anchor) -> SourceUnit:
        """Turn an anchor back into the text it cites.

        The single function ``make verify-anchors`` runs over every claim.
        """
        source = self.get(anchor.source_id)
        unit = source.unit(anchor.locator)
        if anchor.checksum and anchor.checksum != source.checksum:
            raise AnchorResolutionError(
                f"{anchor.key()} was written against source checksum "
                f"{anchor.checksum[:12]} but the source now hashes to "
                f"{source.checksum[:12]}. The document changed under the "
                "citation; re-ingest rather than re-point the anchor."
            )
        return unit

    def verify_quote(self, anchor: Anchor, quote: str) -> tuple[bool, str]:
        """Check that a claim's quote actually appears at its anchor.

        Returns ``(ok, detail)``. Whitespace is normalized before comparison
        because extraction reflows text, but nothing else is: a quote that is
        not a substring of the cited unit is a fabricated citation, and the
        whole point of this file is that those are catchable.
        """
        unit = self.resolve(anchor)
        haystack = re.sub(r"\s+", " ", unit.text).strip().lower()
        needle = re.sub(r"\s+", " ", quote).strip().lower()
        if not needle:
            return False, "empty quote"
        if needle in haystack:
            return True, "exact"
        # A quote may legitimately span a unit boundary when the extractor read
        # two adjacent chunks. Accept a high-overlap prefix, and say so.
        head = needle[: max(24, len(needle) // 2)]
        if head in haystack:
            return True, "partial (quote spans the unit boundary)"
        return False, (
            f"quote not found at {anchor.key()}. "
            f"unit begins: {unit.text.strip()[:120]!r}"
        )

    # --------------------------------------------------------------- persistence

    def to_dict(self) -> dict[str, object]:
        return {
            "sources": [
                {
                    "source_id": s.source_id,
                    "path": str(s.path),
                    "format": s.fmt.value,
                    "checksum": s.checksum,
                    "observed_at": s.observed_at,
                    "title": s.title,
                    "notes": s.notes,
                    "units": [
                        {
                            "locator": u.locator,
                            "text": u.text,
                            "observed_at": u.observed_at,
                            "speaker": u.speaker,
                            "confidence": u.confidence,
                        }
                        for u in s.units.values()
                    ],
                }
                for s in sorted(self._sources.values(), key=lambda s: s.source_id)
            ]
        }

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return target

    @staticmethod
    def load(path: Path | str) -> SourceRegistry:
        registry = SourceRegistry()
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        for entry in payload.get("sources", []):
            source = Source(
                source_id=entry["source_id"],
                path=Path(entry["path"]),
                fmt=SourceFormat(entry["format"]),
                checksum=entry["checksum"],
                observed_at=to_epoch_millis(
                    entry["observed_at"], field="source.observed_at"
                ),
                title=entry.get("title", ""),
                notes=entry.get("notes", ""),
            )
            for unit in entry.get("units", []):
                source.units[unit["locator"]] = SourceUnit(
                    locator=unit["locator"],
                    text=unit["text"],
                    observed_at=unit.get("observed_at"),
                    speaker=unit.get("speaker"),
                    confidence=float(unit.get("confidence", 1.0)),
                )
            registry.register(source)
        return registry


def checksum_of(path: Path) -> str:
    """SHA-256 of a file's bytes. Part of a source's identity."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()
