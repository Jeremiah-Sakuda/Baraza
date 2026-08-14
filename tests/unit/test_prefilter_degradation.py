"""A dead pre-filter must not look like a pre-filter that kept everything.

`GemmaFilter` fails open on purpose: an unreachable endpoint must not silently
delete a night's worth of institutional memory, and the cost of failing open is a
larger extraction bill rather than a hole in the record. That is the right call.

The problem is what it *prints*. Before this file, a pass in which every single
call raised produced `prefilter[gemma]: kept 33/33 = 100.0%  (gemma)`, which is
byte-identical to a pass in which Gemma read all 33 chunks and kept them. One of
those is a measurement and the other is an outage, and BAR-303's additional-model
bonus is claimed on the first.

This matters concretely rather than theoretically. `GemmaFilter.verdict` calls
the ordinary `generate_content` path via `models.resolve("prefilter")`, while the
pre-filter pin declares `surface="vertex-endpoint"` — a self-deployed Model Garden
endpoint, which is not addressed the same way. Nothing in the tree reads
`self.endpoint`. So the most likely outcome of the first `BARAZA_PREFILTER=gemma`
run is that every call fails and every chunk is kept, and the number that reaches
a human has to say so on its own.
"""

from __future__ import annotations

from baraza.ingest.chunking import Chunk
from baraza.ingest.prefilter import (
    FilterMode,
    FilterVerdict,
    GemmaFilter,
    RelevanceFilter,
)


def _chunk(n: int) -> Chunk:
    return Chunk(
        chunk_id=f"chunk-{n}",
        source_id="src:constitution-scan",
        units=[],
        observed_at=1_700_000_000_000,
    )


class _AlwaysRaises:
    """A client whose every call fails, like an endpoint that was never stood up."""

    def generate(self, **kwargs):
        raise ConnectionError("endpoint not found")


class _Scripted(RelevanceFilter):
    """A filter that returns exactly the verdicts a test hands it."""

    mode = FilterMode.GEMMA

    def __init__(self, verdicts: list[FilterVerdict]):
        self._verdicts = list(verdicts)

    def verdict(self, chunk: Chunk) -> FilterVerdict:
        return self._verdicts.pop(0)


def _kept(*, decided: bool) -> FilterVerdict:
    return FilterVerdict(
        keep=True, reason="scripted", mode=FilterMode.GEMMA, decided=decided
    )


def _dropped() -> FilterVerdict:
    return FilterVerdict(
        keep=False, reason="scripted", mode=FilterMode.GEMMA, decided=True
    )


class TestATotalOutageIsNotAHundredPercentSurvival:
    def test_every_chunk_survives_because_nothing_ran(self):
        chunks = [_chunk(i) for i in range(5)]
        kept, report = GemmaFilter(client=_AlwaysRaises()).run(chunks)

        # Failing open is still the behaviour. No claim is lost.
        assert len(kept) == 5
        assert report.kept == 5
        # But the pass decided nothing.
        assert report.failed_open == 5
        assert report.decided == 0
        assert report.degraded is True

    def test_the_console_line_says_the_filter_never_ran(self):
        chunks = [_chunk(i) for i in range(5)]
        _, report = GemmaFilter(client=_AlwaysRaises()).run(chunks)
        line = report.describe()

        assert "DEGRADED" in line
        assert "the filter never ran" in line
        assert "NOT a survival rate" in line

    def test_a_degraded_pass_writes_no_metric(self):
        """`metrics.json` has two legal forms; there is no "sort of measured"."""
        chunks = [_chunk(i) for i in range(5)]
        _, report = GemmaFilter(client=_AlwaysRaises()).run(chunks)

        assert report.metrics_entry(run_id="r1", date="2026-08-13") == (
            "not yet measured"
        )


class TestPartialDegradationIsAlsoDegradation:
    def test_one_failure_in_a_good_pass_still_taints_the_number(self):
        scripted = _Scripted([_kept(decided=True), _dropped(), _kept(decided=False)])
        _, report = scripted.run([_chunk(i) for i in range(3)])

        assert report.considered == 3
        assert report.kept == 2
        assert report.failed_open == 1
        assert report.decided == 2
        assert report.degraded is True
        assert "DEGRADED" in report.describe()
        assert report.metrics_entry(run_id="r1", date="2026-08-13") == (
            "not yet measured"
        )


class TestACleanPassIsStillReportedCleanly:
    """The guard must not swallow the measurement it exists to protect."""

    def test_a_pass_with_no_failures_reports_a_rate(self):
        scripted = _Scripted([_kept(decided=True), _dropped(), _kept(decided=True)])
        _, report = scripted.run([_chunk(i) for i in range(3)])

        assert report.failed_open == 0
        assert report.degraded is False
        assert "DEGRADED" not in report.describe()

        entry = report.metrics_entry(run_id="r1", date="2026-08-13")
        assert isinstance(entry, dict)
        assert entry["value"] == report.survival_rate
        assert entry["provenance"] == "measured in-process"
        assert entry["considered"] == 3
        assert entry["kept"] == 2
