#!/usr/bin/env python3
"""``make corpus`` — emit the synthetic corpus from ``fixtures/corpus/BIBLE.md``.

The corpus is the fixture that every downstream claim in this project is
measured against, so two properties matter more than convenience.

**Native formats, not four Markdown files wearing hats.** A GroupMe export with
bare epoch-second timestamps, a headerless spreadsheet, minutes with a vote
table, and a skew-scanned constitution with a degraded page exercise genuinely
different reader paths and genuinely different locator grammars. If the corpus
were homogeneous, the ingestion spine would look like it worked when it had
only ever been asked one question.

**Byte-determinism.** Same BIBLE, same bytes, therefore the same SHA-256 for
every source. This is load-bearing rather than tidy: ``Anchor.checksum`` is the
source's content hash, ``SourceRegistry.register`` refuses a re-registration
whose checksum moved, and ``make verify-anchors`` compares the two. A generator
that produced fresh bytes on every run would invalidate every committed citation
each time somebody typed ``make corpus``.

That second property is why this module writes OOXML itself instead of calling
openpyxl and python-docx, which are declared in ``pyproject.toml`` and used on
the *reading* side. Measured on this machine, two consecutive ``openpyxl.save()``
calls over identical content produce different bytes: the zip directory records
wall-clock entry times and ``docProps/core.xml`` records a creation timestamp.
python-docx happened to be stable in the same test, but it is stable by accident
of its template rather than by contract. The writers below fix every zip entry
to a constant timestamp and emit no document properties at all, so the only
input is the BIBLE.

Everything is written **uncompressed** — ``ZIP_STORED`` for the OOXML packages,
raw content streams for the PDF. Two reasons: a compressed stream's bytes depend
on the zlib build, which would move determinism from "a property of this file"
to "a property of the machine"; and an uncompressed fixture is greppable, so
``scripts/verify_manifest.py`` can confirm a planted string is present without
needing a parser installed.

No wall clock, no unseeded randomness, no network. Run:

    make corpus
    python3 scripts/generate_corpus.py --check-determinism
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from baraza.schema.temporal import to_epoch_millis  # noqa: E402

CORPUS = REPO / "fixtures" / "corpus"
BIBLE = CORPUS / "BIBLE.md"

# Every zip entry in every generated OOXML package carries this instant. 1980-01-01
# is the earliest a DOS timestamp can express, so it is the unambiguous "no time
# recorded here" value rather than a plausible-looking one.
ZIP_EPOCH: tuple[int, int, int, int, int, int] = (1980, 1, 1, 0, 0, 0)


class BibleError(ValueError):
    """The BIBLE is malformed. Raised rather than worked around.

    A generator that silently skipped an unparseable block would emit a corpus
    missing a planted landmine, and ``verify_manifest`` would then report a miss
    whose real cause is three files away.
    """


# --------------------------------------------------------------- BIBLE parsing


@dataclass(slots=True)
class Block:
    """One fenced data block from the BIBLE."""

    kind: str
    attrs: dict[str, str]
    lines: list[str]
    start_line: int


_FENCE = re.compile(r"^```(corpus\.[a-z]+)\s*(.*)$")
_ATTR_KEY = re.compile(r"(?:^|\s)([a-z_]+)=")


def parse_attrs(text: str) -> dict[str, str]:
    """Parse ``key=value`` attributes where values may contain spaces.

    Values run to the start of the next ``key=`` token, which is why offsets
    (``offset=-05:00``) and free-text notes coexist on one line without quoting.
    """
    attrs: dict[str, str] = {}
    matches = list(_ATTR_KEY.finditer(text))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        attrs[match.group(1)] = text[match.end() : end].strip()
    return attrs


def parse_bible(path: Path) -> list[Block]:
    blocks: list[Block] = []
    current: Block | None = None
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if current is None:
            match = _FENCE.match(raw)
            if match:
                current = Block(
                    kind=match.group(1).split(".", 1)[1],
                    attrs=parse_attrs(match.group(2)),
                    lines=[],
                    start_line=lineno,
                )
            continue
        if raw.strip() == "```":
            blocks.append(current)
            current = None
            continue
        current.lines.append(raw)
    if current is not None:
        raise BibleError(
            f"unterminated ```corpus.{current.kind} block opened at line "
            f"{current.start_line}"
        )
    return blocks


def table_rows(block: Block) -> list[dict[str, str]]:
    """Read a pipe-delimited block whose first non-comment line is the header."""
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in block.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        cells = [c.strip() for c in stripped.split("|")]
        if header is None:
            header = cells
            continue
        if len(cells) != len(header):
            raise BibleError(
                f"corpus.{block.kind} row has {len(cells)} cells, header has "
                f"{len(header)}: {stripped!r}"
            )
        rows.append(dict(zip(header, cells, strict=True)))
    if header is None:
        raise BibleError(f"corpus.{block.kind} block has no header row")
    return rows


# ------------------------------------------------------ deterministic packaging


def write_zip(path: Path, parts: Sequence[tuple[str, bytes]]) -> None:
    """Write an OOXML package whose bytes depend only on ``parts``.

    ``ZipInfo`` is constructed explicitly for every entry: the default
    constructor stamps the current time and derives ``create_system`` from the
    host platform, both of which would leak the environment into the fixture's
    checksum.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, payload in parts:
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.create_system = 3  # unix, fixed; the default is platform-derived
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, payload)


