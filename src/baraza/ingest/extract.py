"""Claim extraction — turning a chunk into citation-bearing claims.

The extractor is given a chunk whose every line is prefixed with its locator,
and is instructed to return, for each claim, an ``anchor`` chosen from **that
closed set**. It cannot invent a citation because it is not asked to produce one
— it is asked to select one.

Three validation gates run on every returned claim, in this order, and a claim
that fails any of them is dropped with a named reason rather than repaired:

1. **Anchor membership.** The anchor must be one of the chunk's locators. A
   model that returns ``p.9 ¶1`` for a chunk containing only page 4 has
   hallucinated, and the claim is discarded.
2. **Quote grounding.** The quote must actually appear in the cited unit, after
   whitespace normalization. This catches the subtler failure where the anchor
   is real but the quote is a paraphrase.
3. **Schema validity.** Mandatory quote, resolvable interval, an object of some
   kind. Enforced by ``Claim.create`` itself, so it cannot be skipped.

Rejected extractions are counted and reported. A silent drop rate is
indistinguishable from a working extractor, so the pipeline prints both.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from baraza.ingest.chunking import Chunk
from baraza.ingest.sources import Source, SourceRegistry
from baraza.llm import LLMClient
from baraza.schema.claim import Anchor, CitationError, Claim, Provenance, Tier
from baraza.schema.temporal import TemporalError, to_epoch_millis
from baraza.schema.visibility import Visibility

__all__ = ["ExtractionResult", "ClaimExtractor", "EXTRACTION_SCHEMA_NAME"]

EXTRACTION_SCHEMA_NAME = "claims.v1"

_SYSTEM = """\
You extract durable institutional facts from a student organization's records \
and return them as structured claims. You are a careful archivist, not a \
summarizer: you record what a document says, including where it contradicts \
another document, and you never smooth over a discrepancy.

Rules you never break:

* Every claim cites exactly one anchor, and that anchor MUST be copied verbatim \
from the bracketed locators in the excerpt. Never construct a locator.
* Every claim carries a quote that appears VERBATIM in the cited line. Copy it; \
do not paraphrase, do not correct spelling, do not expand abbreviations.
* If a line states a period of validity ("for the 2024-25 year", "until the \
spring election"), record it. If it does not, leave the interval null. Never \
infer a period from context.
* Record what the document asserts, not what is true. Two documents disagreeing \
is the most valuable thing you can find; extract BOTH sides faithfully.
* If a line contains no durable fact, return no claim for it. An empty result is \
a valid and common answer.
"""

_PROMPT = """\
Extract every durable institutional fact from the excerpt below.

Return JSON only, matching this shape exactly:

{{
  "claims": [
    {{
      "subject": "a short noun phrase naming who or what the fact is about",
      "predicate": "a short verb phrase naming the relation",
      "predicate_hint": "2-4 lowercase words categorising the relation, used for \
grouping related claims across documents (e.g. 'signing authority', 'dues \
amount', 'officer term')",
      "object": "the value, entity, or amount asserted",
      "quote": "verbatim text from the cited line",
      "anchor": "one of the bracketed locators, copied exactly",
      "valid_from": "ISO-8601 with offset, or null",
      "valid_until": "ISO-8601 with offset, or null"
    }}
  ]
}}

Valid anchors for this excerpt — you must choose from these and no others:
{locators}

