#!/usr/bin/env python3
"""BAR-007 — the compliance audit. ``make compliance``.

Two jobs.

**The PRD audit**, as specified by BAR-007: extract every ``BAR-###`` defined in
``docs/PRD.md`` §4, diff that set against the IDs cited in §2's compliance
matrix and against IDs referenced anywhere in the PRD prose, and exit nonzero on

  * an **orphan** — an ID defined in §4 that nothing references;
  * a **dangling reference** — an ID referenced that §4 never defines;
  * **range notation in a matrix cell** — cells enumerate IDs, never ranges.

**The invariant lints**, which are not in BAR-007's text but exist for the same
reason it does: an invariant that only a human can check is an invariant that
survives until the first tired night. Each lint below corresponds to a named
hard constraint in AGENTS.md.

  * ``_quote_protected`` referenced outside ``src/baraza/schema/`` — the
    visibility boundary must fail closed structurally, not by convention.
  * a model-ID literal outside ``src/baraza/schema/models.py`` — the runtime is
    Gemini exclusively and the pin lives in exactly one place.
  * ``datetime.now()`` / ``time.time()`` compared against a string, or an ISO
    string used as a sort key — BAR-309's defect class.
  * a number in ``docs/metrics.json`` carrying neither a ``run_id`` + ``date``
    nor the literal string ``"not yet measured"``.

Exit codes: 0 green, 1 findings, 2 the audit could not run (missing PRD).
Every finding prints ``file:line`` so it is clickable.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
PRD = REPO / "docs" / "PRD.md"
SRC = REPO / "src"
METRICS = REPO / "docs" / "metrics.json"
SCHEMA_DIR = SRC / "baraza" / "schema"
MODELS_MODULE = SCHEMA_DIR / "models.py"

BAR_ID = re.compile(r"\bBAR-(\d{3})\b")

# "BAR-301–309", "BAR-301-309", "BAR-301 to 309", "BAR-330..336"
RANGE_NOTATION = re.compile(
    r"BAR-\d{3}\s*(?:[–—]|-{1,2}|\.{2,3}|\bto\b|\bthrough\b)\s*(?:BAR-)?\d{3}",
    re.IGNORECASE,
)

# A model-ID literal: a family name followed by a version suffix, inside quotes.
#
# The `-\d` is load-bearing. Without it the pattern fires on the *word* "Gemini"
# wherever it opens a docstring, which is prose, not a pin. Requiring the
# version separator matches gemini-3.5-pro, gemma-3-12b-it and
# text-embedding-005 while leaving discussion of the models alone.
MODEL_LITERAL = re.compile(
    r"[\"'](?:gemini|gemma|imagen|veo|lyria|text-embedding)[a-z]*-\d[a-z0-9.\-]*[\"']",
    re.IGNORECASE,
)

ISO_SORT_SMELL = re.compile(
    r"""(?x)
    sorted\([^)]*\biso\b[^)]*\)
    | \.sort\([^)]*\biso\b[^)]*\)
    | \bisoformat\(\)\s*(?:<|>|<=|>=)
    | (?:<|>|<=|>=)\s*[a-z_]*\.isoformat\(\)
    | \bstrftime\([^)]*\)\s*(?:<|>|<=|>=)
    """,
    re.IGNORECASE,
)

SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache"}


@dataclass(frozen=True)
class Finding:
    """One audit failure, addressed to a location a human can open."""

    rule: str
    location: str
    message: str

    def render(self) -> str:
        return f"  [{self.rule}] {self.location}\n      {self.message}"


# ------------------------------------------------------------------ helpers


def _iter_source_files(root: Path, suffixes: Sequence[str]) -> Iterable[Path]:
    if not root.exists():
        return
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError:  # pragma: no cover
        return str(path)


def _split_sections(text: str) -> Dict[str, str]:
    """Split the PRD on top-level ``## <n>.`` headings, keyed by section number."""
    sections: Dict[str, str] = {}
    current = "0"
    buffer: List[str] = []
    heading = re.compile(r"^#{1,3}\s+§?\s*(\d+)(?:\.\d+)*\.?\s", re.MULTILINE)

    for line in text.splitlines(keepends=True):
        match = heading.match(line)
        if match:
            sections[current] = "".join(buffer)
            current = match.group(1)
            buffer = [line]
        else:
            buffer.append(line)
    sections[current] = "".join(buffer)
    return sections