def xml(text: str) -> bytes:
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + text).encode(
        "utf-8"
    )


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------- XLSX

_NS_SS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NS_CT = "http://schemas.openxmlformats.org/package/2006/content-types"

_CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


def _column_index(letters: str) -> int:
    value = 0
    for char in letters:
        value = value * 26 + (ord(char) - ord("A") + 1)
    return value


@dataclass(slots=True)
class Sheet:
    name: str
    cells: dict[str, Any] = field(default_factory=dict)


def parse_xlsx_block(block: Block) -> list[Sheet]:
    """``@sheet <name>`` opens a sheet; ``<ref> | <value>`` assigns a cell.

    A leading apostrophe forces the value to text, exactly as it does in a
    spreadsheet UI. That is how ``1,250.00`` stays a string in the fixture — the
    same figure appears elsewhere as ``$1,250`` and ``1250``, and a normalizer
    that reads three different values out of them invents a contradiction
    (landmine L-14).
    """
    sheets: list[Sheet] = []
    current: Sheet | None = None
    for line in block.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@sheet "):
            current = Sheet(name=stripped[len("@sheet ") :].strip())
            sheets.append(current)
            continue
        if current is None:
            raise BibleError(f"cell {stripped!r} appears before any @sheet")
        ref, _, raw_value = stripped.partition("|")
        ref = ref.strip()
        if not _CELL_REF.match(ref):
            raise BibleError(f"{ref!r} is not a cell reference")
        value = raw_value.strip()
        if value.startswith("'"):
            current.cells[ref] = value[1:]
            continue
        try:
            current.cells[ref] = int(value)
        except ValueError:
            try:
                current.cells[ref] = float(value)
            except ValueError:
                current.cells[ref] = value
    return sheets