Excerpt:
{text}
"""


@dataclass(slots=True)
class ExtractionResult:
    """Claims and, just as importantly, what was thrown away and why."""

    claims: List[Claim] = field(default_factory=list)
    rejected: List[Tuple[str, Dict[str, Any]]] = field(default_factory=list)
    chunks_processed: int = 0
    raw_returned: int = 0

    @property
    def rejection_rate(self) -> Optional[float]:
        if self.raw_returned == 0:
            return None
        return round(len(self.rejected) / self.raw_returned, 4)

    def describe(self) -> str:
        rate = self.rejection_rate
        rate_text = "n/a" if rate is None else f"{rate:.1%}"
        return (
            f"extraction: {len(self.claims)} claims kept from {self.raw_returned} "
            f"returned across {self.chunks_processed} chunks "
            f"({len(self.rejected)} rejected, {rate_text})"
        )

    def rejection_summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for reason, _ in self.rejected:
            key = reason.split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


class ClaimExtractor:
    """One extraction call per chunk, with every result verified against source.

    The extractor writes claims at tier ``pending`` and visibility ``private``,
    and it has no code path that writes ``committed``. That is enforced twice:
    here, by never constructing a committed claim, and in production by the
    extractor's service account lacking permission to write the promotion event
    at all. The IAM binding is the real control; this is the readable one.
    """

    def __init__(self, client: LLMClient, registry: SourceRegistry):
        self.client = client
        self.registry = registry

    def extract_chunk(self, chunk: Chunk) -> ExtractionResult:
        result = ExtractionResult(chunks_processed=1)

        locator_list = "\n".join(f"  [{loc}]" for loc in chunk.locators)
        prompt = _PROMPT.format(locators=locator_list, text=chunk.text)

        response = self.client.generate(
            role="fast",
            prompt=prompt,
            system=_SYSTEM,
            schema_name=EXTRACTION_SCHEMA_NAME,
            temperature=0.0,
        )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            result.rejected.append(
                ("unparseable-response", {"error": str(exc), "chunk": chunk.chunk_id})
            )
            return result

        raw_claims = payload.get("claims") or []
        result.raw_returned = len(raw_claims)

        allowed = set(chunk.locators)
        for raw in raw_claims:
            claim, reason = self._build(raw, chunk, allowed)
            if claim is None:
                result.rejected.append((reason, raw))
            else:
                result.claims.append(claim)
        return result

    def _build(
        self, raw: Dict[str, Any], chunk: Chunk, allowed: set[str]
    ) -> Tuple[Optional[Claim], str]:
        anchor_locator = (raw.get("anchor") or "").strip().strip("[]")

        # Gate 1 — anchor membership.
        if anchor_locator not in allowed:
            return None, (
                f"anchor-not-in-chunk: {anchor_locator!r} is not one of this "
                f"chunk's {len(allowed)} locators"
            )

        unit = chunk.unit(anchor_locator)
        if unit is None:  # unreachable given the membership check, kept explicit
            return None, f"anchor-unresolvable: {anchor_locator!r}"

        quote = (raw.get("quote") or "").strip()
        source: Source = self.registry.get(chunk.source_id)
        anchor = Anchor(
            source_id=chunk.source_id,
            locator=anchor_locator,
            checksum=source.checksum,
        )

        # Gate 2 — quote grounding.
        ok, detail = self.registry.verify_quote(anchor, quote)
        if not ok:
            return None, f"quote-not-grounded: {detail}"

        # Gate 3 — schema validity, enforced by the constructor.
        try:
            claim = Claim.create(
                subject_id=_entity_key(raw.get("subject", "")),
                predicate=(raw.get("predicate") or "").strip(),
                predicate_hint=(raw.get("predicate_hint") or "").strip().lower(),
                quote=quote,
                anchor=anchor,
                observed_at=(
                    unit.observed_at
                    if unit.observed_at is not None
                    else source.observed_at
                ),
                object_literal=str(raw.get("object", "")).strip() or None,
                valid_from=raw.get("valid_from") or None,
                valid_until=raw.get("valid_until") or None,
                # Extractors produce pending, private claims. Only the approval
                # path promotes, and only an approver chooses visibility.
                tier=Tier.PENDING,
                visibility=Visibility.PRIVATE,
                provenance=Provenance.CORPUS,
                extra={
                    "chunk_id": chunk.chunk_id,
                    "unit_confidence": unit.confidence,
                    "source_format": chunk.format_hint,
                },
            )
        except CitationError as exc:
            return None, f"citation-invalid: {exc}"
        except TemporalError as exc:
            return None, f"temporal-invalid: {exc}"
        except ValueError as exc:
            return None, f"schema-invalid: {exc}"

        return claim, ""


def _entity_key(name: str) -> str:
    """Provisional entity id from a surface form.

    Deliberately naive — normalization is the entity pass's job, and doing it
    here would hide the aliasing problem the scorecard is supposed to measure.
    """
    slug = "-".join(name.strip().lower().split())
    return f"ent:{slug}" if slug else "ent:unknown"
