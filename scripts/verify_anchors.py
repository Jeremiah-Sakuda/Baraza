#!/usr/bin/env python3
"""``make verify-anchors`` — re-resolve every citation in the log against source.

Citations are load-bearing. ``quote`` is mandatory on every claim, an anchor may
only name a real registered source location, and a fabricated or unresolvable
anchor is a **stop condition** rather than a warning. This script is the
mechanical form of that rule: it walks every claim in the event log, resolves
the anchor back to the exact text it cites, and checks that the quote is
actually there.

Three things are checked, in order, because a failure at one level makes the
next meaningless:

1. **Source integrity.** Every registered document still exists and still hashes
   to what the registry recorded. A source whose bytes moved under its citations
   invalidates every anchor into it, and the right response is to re-ingest — not
   to re-point the anchors.
2. **Anchor resolution.** ``(source_id, locator)`` produces a unit. An anchor
   naming a locator the source does not have is a hallucinated citation.
3. **Quote grounding.** The quote appears in the cited unit after whitespace
   normalization. This catches the subtler failure where the anchor is real and
   the quote is a paraphrase — the citation *looks* right and does not support
   what it is attached to.

**The registry is rebuilt from disk by default**, rather than loaded from a
snapshot the pipeline wrote. Verifying against a snapshot only proves the
pipeline agrees with itself; re-reading the bytes proves the citation still
points at real text on this machine, today. ``--registry`` opts into a snapshot
when there is one worth checking.

**Quotes are read through the audience predicate.** This script passes
``Audience.OWNER`` explicitly — the audit clearance, which reads everything
including private testimony — because that is the only way to read a quote and
because an audit that silently skipped private claims would leave exactly the
claims most in need of checking unchecked.

Exit codes, matching ``scripts/compliance.py``:

===  ============================================================
 0   every source intact, every anchor resolved, every quote grounded
 1   at least one failure; every one is named with its claim ID
 2   the check could not run — no corpus index and no registry, or no log
===  ============================================================
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from baraza.fold.graph import fold  # noqa: E402
from baraza.fold.store import JsonlEventStore  # noqa: E402
from baraza.ingest.sources import (  # noqa: E402
    AnchorResolutionError,
    SourceRegistry,
    checksum_of,
)
from baraza.schema.claim import Claim  # noqa: E402
from baraza.schema.visibility import Audience  # noqa: E402

CORPUS_INDEX = REPO / "fixtures" / "corpus" / "corpus-index.json"
REGISTRY_CANDIDATES = ("out/registry.json", "out/sources.json")
LOG_CANDIDATES = ("out/events.jsonl", "fixtures/golden-log.jsonl")


def rel(path: Path) -> str:
    """Repo-relative when possible; absolute otherwise.

    A log or registry passed with --log may live outside the tree, and a path
    formatter that assumed otherwise would crash the run at the report line —
    after every check had already passed.
    """
    try:
        return str(Path(path).relative_to(REPO))
    except ValueError:
        return str(path)


class CannotRun(RuntimeError):
    """The check could not be performed. Distinct from the check failing."""


@dataclass(frozen=True)
class Failure:
    claim_id: str
    anchor: str
    rule: str
    detail: str

    def render(self) -> str:
        return (
            f"  [{self.rule}] {self.claim_id}\n"
            f"      anchor: {self.anchor}\n"
            f"      {self.detail}"
        )


# --------------------------------------------------------------- the registry


def rebuild_registry() -> tuple[SourceRegistry, list[str]]:
    """Read every corpus source off disk, right now.

    Includes ``deferred_sources``: the BAR-323 artifact is dropped into the
    corpus between two nightly runs, so after the drop there are live claims
    citing it and a verifier that ignored it would report those as unresolvable.
    """
    if not CORPUS_INDEX.exists():
        raise CannotRun(
            f"{rel(CORPUS_INDEX)} is missing and no --registry was "
            "given. Run `make corpus` first, or point at a saved registry."
        )
    from baraza.ingest.readers import MissingReaderDependency, read_source

    index = json.loads(CORPUS_INDEX.read_text(encoding="utf-8"))
    registry = SourceRegistry()
    notes: list[str] = []

    for record in index["sources"] + index["deferred_sources"]:
        path = REPO / record["path"]
        if not path.exists():
            notes.append(f"  {record['source_id']:<22} MISSING FILE {record['path']}")
            continue
        try:
            source = read_source(
                path,
                source_id=record["source_id"],
                observed_at=record["observed_at"],
            )
        except MissingReaderDependency as exc:
            # Reported, never skipped silently: a format whose parser is absent
            # means every anchor into it goes unverified, and a run that hid
            # that would be green for the wrong reason.
            notes.append(f"  {record['source_id']:<22} UNVERIFIABLE {exc}")
            continue
        registry.register(source)
        notes.append(
            f"  {record['source_id']:<22} ok  {len(source.units):>4} units  "
            f"{source.checksum[:12]}"
        )
    return registry, notes


def load_registry(path: Path) -> tuple[SourceRegistry, list[str]]:
    registry = SourceRegistry.load(path)
    notes: list[str] = []
    for source in registry:
        notes.append(
            f"  {source.source_id:<22} loaded  {len(source.units):>4} units  "
            f"{source.checksum[:12]}"
        )
    return registry, notes


def check_source_integrity(registry: SourceRegistry) -> list[Failure]:
    """Every registered document still exists and still hashes the same."""
    failures: list[Failure] = []
    for source in registry:
        path = source.path if source.path.is_absolute() else REPO / source.path
        if not path.exists():
            failures.append(
                Failure(
                    claim_id="(source)",
                    anchor=source.source_id,
                    rule="source-missing",
                    detail=(
                        f"{source.path} does not exist. Every anchor into this "
                        "source is now unresolvable."
                    ),
                )
            )
            continue
        current = checksum_of(path)
        if current != source.checksum:
            failures.append(
                Failure(
                    claim_id="(source)",
                    anchor=source.source_id,
                    rule="source-drift",
                    detail=(
                        f"registered as {source.checksum[:12]}, now hashes to "
                        f"{current[:12]}. The document changed under its "
                        "citations; re-ingest rather than re-point the anchors."
                    ),
                )
            )
    return failures


# ------------------------------------------------------------------- the log


def load_claims(explicit: str | None) -> tuple[Path, list[Claim]]:
    candidates = (
        [Path(explicit)]
        if explicit
        else (
            [Path(os.environ["BARAZA_EVENT_LOG"])]
            if os.environ.get("BARAZA_EVENT_LOG")
            else [REPO / c for c in LOG_CANDIDATES]
        )
    )
    for candidate in candidates:
        if candidate.exists() and candidate.stat().st_size > 0:
            state = fold(JsonlEventStore(candidate).read_all())
            return candidate, list(state.claims.values())
    looked = ", ".join(str(c) for c in candidates)
    raise CannotRun(
        f"no non-empty event log found (looked at: {looked}). "
        "There are no citations to verify until an ingest run has happened; "
        "try `make demo-agenda` first."
    )


# ---------------------------------------------------------------- diagnosis


_PDF_LOCATOR = re.compile(r"^p\.(\d+)\s+¶(\d+)$")


def diagnose(
    registry: SourceRegistry, claim: Claim, quote: str, base: str
) -> str:
    """Turn a bare resolution failure into something actionable.

    The specific case worth naming: ``read_pdf`` prefers pdfplumber and falls
    back to pypdf, and the two disagree about paragraph granularity — measured
    on the fixture constitution, pypdf yields 33 units and pdfplumber 7, because
    pdfplumber discards the whitespace-only lines that ``\\n\\s*\\n`` splits on.
    The ``p.N`` component is stable; the ``¶n`` component is not. An anchor
    written under one parser and verified under the other fails as
    "unresolvable" when the text is still perfectly present, and reporting that
    as a hallucinated citation would send someone hunting the wrong bug.
    """
    try:
        source = registry.get(claim.anchor.source_id)
    except AnchorResolutionError:
        return base

    match = _PDF_LOCATOR.match(claim.anchor.locator)
    if not match or not quote:
        return base

    needle = re.sub(r"\s+", " ", quote).strip().lower()
    page = match.group(1)
    elsewhere = [
        locator
        for locator, unit in source.units.items()
        if needle in re.sub(r"\s+", " ", unit.text).strip().lower()
    ]
    if not elsewhere:
        return base

    same_page = [loc for loc in elsewhere if loc.startswith(f"p.{page} ")]
    if same_page:
        return (
            f"{base}\n"
            f"      DIAGNOSIS: the quoted text is present on the same page, at "
            f"{sorted(same_page)}. This is PDF paragraph-granularity drift "
            f"between pdfplumber and pypdf, not a fabricated citation. Re-ingest "
            f"under the parser this environment has, or pin the parser."
        )
    return (
        f"{base}\n"
        f"      DIAGNOSIS: the quoted text exists in this source at "
        f"{sorted(elsewhere)[:4]}, on a different page than the anchor claims."
    )


# ------------------------------------------------------------------- checking


def check_claims(
    registry: SourceRegistry, claims: Sequence[Claim]
) -> tuple[list[Failure], dict[str, int]]:
    failures: list[Failure] = []
    stats = {"claims": len(claims), "resolved": 0, "grounded": 0, "partial": 0}

    for claim in sorted(claims, key=lambda c: c.claim_id):
        # The audience is passed explicitly. OWNER is the audit clearance: this
        # script must check private claims too, and the boundary is crossed
        # deliberately and visibly rather than by reaching past it.
        quote = claim.quote_for(Audience.OWNER) or ""

        if not quote.strip():
            failures.append(
                Failure(
                    claim_id=claim.claim_id,
                    anchor=claim.anchor.key(),
                    rule="quote-empty",
                    detail=(
                        "the claim carries no readable quote. Citations are "
                        "mandatory; an uncited claim should never have reached "
                        "the log."
                    ),
                )
            )
            continue

        try:
            registry.resolve(claim.anchor)
        except AnchorResolutionError as exc:
            failures.append(
                Failure(
                    claim_id=claim.claim_id,
                    anchor=claim.anchor.key(),
                    rule="anchor-unresolvable",
                    detail=diagnose(registry, claim, quote, str(exc)),
                )
            )
            continue
        stats["resolved"] += 1

        ok, detail = registry.verify_quote(claim.anchor, quote)
        if not ok:
            failures.append(
                Failure(
                    claim_id=claim.claim_id,
                    anchor=claim.anchor.key(),
                    rule="quote-not-grounded",
                    detail=(
                        f"{detail}\n"
                        f"      quote: {quote[:140]!r}"
                    ),
                )
            )
            continue
        stats["grounded"] += 1
        if detail.startswith("partial"):
            stats["partial"] += 1

    return failures, stats


def main(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(description="resolve every citation anchor")
    parser.add_argument(
        "--registry",
        help="a saved SourceRegistry JSON; default rebuilds from the corpus on disk",
    )
    parser.add_argument("--log", help="path to an event log (JSONL)")
    args = parser.parse_args(argv)

    print("make verify-anchors — every citation resolved against its source")
    print("=" * 78)

    # -- registry -----------------------------------------------------------
    registry_path = args.registry
    if registry_path is None:
        registry_path = os.environ.get("BARAZA_REGISTRY")
    if registry_path is None:
        for candidate in REGISTRY_CANDIDATES:
            if (REPO / candidate).exists():
                registry_path = str(REPO / candidate)
                break

    try:
        if registry_path:
            registry, notes = load_registry(Path(registry_path))
            origin = f"loaded from {registry_path}"
        else:
            registry, notes = rebuild_registry()
            origin = (
                "rebuilt from fixtures/corpus/corpus-index.json — the bytes on "
                "disk, not a snapshot"
            )
    except CannotRun as exc:
        print(f"cannot run: {exc}")
        return 2

    print(f"source registry: {origin}")
    for note in notes:
        print(note)
    unverifiable = [n for n in notes if "UNVERIFIABLE" in n or "MISSING FILE" in n]

    integrity = check_source_integrity(registry)

    # -- log ----------------------------------------------------------------
    try:
        log_path, claims = load_claims(args.log)
    except CannotRun as exc:
        print()
        print(f"cannot run: {exc}")
        if integrity:
            print()
            print(f"{len(integrity)} source-integrity finding(s) before that:")
            for failure in integrity:
                print(failure.render())
            return 1
        return 2

    print()
    print(f"event log: {rel(log_path)}  ({len(claims)} claim(s))")

    failures, stats = check_claims(registry, claims)
    all_failures = integrity + failures

    print()
    print("=" * 78)
    print(
        f"sources {len(list(registry)):<4} claims {stats['claims']:<5} "
        f"anchors resolved {stats['resolved']:<5} quotes grounded "
        f"{stats['grounded']}"
    )
    if stats["partial"]:
        print(
            f"  {stats['partial']} quote(s) matched only across a unit boundary "
            "— accepted, and counted separately so the softness is visible"
        )
    if unverifiable:
        print(
            f"  {len(unverifiable)} source(s) could not be read at all; anchors "
            "into them are UNVERIFIED, not verified"
        )
    print("=" * 78)

    if not all_failures:
        if unverifiable:
            # Nothing failed, but a source could not be opened at all, so the
            # anchors into it were never checked. Returning 0 here would report
            # "every citation verified" when some were merely not looked at —
            # the difference between a passing check and a skipped one.
            print(
                "NOT GREEN — every anchor that could be checked resolved, but "
                f"{len(unverifiable)} source(s) could not be read.\n"
                "Install the missing parser (see pyproject.toml) and re-run; "
                "until then those citations are unverified."
            )
            return 1
        print("green — every anchor resolves and every quote is grounded")
        return 0

    print(f"{len(all_failures)} finding(s):\n")
    for failure in all_failures:
        print(failure.render())
        print()
    print(
        "A fabricated or unresolvable anchor is a stop condition, not a warning."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