def _defined_ids(section_four: str) -> Dict[str, int]:
    """IDs *defined* in §4 — an ID at the head of a requirement heading or bold run.

    A definition looks like ``### BAR-309 (new, Phase 2) — Temporal normalization``
    or ``**BAR-309** — ...``. A bare mention inside prose is a reference, not a
    definition; conflating the two is what lets an orphan hide.
    """
    defined: Dict[str, int] = {}
    definition = re.compile(
        r"^(?:#{2,4}\s*|\*\*\s*|\|\s*)?BAR-(\d{3})\b",
    )
    for lineno, line in enumerate(section_four.splitlines(), start=1):
        match = definition.match(line.strip())
        if match:
            defined.setdefault(f"BAR-{match.group(1)}", lineno)
    return defined


def _referenced_ids(text: str, *, exclude: str = "") -> Set[str]:
    """Every ID mentioned outside the definition section."""
    body = text.replace(exclude, "") if exclude else text
    return {f"BAR-{m.group(1)}" for m in BAR_ID.finditer(body)}


def _matrix_rows(section_two: str) -> List[Tuple[int, str]]:
    """Markdown table rows in §2, with line numbers."""
    rows: List[Tuple[int, str]] = []
    for lineno, line in enumerate(section_two.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            if set(stripped) <= set("|-: "):  # separator row
                continue
            rows.append((lineno, stripped))
    return rows


# -------------------------------------------------------------- the PRD audit


def audit_prd() -> Tuple[List[Finding], Optional[str]]:
    """BAR-007 proper. Returns findings and an optional fatal message."""
    if not PRD.exists():
        return [], (
            f"{_rel(PRD)} does not exist.\n"
            "  BAR-007 audits the merged PRD v1.2 and cannot run without it.\n"
            "  Per the amendments file §6: place PRD v1.1 at docs/PRD.md, apply\n"
            "  baraza-prd-v1.2-amendments.md, then re-run. The amendments file\n"
            "  forbids reconstructing the unrecovered sections from memory."
        )

    text = PRD.read_text(encoding="utf-8")
    sections = _split_sections(text)
    section_four = sections.get("4", "")
    section_two = sections.get("2", "")

    findings: List[Finding] = []

    if not section_four.strip():
        findings.append(
            Finding(
                "prd-structure",
                f"{_rel(PRD)}",
                "§4 (requirements) is empty or unparseable; nothing to audit.",
            )
        )
        return findings, None

    defined = _defined_ids(section_four)
    referenced = _referenced_ids(text, exclude=section_four)
    matrix_ids = _referenced_ids(section_two)

    for bar_id in sorted(set(defined) - referenced):
        findings.append(
            Finding(
                "orphan",
                f"{_rel(PRD)}:{defined[bar_id]}",
                f"{bar_id} is defined in §4 but referenced nowhere else in the "
                "PRD. Either cite it from the compliance matrix or the prose, or "
                "cut it — a requirement nothing points at is a requirement "
                "nothing enforces.",
            )
        )

    for bar_id in sorted(referenced - set(defined)):
        findings.append(
            Finding(
                "dangling-ref",
                f"{_rel(PRD)}",
                f"{bar_id} is referenced but §4 never defines it. If it carried "
                "forward from v1.1, the merge dropped it.",
            )
        )

    for bar_id in sorted(matrix_ids - set(defined)):
        findings.append(
            Finding(
                "matrix-dangling",
                f"{_rel(PRD)}",
                f"the §2 compliance matrix cites {bar_id}, which §4 does not "
                "define. The matrix must never claim a requirement the PRD does "
                "not carry.",
            )
        )

    for lineno, row in _matrix_rows(section_two):
        match = RANGE_NOTATION.search(row)
        if match:
            findings.append(
                Finding(
                    "matrix-range",
                    f"{_rel(PRD)} §2:{lineno}",
                    f"matrix cell uses range notation {match.group(0)!r}. Cells "
                    "enumerate IDs, never ranges — v1.1 ruling #6. A range hides "
                    "which requirements actually back the claim.",
                )
            )

    return findings, None


# ---------------------------------------------------------- invariant lints


def lint_visibility_boundary() -> List[Finding]:
    """The quote must be unreachable outside the schema package."""
    findings: List[Finding] = []
    for path in _iter_source_files(REPO, (".py",)):
        if path.is_relative_to(SCHEMA_DIR) or path.name == "compliance.py":
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if "_quote_protected" in line:
                findings.append(
                    Finding(
                        "boundary",
                        f"{_rel(path)}:{lineno}",
                        "reaches for _quote_protected outside src/baraza/schema/. "
                        "Read the quote through claim.quote_for(audience) so the "
                        "visibility predicate cannot be forgotten.",
                    )
                )
    return findings


def lint_model_pins() -> List[Finding]:
    """Model IDs live in exactly one module."""
    findings: List[Finding] = []
    for path in _iter_source_files(REPO, (".py",)):
        if path == MODELS_MODULE or path.name == "compliance.py":
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue
            match = MODEL_LITERAL.search(line)
            if match:
                findings.append(
                    Finding(
                        "model-pin",
                        f"{_rel(path)}:{lineno}",
                        f"model-ID literal {match.group(0)} outside "
                        "schema/models.py. Resolve through models.resolve(role) "
                        "so the compliance matrix can never name a model the "
                        "code does not call.",
                    )
                )
    return findings


def lint_temporal() -> List[Finding]:
    """BAR-309: no instant is ever compared as a string."""
    findings: List[Finding] = []
    for path in _iter_source_files(SRC, (".py",)):
        if path.is_relative_to(SCHEMA_DIR) and path.name == "temporal.py":
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if line.lstrip().startswith("#"):
                continue
            if ISO_SORT_SMELL.search(line):
                findings.append(
                    Finding(
                        "temporal",
                        f"{_rel(path)}:{lineno}",
                        "compares or sorts what looks like an ISO-8601 string. "
                        "BAR-309: normalize with to_epoch_millis() and compare "
                        "integers. This exact pattern kept a revoked grant active "
                        "under mixed UTC offsets.",
                    )
                )
    return findings


def lint_metrics() -> List[Finding]:
    """Every published number carries provenance, or says it has none."""
    findings: List[Finding] = []
    if not METRICS.exists():
        return [
            Finding(
                "metrics",
                f"{_rel(METRICS)}",
                "missing. Every measurable claim needs an entry, even if that "
                'entry is the literal string "not yet measured".',
            )
        ]

    try:
        payload = json.loads(METRICS.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [Finding("metrics", f"{_rel(METRICS)}", f"invalid JSON: {exc}")]

    entries = payload.get("metrics")
    if not isinstance(entries, dict):
        return [
            Finding(
                "metrics",
                f"{_rel(METRICS)}",
                'top-level "metrics" object is missing or not an object.',
            )
        ]

    allowed_provenance = {
        "measured in-process",
        "measured deployed",
        "not yet measured",
    }

    for key, entry in sorted(entries.items()):
        if entry == "not yet measured":
            continue
        if not isinstance(entry, dict):
            findings.append(
                Finding(
                    "metrics",
                    f"{_rel(METRICS)} :: {key}",
                    'must be either the literal string "not yet measured" or an '
                    "object carrying value, provenance, run_id and date.",
                )
            )
            continue
        if entry.get("value") == "not yet measured":
            continue
        missing = [f for f in ("value", "provenance", "run_id", "date") if not entry.get(f)]
        if missing:
            findings.append(
                Finding(
                    "metrics",
                    f"{_rel(METRICS)} :: {key}",
                    f"carries a value but is missing {', '.join(missing)}. A "
                    "number without provenance is a plausible number where a "
                    'measured one belongs; write "not yet measured" instead.',
                )
            )
        provenance = entry.get("provenance")
        if provenance and provenance not in allowed_provenance:
            findings.append(
                Finding(
                    "metrics",
                    f"{_rel(METRICS)} :: {key}",
                    f"provenance {provenance!r} is not one of "
                    f"{sorted(allowed_provenance)}. In-process timings are never "
                    "reported as deployed measurements.",
                )
            )
    return findings


# -------------------------------------------------------------------- runner


def main(argv: Sequence[str]) -> int:
    strict_prd = "--no-prd" not in argv

    print("BAR-007 compliance audit")
    print("=" * 72)

    all_findings: List[Finding] = []
    fatal: Optional[str] = None

    if strict_prd:
        prd_findings, fatal = audit_prd()
        all_findings.extend(prd_findings)

    lints = [
        ("visibility boundary", lint_visibility_boundary),
        ("model pins", lint_model_pins),
        ("temporal comparisons", lint_temporal),
        ("metrics provenance", lint_metrics),
    ]
    for label, fn in lints:
        found = fn()
        all_findings.extend(found)
        status = "FAIL" if found else "ok"
        print(f"  {label:<24} {status}{f' ({len(found)})' if found else ''}")

    if fatal:
        print()
        print("PRD audit could not run:")
        print(f"  {fatal}")
        print()
        print(
            "  Re-run the lints alone with:  python3 scripts/compliance.py --no-prd"
        )
        return 2

    if strict_prd:
        print(f"  {'PRD ID audit':<24} "
              f"{'FAIL' if any(f.rule.startswith(('orphan', 'dangling', 'matrix', 'prd')) for f in all_findings) else 'ok'}")

    print("=" * 72)

    if not all_findings:
        print("green — no findings")
        return 0

    print(f"{len(all_findings)} finding(s):\n")
    for finding in all_findings:
        print(finding.render())
    print()
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
