"""Native-format readers.

Each reader turns one messy real-world file into a :class:`Source` with
addressable units. The formats are deliberately heterogeneous — this is the
"unusual, messy, highly complex unstructured data" the corpus is supposed to be,
not four Markdown files with different extensions.

Every reader is responsible for two things beyond extracting text:

1. **Producing a locator grammar a human can check.** ``Sheet1!B14`` and
   ``p.4 ¶2`` are verifiable by opening the file. ``chunk_137`` is not.
2. **Recording the instant honestly.** A GroupMe message carries its own epoch
   timestamp. A spreadsheet cell does not, and inherits the document's — which
   the reader marks as inherited rather than inventing a per-cell time.

Heavy parsing dependencies are imported lazily, so importing this module on a
machine without them still works and the failure names the missing package and
the format it was needed for.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path

from baraza.ingest.sources import (
    Source,
    SourceFormat,
    SourceUnit,
    checksum_of,
)
from baraza.schema.temporal import to_epoch_millis

__all__ = ["read_source", "READERS", "MissingReaderDependency"]


class MissingReaderDependency(RuntimeError):
    """A format's parser is not installed."""


def _require(module: str, package: str, fmt: str):
    try:
        return __import__(module, fromlist=["_"])
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise MissingReaderDependency(
            f"reading {fmt} requires the {package!r} package "
            f"(pip install {package}); it is declared in pyproject.toml"
        ) from exc


# ------------------------------------------------------------------ GroupMe


