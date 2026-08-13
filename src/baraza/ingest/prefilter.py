"""BAR-303 — the relevance pre-filter.

``filter(chunk) -> keep | drop``, sitting in the ingestion path at exactly the
point where the production call goes. Most of a chat export is scheduling noise
("can we move it to 7?", "omw"), and running the expensive extraction pass over
all of it is the difference between an ingestion that costs dollars and one that
costs tens of dollars.

**Two modes, one interface, selected by a flag.**

``stub``
    A deterministic keyword-and-shape heuristic. Committed, cheap, and
    **disclosed as a stub** — here in this docstring, in
    ``docs/metrics.json``, and in the console output of any run that used it.
    This is what unattended night-1 ingestion runs, because an unattended
    session must not block on a model pull or an endpoint provision.

``gemma``
    Gemma via a Vertex endpoint or a local Ollama. This is the real filter. Its
    survival rate is measured in a **supervised** session, with the endpoint
    scripted up and down inside that session and never left running.

The interface is final. Switching modes flips a flag; no call site changes.

**On the number.** ``docs/metrics.json`` holds either a measured survival rate
with a run ID and a date, or the literal string ``"not yet measured"``. There is
no third state and no placeholder estimate. The architecture diagram may display
only the measured value. A plausible rate written where a measured one belongs
is the specific defect this requirement was split in two to prevent.
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Iterable, List, Optional, Tuple

from baraza.ingest.chunking import Chunk
from baraza.schema import models

__all__ = [
    "FilterMode",
    "FilterVerdict",
    "RelevanceFilter",
    "StubFilter",
    "GemmaFilter",
    "open_filter",
    "FilterReport",
]


class FilterMode(str, Enum):
    STUB = "stub"
    GEMMA = "gemma"


@dataclass(frozen=True, slots=True)
class FilterVerdict:
    keep: bool
    reason: str
    mode: FilterMode
    confidence: float = 1.0


@dataclass(slots=True)
class FilterReport:
    """What a filtering pass did, in terms honest enough to publish."""

    mode: FilterMode
    considered: int = 0
    kept: int = 0

    @property
    def dropped(self) -> int:
        return self.considered - self.kept

    @property
    def survival_rate(self) -> Optional[float]:
        if self.considered == 0:
            return None
        return round(self.kept / self.considered, 4)

    def describe(self) -> str:
        """Console line. Names the mode every time.

        A survival rate produced by the stub is not the requirement's number and
        must never be recorded as one, so the mode is inseparable from the
        figure wherever it is printed.
        """
        rate = self.survival_rate
        if rate is None:
            return f"prefilter[{self.mode.value}]: nothing considered"
        suffix = (
            "  (STUB heuristic — NOT the BAR-303 measurement)"
            if self.mode is FilterMode.STUB
            else "  (gemma)"
        )
        return (
            f"prefilter[{self.mode.value}]: kept {self.kept}/{self.considered} "
            f"= {rate:.1%}{suffix}"
        )

    def metrics_entry(self, *, run_id: str, date: str) -> object:
        """The ``docs/metrics.json`` entry for this pass.

        The stub deliberately returns the literal ``"not yet measured"``: its
        rate is a property of a keyword list, not a measurement of anything, and
        writing it into the metrics file would launder a heuristic into a
        result.
        """
        if self.mode is FilterMode.STUB:
            return "not yet measured"
        rate = self.survival_rate
        if rate is None:
            return "not yet measured"
        return {
            "value": rate,
            "provenance": "measured in-process",
            "run_id": run_id,
            "date": date,
            "mode": self.mode.value,
            "model_id": models.PREFILTER.resolved(),
            "considered": self.considered,
            "kept": self.kept,
        }


class RelevanceFilter(ABC):
    """The interface. Final; only the implementation behind it changes."""

    mode: FilterMode

    @abstractmethod
    def verdict(self, chunk: Chunk) -> FilterVerdict:
        """Keep or drop one chunk."""

    def run(self, chunks: Iterable[Chunk]) -> Tuple[List[Chunk], FilterReport]:
        report = FilterReport(mode=self.mode)
        kept: List[Chunk] = []
        for chunk in chunks:
            report.considered += 1
            decision = self.verdict(chunk)
            if decision.keep:
                report.kept += 1
                kept.append(chunk)
        return kept, report


# ------------------------------------------------------------------- stub

# Terms that indicate a chunk may contain an institutional fact worth
# extracting. Deliberately broad: the stub's job is to be obviously
# conservative, because a false drop loses a claim permanently while a false
# keep only costs one extraction call.
_SIGNAL = re.compile(
    r"""(?ix)
    \b(
      budget | spend | spent | invoice | reimburs \w* | dues | funds? | account |
      treasurer | president | chair \w* | officer | secretary | advisor |
      constitution | bylaw \w* | amend \w* | quorum | vote[ds]? | motion |
      approv \w* | authoriz \w* | signator \w* | sign(?:ing)? \s+ authority |
      elect \w* | term | succeed \w* | handover | transition |
      polic \w* | rule | require \w* | deadline | contract | vendor |
      \$ \s? \d | \d+ \s? (?:dollars|usd)
    )\b
    """,
)

# Shapes that are almost always logistics rather than record. Applied only when
# no signal term is present.
_NOISE = re.compile(
    r"""(?ix)
    ^\W* (
      omw | otw | ok(?:ay)? | k | thanks? | ty | lol | lmao | \+1 | same |
      yes | no | yep | nope | sure | bet | got \s it | on \s my \s way |
      running \s late | brb | be \s there \s (?:soon|in) \s? \d* |
      can \s we \s move | does \s \w+ \s work \s for
    ) \W* $
    """,
)


class StubFilter(RelevanceFilter):
    """Deterministic keyword heuristic. **This is a stub.**

    It is committed and it runs in unattended ingestion, but it is not the
    BAR-303 filter and its survival rate is not the BAR-303 measurement. Every
    surface that reports a rate produced by this class labels it as a stub.
    """

    mode = FilterMode.STUB

    def verdict(self, chunk: Chunk) -> FilterVerdict:
        text = chunk.text

        if _SIGNAL.search(text):
            return FilterVerdict(
                keep=True, reason="signal term present", mode=self.mode
            )

        # Judge a multi-unit chunk by whether *every* line is noise. One
        # substantive line in a chunk of chatter is exactly the case that must
        # not be dropped.
        lines = [u.text.strip() for u in chunk.units if u.text.strip()]
        if lines and all(_NOISE.match(line) for line in lines):
            return FilterVerdict(
                keep=False, reason="every unit matches a logistics shape", mode=self.mode
            )

        # Very short chunks with no signal are almost never claim-bearing, but
        # "almost never" is not "never", so the threshold is low.
        if chunk.char_count < 40:
            return FilterVerdict(
                keep=False, reason="below the length floor with no signal", mode=self.mode
            )

        return FilterVerdict(
            keep=True, reason="no confident reason to drop", mode=self.mode
        )


# ------------------------------------------------------------------ gemma

_GEMMA_INSTRUCTION = """\
You are a relevance gate for an organizational-memory system. You will be shown \
an excerpt from a student organization's records: chat messages, minutes, budget \
cells, or constitution text.