def build_xlsx(sheets: Sequence[Sheet]) -> list[tuple[str, bytes]]:
    shared: list[str] = []
    shared_index: dict[str, int] = {}

    def intern(text: str) -> int:
        if text not in shared_index:
            shared_index[text] = len(shared)
            shared.append(text)
        return shared_index[text]

    sheet_parts: list[tuple[str, bytes]] = []
    for position, sheet in enumerate(sheets, start=1):
        by_row: dict[int, list[tuple[int, str, Any]]] = {}
        for ref, value in sheet.cells.items():
            match = _CELL_REF.match(ref)
            assert match is not None  # parse_xlsx_block validated the shape
            letters, digits = match.group(1), int(match.group(2))
            by_row.setdefault(digits, []).append(
                (_column_index(letters), ref, value)
            )

        rows_xml: list[str] = []
        for row_number in sorted(by_row):
            cells_xml: list[str] = []
            for _, ref, value in sorted(by_row[row_number]):
                if isinstance(value, bool):  # never a spreadsheet value here
                    raise BibleError(f"{ref}: bool is not a cell value")
                if isinstance(value, (int, float)):
                    cells_xml.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    cells_xml.append(
                        f'<c r="{ref}" t="s"><v>{intern(str(value))}</v></c>'
                    )
            rows_xml.append(
                f'<row r="{row_number}">' + "".join(cells_xml) + "</row>"
            )
        sheet_parts.append(
            (
                f"xl/worksheets/sheet{position}.xml",
                xml(
                    f'<worksheet xmlns="{_NS_SS}"><sheetData>'
                    + "".join(rows_xml)
                    + "</sheetData></worksheet>"
                ),
            )
        )

    sheet_tags = "".join(
        f'<sheet name="{esc(s.name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, s in enumerate(sheets, start=1)
    )
    rel_tags = "".join(
        f'<Relationship Id="rId{i}" Type="{_NS_REL}/worksheet" '
        f'Target="worksheets/sheet{i}.xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    next_rel = len(sheets) + 1
    rel_tags += (
        f'<Relationship Id="rId{next_rel}" Type="{_NS_REL}/styles" '
        f'Target="styles.xml"/>'
        f'<Relationship Id="rId{next_rel + 1}" Type="{_NS_REL}/sharedStrings" '
        f'Target="sharedStrings.xml"/>'
    )
    overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
        f'ContentType="application/vnd.openxmlformats-officedocument.'
        f'spreadsheetml.worksheet+xml"/>'
        for i in range(1, len(sheets) + 1)
    )
    strings_xml = "".join(
        f'<si><t xml:space="preserve">{esc(s)}</t></si>' for s in shared
    )

    return [
        (
            "[Content_Types].xml",
            xml(
                f'<Types xmlns="{_NS_CT}">'
                '<Default Extension="rels" ContentType="application/'
                'vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/xl/workbook.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                f"{overrides}"
                '<Override PartName="/xl/styles.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                '<Override PartName="/xl/sharedStrings.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
                "</Types>"
            ),
        ),
        (
            "_rels/.rels",
            xml(
                f'<Relationships xmlns="{_NS_PKG_REL}">'
                f'<Relationship Id="rId1" Type="{_NS_REL}/officeDocument" '
                'Target="xl/workbook.xml"/></Relationships>'
            ),
        ),
        (
            "xl/workbook.xml",
            xml(
                f'<workbook xmlns="{_NS_SS}" xmlns:r="{_NS_REL}">'
                f"<sheets>{sheet_tags}</sheets></workbook>"
            ),
        ),
        (
            "xl/_rels/workbook.xml.rels",
            xml(f'<Relationships xmlns="{_NS_PKG_REL}">{rel_tags}</Relationships>'),
        ),
        (
            "xl/styles.xml",
            xml(
                f'<styleSheet xmlns="{_NS_SS}">'
                '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
                '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
                '<borders count="1"><border/></borders>'
                '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
                'borderId="0"/></cellStyleXfs>'
                '<cellXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" '
                'borderId="0" xfId="0"/></cellXfs>'
                "</styleSheet>"
            ),
        ),
        (
            "xl/sharedStrings.xml",
            xml(
                f'<sst xmlns="{_NS_SS}" count="{len(shared)}" '
                f'uniqueCount="{len(shared)}">{strings_xml}</sst>'
            ),
        ),
        *sheet_parts,
    ]


# ---------------------------------------------------------------------- DOCX

_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def parse_docx_block(block: Block) -> list[tuple[str, Any]]:
    """``@h`` heading, ``@p`` paragraph, ``@table`` + ``@row a | b | c``."""
    items: list[tuple[str, Any]] = []
    table: list[list[str]] | None = None
    for line in block.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "@table":
            table = []
            items.append(("table", table))
            continue
        if stripped.startswith("@row "):
            if table is None:
                raise BibleError(f"@row outside a @table: {stripped!r}")
            table.append([c.strip() for c in stripped[len("@row ") :].split("|")])
            continue
        table = None
        if stripped.startswith("@h "):
            items.append(("h", stripped[3:].strip()))
        elif stripped.startswith("@p "):
            items.append(("p", stripped[3:].strip()))
        else:
            raise BibleError(f"unrecognized corpus.docx directive: {stripped!r}")
    return items