def read_groupme(path: Path, *, source_id: str, observed_at) -> Source:
    """A chat export: a JSON array of messages with epoch-second timestamps.

    The timestamps are the reason this format matters. They are bare integers in
    seconds, which is one of the three temporal representations BAR-309 has to
    reconcile, and the export's own segments carry a non-UTC offset in their
    metadata — the planted mixed-offset trap.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    messages = payload["messages"] if isinstance(payload, dict) else payload

    source = Source(
        source_id=source_id,
        path=path,
        fmt=SourceFormat.GROUPME,
        checksum=checksum_of(path),
        observed_at=to_epoch_millis(observed_at, field=f"{source_id}.observed_at"),
        title=(payload.get("name") if isinstance(payload, dict) else "") or source_id,
        notes="chat export; per-message epoch seconds",
    )

    for message in messages:
        text = (message.get("text") or "").strip()
        if not text:
            continue  # attachments and system events carry no claimable content
        created = message.get("created_at")
        locator = f"msg:{created}"
        source.units[locator] = SourceUnit(
            locator=locator,
            text=text,
            # Bare integer -> to_epoch_millis reads it as seconds and converts.
            observed_at=to_epoch_millis(created, field=f"{source_id}.{locator}"),
            speaker=message.get("name"),
        )
    return source


# --------------------------------------------------------------------- XLSX


def read_xlsx(path: Path, *, source_id: str, observed_at) -> Source:
    """Headerless budget sheets.

    Addressed by real cell reference, so a claim citing ``Sheet1!B14`` can be
    checked by opening the workbook. Headerless is the point: the extractor has
    to infer what a column means from neighbouring cells rather than reading a
    label, which is the actual condition of every treasurer's spreadsheet.
    """
    openpyxl = _require("openpyxl", "openpyxl", "xlsx")

    workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
    source = Source(
        source_id=source_id,
        path=path,
        fmt=SourceFormat.XLSX,
        checksum=checksum_of(path),
        observed_at=to_epoch_millis(observed_at, field=f"{source_id}.observed_at"),
        title=source_id,
        notes="headerless; cell instants inherit the document instant",
    )

    for sheet in workbook.worksheets:
        for row in sheet.iter_rows():
            for cell in row:
                if cell.value is None:
                    continue
                value = str(cell.value).strip()
                if not value:
                    continue
                locator = f"{sheet.title}!{cell.coordinate}"
                # Give the model the row's neighbours; an isolated cell value is
                # not interpretable and the extractor would have to guess.
                context = " | ".join(
                    str(c.value).strip()
                    for c in row
                    if c.value is not None and str(c.value).strip()
                )
                source.units[locator] = SourceUnit(
                    locator=locator,
                    text=f"{value}\t[row: {context}]",
                    observed_at=None,  # inherited; never invented per cell
                )
    workbook.close()
    return source


# --------------------------------------------------------------------- DOCX


def read_docx(path: Path, *, source_id: str, observed_at) -> Source:
    """Meeting minutes, addressed by paragraph ordinal."""
    docx = _require("docx", "python-docx", "docx")

    document = docx.Document(str(path))
    source = Source(
        source_id=source_id,
        path=path,
        fmt=SourceFormat.DOCX,
        checksum=checksum_of(path),
        observed_at=to_epoch_millis(observed_at, field=f"{source_id}.observed_at"),
        title=source_id,
        notes="minutes; paragraph ordinals are 1-based and skip empty paragraphs",
    )

    ordinal = 0
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        ordinal += 1
        locator = f"¶{ordinal}"
        source.units[locator] = SourceUnit(locator=locator, text=text)

    for table_index, table in enumerate(document.tables, start=1):
        for row_index, row in enumerate(table.rows, start=1):
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if not cells:
                continue
            locator = f"tbl{table_index}:r{row_index}"
            source.units[locator] = SourceUnit(
                locator=locator, text=" | ".join(cells)
            )
    return source


# ---------------------------------------------------------------------- PDF


def read_pdf(path: Path, *, source_id: str, observed_at) -> Source:
    """A skew-scanned constitution.

    ``pdfplumber`` first because it preserves layout well enough to keep
    paragraph boundaries on a skewed scan; ``pypdf`` as the fallback. Low
    per-unit confidence is recorded rather than smoothed over — the bad scan is
    a planted problem in the manifest, and a reader that quietly produced clean
    text would defeat the fixture it exists to exercise.
    """
    source = Source(
        source_id=source_id,
        path=path,
        fmt=SourceFormat.PDF,
        checksum=checksum_of(path),
        observed_at=to_epoch_millis(observed_at, field=f"{source_id}.observed_at"),
        title=source_id,
        notes="scanned; per-unit confidence recorded, low-confidence units flagged",
    )

    pages: list[str] = []
    try:
        pdfplumber = _require("pdfplumber", "pdfplumber", "pdf")
        with pdfplumber.open(str(path)) as document:
            pages = [(page.extract_text() or "") for page in document.pages]
    except MissingReaderDependency:
        pypdf = _require("pypdf", "pypdf", "pdf")
        reader = pypdf.PdfReader(str(path))
        pages = [(page.extract_text() or "") for page in reader.pages]

    for page_number, page_text in enumerate(pages, start=1):
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", page_text) if p.strip()]
        for para_number, paragraph in enumerate(paragraphs, start=1):
            locator = f"p.{page_number} ¶{para_number}"
            source.units[locator] = SourceUnit(
                locator=locator,
                text=paragraph,
                confidence=_ocr_confidence(paragraph),
            )
    return source


def _ocr_confidence(text: str) -> float:
    """A crude legibility score for scanned text.

    Not an OCR engine's confidence — we do not have one in the extraction path —
    but a measurable proxy: the ratio of characters that belong in prose. It is
    labelled as a proxy wherever it surfaces, and its only job is to flag units
    the manifest expects to be degraded.
    """
    if not text:
        return 0.0
    legible = sum(1 for ch in text if ch.isalnum() or ch in " .,;:'\"()-–—§¶\n")
    return round(legible / len(text), 3)


# ----------------------------------------------------------------- Markdown


def read_md(path: Path, *, source_id: str, observed_at) -> Source:
    """Plain notes, addressed by line range."""
    lines = path.read_text(encoding="utf-8").splitlines()
    source = Source(
        source_id=source_id,
        path=path,
        fmt=SourceFormat.MD,
        checksum=checksum_of(path),
        observed_at=to_epoch_millis(observed_at, field=f"{source_id}.observed_at"),
        title=source_id,
        notes="line-range locators are 1-based and inclusive",
    )

    block: list[str] = []
    start = 1
    for lineno, line in enumerate(lines, start=1):
        if line.strip():
            if not block:
                start = lineno
            block.append(line)
            continue
        if block:
            locator = f"L{start}-L{start + len(block) - 1}"
            source.units[locator] = SourceUnit(
                locator=locator, text="\n".join(block).strip()
            )
            block = []
    if block:
        locator = f"L{start}-L{start + len(block) - 1}"
        source.units[locator] = SourceUnit(
            locator=locator, text="\n".join(block).strip()
        )
    return source


READERS: dict[SourceFormat, Callable[..., Source]] = {
    SourceFormat.GROUPME: read_groupme,
    SourceFormat.XLSX: read_xlsx,
    SourceFormat.DOCX: read_docx,
    SourceFormat.PDF: read_pdf,
    SourceFormat.MD: read_md,
}

_SUFFIX_HINT: dict[str, SourceFormat] = {
    ".json": SourceFormat.GROUPME,
    ".xlsx": SourceFormat.XLSX,
    ".docx": SourceFormat.DOCX,
    ".pdf": SourceFormat.PDF,
    ".md": SourceFormat.MD,
    ".txt": SourceFormat.MD,
}


def read_source(
    path: Path | str,
    *,
    source_id: str | None = None,
    fmt: SourceFormat | None = None,
    observed_at,
) -> Source:
    """Dispatch to the right reader.

    ``observed_at`` is required and never inferred from filesystem mtime — a
    file's mtime is when it was copied, not when its content was authored, and
    the difference is exactly the kind of quiet wrongness that poisons a
    temporal gate.
    """
    target = Path(path)
    resolved_fmt = fmt or _SUFFIX_HINT.get(target.suffix.lower())
    if resolved_fmt is None:
        raise ValueError(
            f"no reader for {target.name!r}; known suffixes: "
            f"{sorted(_SUFFIX_HINT)}"
        )
    return READERS[resolved_fmt](
        target, source_id=source_id or target.stem, observed_at=observed_at
    )