Answer KEEP if the excerpt contains, or plausibly contains, any durable fact \
about how the organization operates: money, roles, authority, rules, decisions, \
deadlines, obligations, or who did what.

Answer DROP only if the excerpt is purely logistics or social chatter with no \
durable fact — scheduling, acknowledgements, greetings, reactions.

When uncertain, answer KEEP. A dropped excerpt is never seen again; a kept one \
merely costs one further call.

Answer with exactly one word: KEEP or DROP.

Excerpt:
"""


class GemmaFilter(RelevanceFilter):
    """The real filter: Gemma via a Vertex endpoint or a local Ollama.

    Fails **open** — a filter error keeps the chunk. The asymmetry is
    deliberate: an unavailable endpoint must not silently delete a night's
    worth of institutional memory, and the cost of failing open is a larger
    extraction bill rather than a hole in the record.
    """

    mode = FilterMode.GEMMA

    def __init__(self, client=None, *, endpoint: Optional[str] = None):
        self._client = client
        self.endpoint = endpoint or os.environ.get("BARAZA_GEMMA_ENDPOINT")

    @property
    def client(self):
        if self._client is None:
            from baraza.llm import open_client

            self._client = open_client(offline=False)
        return self._client

    def verdict(self, chunk: Chunk) -> FilterVerdict:
        try:
            response = self.client.generate(
                role="prefilter",
                prompt=_GEMMA_INSTRUCTION + chunk.text,
                temperature=0.0,
                max_output_tokens=4,
            )
        except Exception as exc:  # noqa: BLE001 - fail open, and say why
            return FilterVerdict(
                keep=True,
                reason=f"filter unavailable, failing open: {type(exc).__name__}",
                mode=self.mode,
                confidence=0.0,
            )

        answer = response.text.strip().upper()
        if answer.startswith("DROP"):
            return FilterVerdict(keep=False, reason="gemma: DROP", mode=self.mode)
        if answer.startswith("KEEP"):
            return FilterVerdict(keep=True, reason="gemma: KEEP", mode=self.mode)
        return FilterVerdict(
            keep=True,
            reason=f"gemma returned {answer[:20]!r}; failing open",
            mode=self.mode,
            confidence=0.0,
        )


def open_filter(mode: Optional[str] = None, **kwargs) -> RelevanceFilter:
    """Select a filter by flag.

    Defaults to ``stub``, and the default is the safe one: an unattended run
    that forgot to set the flag gets the committed heuristic and a console line
    that says so, rather than a silent attempt to reach an endpoint that may not
    be up.
    """
    resolved = (mode or os.environ.get("BARAZA_PREFILTER", "stub")).strip().lower()
    try:
        selected = FilterMode(resolved)
    except ValueError as exc:
        raise ValueError(
            f"unknown prefilter mode {resolved!r}; expected one of "
            f"{[m.value for m in FilterMode]}"
        ) from exc

    if selected is FilterMode.GEMMA:
        return GemmaFilter(**kwargs)
    return StubFilter()