def build_docx(items: Sequence[tuple[str, Any]]) -> list[tuple[str, bytes]]:
    body: list[str] = []
    for kind, payload in items:
        if kind in ("h", "p"):
            style = (
                '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if kind == "h" else ""
            )
            body.append(
                f"<w:p>{style}<w:r><w:t xml:space=\"preserve\">"
                f"{esc(str(payload))}</w:t></w:r></w:p>"
            )
        elif kind == "table":
            rows: list[list[str]] = payload
            width = max((len(r) for r in rows), default=1)
            grid = "".join('<w:gridCol w:w="1800"/>' for _ in range(width))
            row_xml = []
            for row in rows:
                padded = row + [""] * (width - len(row))
                cells = "".join(
                    '<w:tc><w:tcPr><w:tcW w:w="1800" w:type="dxa"/></w:tcPr>'
                    f'<w:p><w:r><w:t xml:space="preserve">{esc(cell)}</w:t>'
                    "</w:r></w:p></w:tc>"
                    for cell in padded
                )
                row_xml.append(f"<w:tr>{cells}</w:tr>")
            body.append(
                '<w:tbl><w:tblPr><w:tblW w:w="0" w:type="auto"/></w:tblPr>'
                f"<w:tblGrid>{grid}</w:tblGrid>" + "".join(row_xml) + "</w:tbl>"
            )

    return [
        (
            "[Content_Types].xml",
            xml(
                f'<Types xmlns="{_NS_CT}">'
                '<Default Extension="rels" ContentType="application/'
                'vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                '<Override PartName="/word/document.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
                '<Override PartName="/word/styles.xml" ContentType="application/'
                'vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
                "</Types>"
            ),
        ),
        (
            "_rels/.rels",
            xml(
                f'<Relationships xmlns="{_NS_PKG_REL}">'
                f'<Relationship Id="rId1" Type="{_NS_REL}/officeDocument" '
                'Target="word/document.xml"/></Relationships>'
            ),
        ),
        (
            "word/_rels/document.xml.rels",
            xml(
                f'<Relationships xmlns="{_NS_PKG_REL}">'
                f'<Relationship Id="rId1" Type="{_NS_REL}/styles" '
                'Target="styles.xml"/></Relationships>'
            ),
        ),
        (
            "word/styles.xml",
            xml(
                f'<w:styles xmlns:w="{_NS_W}">'
                '<w:style w:type="paragraph" w:default="1" w:styleId="Normal">'
                '<w:name w:val="Normal"/></w:style>'
                '<w:style w:type="paragraph" w:styleId="Heading1">'
                '<w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
                "<w:rPr><w:b/></w:rPr></w:style>"
                "</w:styles>"
            ),
        ),
        (
            "word/document.xml",
            xml(
                f'<w:document xmlns:w="{_NS_W}"><w:body>'
                + "".join(body)
                + '<w:sectPr><w:pgSz w:w="12240" w:h="15840"/></w:sectPr>'
                "</w:body></w:document>"
            ),
        ),
    ]


# ----------------------------------------------------------------------- PDF


def parse_pdf_block(block: Block) -> list[list[tuple[str, str]]]:
    """``@page`` starts a page; ``@blank`` a blank line; ``@center`` centres."""
    pages: list[list[tuple[str, str]]] = []
    for line in block.lines:
        stripped = line.rstrip()
        if stripped.strip() == "@page":
            pages.append([])
            continue
        if not pages:
            raise BibleError(f"pdf content before the first @page: {stripped!r}")
        if stripped.strip() == "@blank":
            pages[-1].append(("blank", ""))
        elif stripped.strip().startswith("@center "):
            pages[-1].append(("center", stripped.strip()[len("@center ") :]))
        else:
            pages[-1].append(("left", stripped))
    return pages


