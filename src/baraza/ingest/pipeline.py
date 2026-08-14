"""The ingestion pipeline — read → chunk → filter → extract → resolve → append.

This is the unattended path. It runs as a Cloud Run Job, it runs on a cold
corpus with no human present, and every stage reports what it did in terms that
can be checked rather than believed.

    sources ──▶ chunks ──▶ [prefilter] ──▶ [extract] ──▶ claims
                                                           │
                                    entity observation ◀───┤
                                                           ▼
                                              claim.asserted events
                                                           │
                                                           ▼
                                              on-write contradiction detection

The pipeline never writes a ``committed`` claim and has no code path that could.
Promotion happens only through the approval flow in ``interview/``, and in
production the ingestion service account lacks the IAM permission to write a
``claim.committed`` event at all.

Idempotence is inherited, not implemented: claim IDs and event IDs are content
hashes, so a Job that dies halfway and is retried appends nothing twice.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from baraza.fold.store import EventStore
from baraza.ingest.chunking import Chunk, chunk_source
from baraza.ingest.entities import AliasPass, EntityTable
from baraza.ingest.extract import ClaimExtractor, ExtractionResult
from baraza.ingest.prefilter import FilterReport, RelevanceFilter, open_filter
from baraza.ingest.readers import read_source
from baraza.ingest.sources import Source, SourceRegistry
from baraza.llm import LLMClient
from baraza.schema.claim import Claim
from baraza.schema.event import Event, EventType

__all__ = ["IngestionReport", "IngestionPipeline", "SourceSpec"]


@dataclass(frozen=True, slots=True)
class SourceSpec:
    """One document to ingest, with the instant its content was authored.

    ``observed_at`` is declared in the corpus manifest rather than read from the
    filesystem: a file's mtime records when it was copied onto this machine,
    which has nothing to do with when the minutes were taken.
    """

    path: Path
    source_id: str
    observed_at: str
    note: str = ""


@dataclass(slots=True)
class IngestionReport:
    """What the run did. Every figure here is a count of a real thing."""

    sources_read: int = 0
    units_registered: int = 0
    chunks_built: int = 0
    filter_report: Optional[FilterReport] = None
    extraction: ExtractionResult = field(default_factory=ExtractionResult)
    entities_observed: int = 0
    alias_proposals: int = 0
    alias_proposals_needing_human: int = 0
    events_appended: int = 0
    events_deduplicated: int = 0
    elapsed_ms: int = 0
    offline: bool = True

    def describe(self) -> List[str]:
        lines = [
            f"sources read        {self.sources_read}",
            f"units registered    {self.units_registered}",
            f"chunks built        {self.chunks_built}",
        ]
        if self.filter_report:
            lines.append(f"{self.filter_report.describe()}")
        lines.extend(
            [
                self.extraction.describe(),
                f"entities observed   {self.entities_observed}",
                f"alias proposals     {self.alias_proposals} "
                f"({self.alias_proposals_needing_human} need a human)",
                f"events appended     {self.events_appended} "
                f"({self.events_deduplicated} already present, deduplicated)",
                # Provenance is attached to the number, not left to the reader.
                f"elapsed             {self.elapsed_ms} ms "
                f"(measured in-process, {'offline replay' if self.offline else 'live'})",
            ]
        )
        rejections = self.extraction.rejection_summary()
        if rejections:
            lines.append("rejected extractions by reason:")
            lines.extend(f"    {reason:<28} {count}" for reason, count in rejections.items())
        return lines


class IngestionPipeline:
    """Cold-corpus ingestion, end to end."""

    def __init__(
        self,
        *,
        client: LLMClient,
        store: EventStore,
        registry: Optional[SourceRegistry] = None,
        prefilter: Optional[RelevanceFilter] = None,
        on_claim: Optional[Callable[[Claim], None]] = None,
        offline: bool = True,
    ):
        self.client = client
        self.store = store
        self.registry = registry or SourceRegistry()
        self.prefilter = prefilter or open_filter()
        self.entities = EntityTable()
        self.alias_pass = AliasPass(client)
        self.offline = offline
        self._on_claim = on_claim
        """Called for each accepted claim, immediately after its event is
        appended. This is the hook the reconciler attaches to for **on-write**
        contradiction detection — detection is not a separate sweep over the
        corpus, and wiring it here is what keeps it from becoming one."""

    # ------------------------------------------------------------------ read

    def register(self, specs: Sequence[SourceSpec]) -> List[Source]:
        sources: List[Source] = []
        for spec in specs:
            source = read_source(
                spec.path, source_id=spec.source_id, observed_at=spec.observed_at
            )
            if spec.note:
                source.notes = f"{source.notes}; {spec.note}".strip("; ")
            self.registry.register(source)
            sources.append(source)
        return sources

    # ------------------------------------------------------------------- run

    def run(self, specs: Sequence[SourceSpec]) -> IngestionReport:
        started = time.perf_counter()
        report = IngestionReport(offline=self.offline)

        sources = self.register(specs)
        report.sources_read = len(sources)
        report.units_registered = sum(len(s.units) for s in sources)

        chunks: List[Chunk] = []
        for source in sources:
            chunks.extend(chunk_source(source))
        report.chunks_built = len(chunks)

        kept, filter_report = self.prefilter.run(chunks)
        report.filter_report = filter_report

        extractor = ClaimExtractor(self.client, self.registry)
        for chunk in kept:
            result = extractor.extract_chunk(chunk)
            report.extraction.claims.extend(result.claims)
            report.extraction.rejected.extend(result.rejected)
            report.extraction.raw_returned += result.raw_returned
            report.extraction.chunks_processed += 1

        for claim in report.extraction.claims:
            self.entities.observe(
                claim.subject_id,
                claim.subject_id.removeprefix("ent:").replace("-", " "),
                source_id=claim.anchor.source_id,
            )

            event = Event.create(
                event_type=EventType.CLAIM_ASSERTED,
                occurred_at=claim.observed_at,
                payload={"claim": claim.to_dict()},
                actor="ingest",
            )
            if self.store.append(event):
                report.events_appended += 1
            else:
                report.events_deduplicated += 1

            if self._on_claim is not None:
                self._on_claim(claim)

        report.entities_observed = len(self.entities)

        proposals = self.alias_pass.propose(self.entities)
        report.alias_proposals = len(proposals)
        report.alias_proposals_needing_human = sum(1 for p in proposals if p.needs_human)

        # An alias edge is asserted as of the latest evidence that supports it,
        # i.e. the newest source in this run. Derived from the sources rather
        # than from wall-clock time so a re-ingest of the same corpus produces
        # the same event IDs and therefore appends nothing twice.
        alias_instant = max((s.observed_at for s in sources), default=0)

        for proposal in proposals:
            if proposal.needs_human:
                # Unconfirmed proposals are written for review and NOT applied.
                # A pipeline that auto-applied its ambiguous guesses would be
                # making destructive identity decisions unattended.
                continue
            event = Event.create(
                event_type=EventType.ENTITY_ALIAS_LINKED,
                occurred_at=alias_instant,
                payload={
                    "alias_id": proposal.alias_id,
                    "canonical_id": proposal.canonical_id,
                    "rule": proposal.rule,
                },
                actor="ingest",
            )
            if self.store.append(event):
                report.events_appended += 1

        report.elapsed_ms = int((time.perf_counter() - started) * 1000)
        return report

    # --------------------------------------------------------------- artifacts

    def save_registry(self, path: Path | str) -> Path:
        """Persist the source registry so ``make verify-anchors`` can run
        standalone, without re-reading every PDF."""
        return self.registry.save(path)

    def save_alias_review(self, path: Path | str) -> Path:
        return self.alias_pass.write_review_file(
            self.alias_pass.propose(self.entities), path
        )
