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
``claim.committed`` is constructed in exactly one module,
``interview/approval.py``; nothing in ``baraza.ingest`` imports it, and nothing
here constructs that event type. Stated precisely, because the looser version is
tempting and false: the deployed ingest Job enters through ``baraza.cli`` (see
``deploy/entrypoint-job.sh``), and ``cli.py`` *does* import ``ApprovalFlow`` for
the local demo flow — so what isolates this Job is the code path it takes, not
the absence of the module from its process. Alongside that,
``deploy/firestore.rules`` denies the event type on ``create`` for every
rules-governed caller.

It is **not** IAM. Firestore's permissions are per-operation and carry no
predicate over document contents, so the ingest and interview accounts hold the
same append role. What IAM does enforce is the append-only guarantee — create,
never update or delete. ``deploy/README.md`` has the per-row matrix.

Idempotence is inherited, not implemented: claim IDs and event IDs are content
hashes, so a Job that dies halfway and is retried appends nothing twice.

**One bad chunk does not cost the night.** A transient model failure on chunk 40
of 200 used to propagate out of ``run`` and kill the container; Scheduler would
retry, hit the same weather, and the night would end up missing from the
execution history that is this project's primary evidence of autonomy. Each
chunk's extraction is now wrapped: a failure is appended to the rejection list
under ``extraction-call-failed`` and the run continues. The rejection summary
already prints, so a degraded night is legible rather than silent — and a run
that lost half its chunks looks nothing like a run that found nothing.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from baraza.fold.store import EventStore
from baraza.ingest.chunking import Chunk, chunk_source
from baraza.ingest.entities import AliasPass, EntityTable
from baraza.ingest.extract import AgentClaimExtractor, ClaimExtractor, ExtractionResult
from baraza.ingest.prefilter import FilterReport, RelevanceFilter, open_filter
from baraza.ingest.readers import read_source
from baraza.ingest.sources import Source, SourceRegistry
from baraza.llm import LLMClient
from baraza.schema.claim import Claim
from baraza.schema.event import Event, EventType

__all__ = ["IngestionReport", "IngestionPipeline", "SourceSpec"]


def _resolve_agent_extraction(explicit: bool | None, offline: bool) -> bool:
    """Choose the extraction path: argument, then environment, then offline."""
    if explicit is not None:
        return explicit
    flag = os.environ.get("BARAZA_AGENT_EXTRACTION")
    if flag is not None and flag.strip() != "":
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    return not offline


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
    filter_report: FilterReport | None = None
    extraction: ExtractionResult = field(default_factory=ExtractionResult)
    entities_observed: int = 0
    alias_proposals: int = 0
    alias_proposals_needing_human: int = 0
    events_appended: int = 0
    events_deduplicated: int = 0
    elapsed_ms: int = 0
    offline: bool = True
    extraction_path: str = "direct"
    """``"adk-agent"`` or ``"direct"``. Printed, because "which code path
    actually ran" is exactly the kind of thing a compliance matrix should not
    have to be trusted about."""

    def describe(self) -> list[str]:
        lines = [
            f"sources read        {self.sources_read}",
            f"units registered    {self.units_registered}",
            f"chunks built        {self.chunks_built}",
            f"extraction path     {self.extraction_path}",
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
        registry: SourceRegistry | None = None,
        prefilter: RelevanceFilter | None = None,
        on_claim: Callable[[Claim], None] | None = None,
        offline: bool = True,
        agent_extraction: bool | None = None,
    ):
        self.client = client
        self.store = store
        self.registry = registry or SourceRegistry()
        self.prefilter = prefilter or open_filter()
        self.entities = EntityTable()
        self.alias_pass = AliasPass(client)
        self.offline = offline
        self._on_claim = on_claim
        self.agent_extraction = _resolve_agent_extraction(agent_extraction, offline)
        """Which extraction path runs.

        Resolution order: the explicit argument, then ``BARAZA_AGENT_EXTRACTION``
        (``1``/``0``), then ``not offline``.

        The default is not arbitrary. The ADK agent talks to Vertex through the
        framework's own model layer, which the cassette client cannot intercept
        — so an offline replay *must* take the direct path, and there is no
        configuration in which the agent path could quietly replay a recording
        and be reported as a live run. A live run takes the agent path, which is
        what makes ADK a production execution path rather than an import.

        ``scripts/record_cassettes.py`` passes ``False`` explicitly: it drives a
        live run precisely in order to record the direct path's prompts.
        """

        # Built once, here, so that the ADK fleet's promotion-isolation check
        # runs at pipeline construction — before a document is read, on a
        # deployed run and not only under pytest.
        self.extractor: Any = (
            AgentClaimExtractor(self.registry)
            if self.agent_extraction
            else ClaimExtractor(self.client, self.registry)
        )
        """Called for each accepted claim, immediately after its event is
        appended. This is the hook the reconciler attaches to for **on-write**
        contradiction detection — detection is not a separate sweep over the
        corpus, and wiring it here is what keeps it from becoming one."""

    # ------------------------------------------------------------------ read

    def register(self, specs: Sequence[SourceSpec]) -> list[Source]:
        sources: list[Source] = []
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
        report = IngestionReport(
            offline=self.offline,
            extraction_path="adk-agent" if self.agent_extraction else "direct",
        )

        sources = self.register(specs)
        report.sources_read = len(sources)
        report.units_registered = sum(len(s.units) for s in sources)

        chunks: list[Chunk] = []
        for source in sources:
            chunks.extend(chunk_source(source))
        report.chunks_built = len(chunks)

        kept, filter_report = self.prefilter.run(chunks)
        report.filter_report = filter_report

        for chunk in kept:
            try:
                result = self.extractor.extract_chunk(chunk)
            except Exception as exc:  # noqa: BLE001 - deliberate boundary
                # The unattended path's answer to "what happens at 3am". One
                # transient 429 on chunk 40 of 200 used to end the night; now it
                # costs one chunk and says which one, by name, in the summary.
                report.extraction.rejected.append(
                    (
                        f"extraction-call-failed: {type(exc).__name__}: {exc}",
                        {"chunk_id": chunk.chunk_id},
                    )
                )
                report.extraction.chunks_processed += 1
                continue
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