def _pdf_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def build_pdf(
    pages: Sequence[Sequence[tuple[str, str]]],
    *,
    font_size: float = 10.5,
    leading: float = 14.5,
    left_margin: float = 66.0,
    top: float = 742.0,
    page_width: float = 612.0,
) -> bytes:
    """A PDF 1.4 text layer, written by hand and left uncompressed.

    Uncompressed content streams are the point of this writer, not a shortcut.
    They make the fixture's text greppable without a PDF library installed,
    which is what lets ``verify_manifest`` confirm a planted string is present
    on a machine that has neither pypdf nor pdfplumber.

    A blank line is emitted as a line containing a single space rather than as
    a vertical skip. pypdf preserves it, which is what produces the
    ``\\n \\n`` that ``read_pdf`` splits paragraphs on. pdfplumber discards
    whitespace-only lines and therefore returns one unit per page — a real
    divergence between the two readers, recorded in ``docs/FINDINGS.md``. The
    manifest probes locate planted text by content across a source's units, so
    they hold under either reader.
    """
    objects: dict[int, bytes] = {}
    count = len(pages)
    page_ids = [4 + i * 2 for i in range(count)]
    content_ids = [5 + i * 2 for i in range(count)]

    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Count {count} /Kids [{kids}] >>".encode("latin-1")
    objects[3] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier "
        b"/Encoding /WinAnsiEncoding >>"
    )

    for index, page in enumerate(pages):
        page_id, content_id = page_ids[index], content_ids[index]
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page_width:g} 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode("latin-1")

        ops = [f"BT /F1 {font_size:g} Tf {leading:g} TL {left_margin:g} {top:g} Td"]
        for position, (mode, text) in enumerate(page):
            if position:
                ops.append("T*")
            if mode == "blank":
                ops.append("( ) Tj")
                continue
            if mode == "center":
                # Courier is monospaced at 0.6 em, so centring is exact
                # arithmetic rather than a font-metrics lookup.
                width = len(text) * font_size * 0.6
                offset = max(0.0, (page_width - width) / 2 - left_margin)
                ops.append(f"{offset:.2f} 0 Td ({_pdf_escape(text)}) Tj")
                ops.append(f"{-offset:.2f} 0 Td")
                continue
            ops.append(f"({_pdf_escape(text)}) Tj")
        ops.append("ET")

        stream = ("\n".join(ops) + "\n").encode("latin-1", errors="replace")
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("latin-1")
            + stream
            + b"endstream"
        )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for number in sorted(objects):
        offsets[number] = len(out)
        out += f"{number} 0 obj\n".encode("latin-1") + objects[number] + b"\nendobj\n"

    xref_at = len(out)
    size = max(objects) + 1
    out += f"xref\n0 {size}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for number in range(1, size):
        out += f"{offsets[number]:010d} 00000 n \n".encode("latin-1")
    # No /CreationDate and no /ID: both would be wall-clock or random, and both
    # would move the file's checksum on every regeneration.
    out += (
        f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


# ------------------------------------------------------------------- GroupMe


def parse_groupme_block(block: Block) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Segments and messages.

    Timestamps in the BIBLE are ISO-8601 **with an explicit offset**; the export
    stores bare epoch seconds, which is what GroupMe emits and what the reader
    has to normalize. The offset survives only in the segment metadata, which is
    exactly the shape of the L-01 trap: the sortable-looking string and the
    actual instant are in different places.
    """
    segments: list[dict[str, Any]] = []
    messages: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for line in block.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("@segment"):
            attrs = parse_attrs(stripped[len("@segment") :])
            current = {
                "segment_id": attrs["id"],
                "tz_offset": attrs.get("offset", "+00:00"),
                "note": attrs.get("note", ""),
                "segment_started_at_iso": None,
                "message_count": 0,
            }
            segments.append(current)
            continue
        if current is None:
            raise BibleError(f"message before any @segment: {stripped!r}")

        iso, _, rest = stripped.partition("|")
        handle, _, text = rest.partition("|")
        iso, handle, text = iso.strip(), handle.strip(), text.strip()

        sender_type = "user"
        created: Any = None
        if text.startswith("@bot "):
            sender_type = "bot"
            text = text[len("@bot ") :].strip()
        if text.startswith("@raw "):
            raw_attrs = parse_attrs(text)
            created = int(raw_attrs["created_at"].split()[0])
            text = re.sub(r"^@raw\s+created_at=\S+\s*", "", text).strip()

        if created is None:
            created = to_epoch_millis(iso, field=f"groupme.{iso}") // 1000

        if current["segment_started_at_iso"] is None:
            # The literal BIBLE string, not a re-serialization. L-01 depends on
            # this exact text surviving into the export.
            current["segment_started_at_iso"] = iso
        current["message_count"] += 1

        messages.append(
            {
                "id": f"m{created}",
                "created_at": created,
                "name": handle,
                "sender_type": sender_type,
                "segment_id": current["segment_id"],
                "text": text,
            }
        )

    seen: dict[Any, str] = {}
    for message in messages:
        key = message["created_at"]
        if key in seen:
            # read_groupme addresses messages as msg:<created_at>. A collision
            # would silently drop one of them, and the dropped one would look
            # like an extraction failure rather than a fixture bug.
            raise BibleError(
                f"duplicate created_at {key} ({seen[key]!r} and "
                f"{message['text'][:40]!r}); locators must be unique"
            )
        seen[key] = message["text"][:40]

    return segments, messages


# ----------------------------------------------------------------- interviews


def parse_interview_block(block: Block) -> list[dict[str, str]]:
    turns: list[dict[str, str]] = []
    for line in block.lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = [p.strip() for p in stripped.split("|", 3)]
        if len(parts) != 4:
            raise BibleError(f"interview turn needs 4 fields: {stripped!r}")
        turn_id, ts, speaker, text = parts
        turns.append({"turn_id": turn_id, "ts": ts, "speaker": speaker, "text": text})
    return turns


# ----------------------------------------------------------------- generation


@dataclass(slots=True)
class Written:
    relative: str
    payload: bytes
    kind: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.payload).hexdigest()


def generate(root: Path) -> list[Written]:
    """Emit every artifact into ``root``. Pure function of BIBLE.md."""
    blocks = parse_bible(BIBLE)
    by_kind: dict[str, list[Block]] = {}
    for block in blocks:
        by_kind.setdefault(block.kind, []).append(block)

    for required in ("sources", "groupme", "xlsx", "pdf", "docx", "md", "interview"):
        if required not in by_kind:
            raise BibleError(f"BIBLE.md has no ```corpus.{required} block")

    # The narrative tables are not consumed here — they are the answer key that
    # fixtures/entities-gold.json and scripts/verify_manifest.py are written
    # against. Parse them anyway so a malformed row fails at `make corpus`
    # rather than at whatever reads them next.
    for narrative in ("roster", "people", "dues", "signing", "accounts"):
        for block in by_kind.get(narrative, []):
            table_rows(block)

    source_rows = table_rows(by_kind["sources"][0])
    path_by_id = {row["id"]: row["path"] for row in source_rows}

    def target(source_id: str) -> Path:
        try:
            return root / path_by_id[source_id]
        except KeyError as exc:
            raise BibleError(
                f"block declares id={source_id!r}, which the corpus.sources "
                f"table does not list. Known ids: {sorted(path_by_id)}"
            ) from exc

    written: list[Written] = []

    def emit(path: Path, payload: bytes, kind: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        written.append(
            Written(str(path.relative_to(root)), payload, kind)
        )

    # -- GroupMe ------------------------------------------------------------
    for block in by_kind["groupme"]:
        segments, messages = parse_groupme_block(block)
        payload = {
            "name": block.attrs.get("name", block.attrs["id"]),
            "group_id": "gm-" + hashlib.sha256(
                block.attrs["id"].encode("utf-8")
            ).hexdigest()[:12],
            "export_note": (
                "Timestamps are epoch seconds unless a message was re-imported "
                "from an older archive, in which case they are milliseconds. "
                "Per-segment tz_offset records the local offset the segment was "
                "captured under; it is metadata, not a sort key."
            ),
            "segments": segments,
            "messages": messages,
        }
        emit(
            target(block.attrs["id"]),
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "groupme",
        )

    # -- XLSX ---------------------------------------------------------------
    for block in by_kind["xlsx"]:
        sheets = parse_xlsx_block(block)
        path = target(block.attrs["id"])
        write_zip(path, build_xlsx(sheets))
        written.append(
            Written(str(path.relative_to(root)), path.read_bytes(), "xlsx")
        )

    # -- DOCX ---------------------------------------------------------------
    for block in by_kind["docx"]:
        items = parse_docx_block(block)
        path = target(block.attrs["id"])
        write_zip(path, build_docx(items))
        written.append(
            Written(str(path.relative_to(root)), path.read_bytes(), "docx")
        )

    # -- PDF ----------------------------------------------------------------
    for block in by_kind["pdf"]:
        pages = parse_pdf_block(block)
        emit(target(block.attrs["id"]), build_pdf(pages), "pdf")

    # -- Markdown -----------------------------------------------------------
    for block in by_kind["md"]:
        body = "\n".join(block.lines).strip("\n") + "\n"
        emit(target(block.attrs["id"]), body.encode("utf-8"), "md")

    # -- Prior exit interview ----------------------------------------------
    for block in by_kind["interview"]:
        turns = parse_interview_block(block)
        payload = {
            "interview_id": block.attrs["id"],
            "subject_handle": block.attrs.get("subject", ""),
            "subject_role": block.attrs.get("role", ""),
            "note": (
                "The previous year's exit interview, cut short. Not a corpus "
                "source: it is read by the interview layer, and it is the "
                "baseline the closed loop is supposed to beat. Turn ts values "
                "are ISO-8601 with explicit offsets and are NEVER a sort key."
            ),
            "turns": turns,
        }
        emit(
            root / "interviews" / f"{block.attrs['id']}.json",
            (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            "interview",
        )

    # -- The index ----------------------------------------------------------
    by_relative = {w.relative: w for w in written}
    night1: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for row in source_rows:
        record = {
            "source_id": row["id"],
            "path": f"fixtures/corpus/{row['path']}",
            "format": row["format"],
            "observed_at": row["observed_at"],
            "note": row["note"],
            "sha256": by_relative[row["path"]].sha256,
            "bytes": len(by_relative[row["path"]].payload),
        }
        (deferred if row["stage"] == "deferred" else night1).append(record)

    index = {
        "_readme": [
            "The ingestion manifest for the synthetic corpus. Consumers read this",
            "file; they never glob the directory, because two artifacts in it are",
            "deliberately not sources.",
            "",
            "observed_at is declared, not read from filesystem mtime. An mtime",
            "records when a file was copied onto a machine, which has nothing to do",
            "with when the minutes were taken.",
            "",
            "deferred_sources holds the BAR-323 artifact drop: generated by",
            "make corpus, excluded from the cold night-1 ingest, dropped in between",
            "two nightly reconcile runs so the ledger difference is a real",
            "elapsed-time observation rather than a staged one.",
            "",
            "Regenerate with: make corpus",
        ],
        "generator": "scripts/generate_corpus.py",
        "seed": "fixtures/corpus/BIBLE.md",
        "seed_sha256": hashlib.sha256(BIBLE.read_bytes()).hexdigest(),
        "sources": night1,
        "deferred_sources": deferred,
        "not_sources": [
            {
                "path": "fixtures/corpus/BIBLE.md",
                "why": (
                    "the generative seed and the answer key. Ingesting it would "
                    "let the system read the facts the corpus only implies, "
                    "which would make every downstream number meaningless. "
                    "Landmine L-16 asserts its absence from this list."
                ),
            },
            {
                "path": "fixtures/corpus/interviews/prior-exit-interview-2026-05.json",
                "why": (
                    "prior testimony, read by the interview layer rather than by "
                    "an ingestion reader. Holds the second half of the L-01 "
                    "mixed-offset trap."
                ),
            },
            {
                "path": "fixtures/corpus/corpus-index.json",
                "why": "this file",
            },
        ],
    }
    payload = (json.dumps(index, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (root / "corpus-index.json").write_bytes(payload)
    written.append(Written("corpus-index.json", payload, "index"))

    return written


# ------------------------------------------------------------------ reporting


def ocr_confidence_report(root: Path) -> list[str]:
    """Report the measured legibility proxy for the degraded constitution page.

    Measured here rather than asserted in the manifest: the manifest states a
    threshold, this prints the value, and ``verify_manifest`` compares them. No
    document in the repository writes the number by hand.
    """
    pdf = root / "governing" / "constitution-2016-amended-2019.pdf"
    if not pdf.exists():
        return ["  ocr confidence: not computed (constitution not emitted)"]
    try:
        from baraza.ingest.readers import read_source
    except Exception as exc:  # pragma: no cover - environment dependent
        return [f"  ocr confidence: not computed ({type(exc).__name__}: {exc})"]

    try:
        source = read_source(
            pdf, source_id="constitution", observed_at="2024-03-12T00:00:00Z"
        )
    except Exception as exc:  # pragma: no cover - no PDF parser installed
        return [f"  ocr confidence: not computed ({type(exc).__name__}: {exc})"]

    units = sorted(source.units.values(), key=lambda u: u.confidence)
    lines = [
        f"  ocr confidence, worst unit  {units[0].locator:<12} "
        f"{units[0].confidence:.3f}  {units[0].text.strip()[:44]!r}",
        f"  ocr confidence, best unit   {units[-1].locator:<12} "
        f"{units[-1].confidence:.3f}",
        f"  units below 0.90            "
        f"{sum(1 for u in units if u.confidence < 0.90)} of {len(units)}",
    ]
    return lines


def roundtrip_check(root: Path) -> tuple[list[str], int]:
    """Re-read every emitted artifact through the project's own readers.

    A generator that emits a file no reader can open is worse than one that
    emits nothing, because the failure surfaces three stages downstream as an
    empty extraction. Readers whose parser is not installed are reported as
    skipped, never as passed.

    Returns the report lines and the number of sources that did **not** round
    trip. The count is load-bearing: an unverified source has to make the target
    red. Observed on a machine where ``python-docx`` was absent, this function
    printed six SKIPPED lines and the target still exited 0 with a "13 artifacts"
    summary — a green target that verified less than it claimed, which is the
    exact failure the Makefile header names.
    """
    lines: list[str] = []
    unverified = 0
    index = json.loads((root / "corpus-index.json").read_text(encoding="utf-8"))
    try:
        from baraza.ingest.readers import MissingReaderDependency, read_source
    except Exception as exc:  # pragma: no cover
        return [f"  round-trip: skipped ({type(exc).__name__}: {exc})"], 1

    for record in index["sources"] + index["deferred_sources"]:
        path = REPO / record["path"]
        try:
            source = read_source(
                path,
                source_id=record["source_id"],
                observed_at=record["observed_at"],
            )
        except MissingReaderDependency as exc:
            lines.append(f"  {record['source_id']:<20} SKIPPED  {exc}")
            unverified += 1
            continue
        except Exception as exc:
            lines.append(
                f"  {record['source_id']:<20} FAILED   "
                f"{type(exc).__name__}: {exc}"
            )
            unverified += 1
            continue
        locators = sorted(source.units)
        first = repr(locators[0]) if locators else "(none)"
        lines.append(
            f"  {record['source_id']:<20} ok       {len(locators):>3} units"
            f"   first locator {first}"
        )
    return lines, unverified


def check_determinism() -> int:
    """Generate twice into scratch directories and compare every byte."""
    hashes: list[dict[str, str]] = []
    for _ in range(2):
        scratch = Path(tempfile.mkdtemp(prefix="baraza-corpus-"))
        try:
            written = generate(scratch)
            hashes.append({w.relative: w.sha256 for w in written})
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

    first, second = hashes
    drifted = sorted(
        name for name in set(first) | set(second) if first.get(name) != second.get(name)
    )
    if drifted:
        print("DETERMINISM FAILED — these artifacts differ between two runs:")
        for name in drifted:
            print(f"  {name}: {first.get(name)} != {second.get(name)}")
        return 1
    print(f"determinism ok — {len(first)} artifacts, byte-identical across two runs")
    return 0


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check-determinism",
        action="store_true",
        help="generate twice into scratch dirs and compare every byte; write nothing",
    )
    parser.add_argument(
        "--no-roundtrip",
        action="store_true",
        help="skip re-reading the output through baraza.ingest.readers",
    )
    args = parser.parse_args(argv)

    if not BIBLE.exists():
        print(f"missing seed: {BIBLE.relative_to(REPO)}")
        print("  The corpus is a pure function of the BIBLE; without it there is")
        print("  nothing to generate and nothing may be invented in its place.")
        return 2

    if args.check_determinism:
        return check_determinism()

    written = generate(CORPUS)

    print("make corpus — synthetic corpus generated from fixtures/corpus/BIBLE.md")
    print("=" * 72)
    for item in sorted(written, key=lambda w: w.relative):
        print(
            f"  {item.kind:<9} {item.relative:<52} "
            f"{len(item.payload):>7} B  {item.sha256[:12]}"
        )
    print("=" * 72)
    for line in ocr_confidence_report(CORPUS):
        print(line)
    unverified = 0
    if not args.no_roundtrip:
        print("round-trip through baraza.ingest.readers:")
        lines, unverified = roundtrip_check(CORPUS)
        for line in lines:
            print(line)
    print()
    if unverified:
        print(
            f"{len(written)} artifacts written, but {unverified} did not round "
            "trip through baraza.ingest.readers."
        )
        print(
            "  A skipped reader is a missing declared dependency, not a pass: "
            "install\n  the extras (`make install`) and re-run. The corpus on "
            "disk is only as\n  good as the readers that were present when it "
            "was checked."
        )
        return 1
    print(f"{len(written)} artifacts. Verify the plants with: make verify-manifest")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
