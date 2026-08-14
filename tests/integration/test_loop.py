"""The loop, closed, over real corpus documents and with no credentials.

Every other test in this suite proves one component behaves. None of them
proved the components connect — and both of the two structural defects found in
this system's flagship workflow lived in the two modules with no tests at all.
One of them (a nightly filter that examined zero claims forever) would have been
caught by this file on the day it was written.

What this drives, end to end, in one process:

    real documents  →  read  →  chunk  →  prefilter  →  extract
                            →  on-write contradiction detection
                            →  fold  →  disputed ledger  →  interview agenda

Three real files out of ``fixtures/corpus/`` in three different formats — a
GroupMe export, a .docx set of minutes, a markdown handover note — read by the
real readers, chunked by the real chunker, anchored against the real registry.
The output asserted at the end is an agenda item: a question no human wrote,
derived from a disagreement between two documents that were never written with
each other in mind.

**The honesty guardrail, which is enforced below and not merely stated.**

The model is faked. ``FakeLLMClient`` returns exactly what this file scripts, so
what is measured here is *wiring* — that claims reach detection, that
contradictions reach the ledger, that the ledger reaches the agenda. It is not
a measurement of Gemini and it never becomes one:

* No number produced by this test may be written into ``docs/metrics.json``.
* No event log this test writes may satisfy ``make verify-manifest``'s behaviour
  probes; those must observe a log produced by real model calls.
* Nothing here may be shown on camera as system output.

``test_this_test_writes_nothing_outside_its_tmp_path`` enforces exactly that: it
fails if the run touched the repository's real artifacts. A guardrail that is
only a comment is a guardrail that lasts until the first person in a hurry.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from baraza.cli import OnWriteReconciler
from baraza.fold.graph import fold
from baraza.fold.store import JsonlEventStore
from baraza.ingest.pipeline import IngestionPipeline, SourceSpec
from baraza.reconcile.agenda import AgendaGenerator
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.event import EventType
from baraza.schema.visibility import Audience
from baraza_testkit import FakeLLMClient

REPO = Path(__file__).resolve().parents[2]
CORPUS = REPO / "fixtures" / "corpus"

# Three sources, three formats, three authoring dates. Chosen because they
# disagree with each other about the one thing a treasurer's successor most
# needs to know, which is what makes them the right three.
SOURCES = [
    (
        "gm-officers",
        CORPUS / "chat" / "groupme-meridian-officers.json",
        "2026-05-04T00:00:00Z",
    ),
    (
        "minutes-2023-09-12",
        CORPUS / "minutes" / "minutes-2023-09-12.docx",
        "2023-09-12T00:00:00Z",
    ),
    (
        "notes-handover",
        CORPUS / "notes" / "handover-checklist-2026-05.md",
        "2026-05-03T00:00:00Z",
    ),
]

# What the test asserts it left alone. See the module docstring.
PROTECTED = [
    REPO / "docs" / "metrics.json",
    REPO / "out" / "events.jsonl",
    REPO / "fixtures" / "transcripts",
]


pytestmark = pytest.mark.skipif(
    not all(path.exists() for _, path, _ in SOURCES),
    reason="synthetic corpus absent; run `make corpus`",
)


# ------------------------------------------------------- the scripted archivist


def _excerpt_units(prompt: str) -> list[tuple[str, str]]:
    """Recover ``(locator, text)`` from an extraction prompt.

    The stub reads the *real* excerpt out of the prompt rather than being handed
    the corpus separately, so every quote it produces is necessarily verbatim
    source text and every anchor is necessarily one the chunk offered. A stub
    that invented a quote would be testing the gates against fiction — and the
    gates would correctly reject it, which would look like a wiring failure.
    """
    head, _, excerpt = prompt.partition("Excerpt:\n")
    locators = re.findall(r"^ {2}\[(.+)\]$", head, flags=re.M)

    positions: list[tuple[str, int, int]] = []
    cursor = 0
    for locator in locators:
        marker = f"[{locator}] "
        index = excerpt.find(marker, cursor)
        if index == -1:
            continue
        positions.append((locator, index, index + len(marker)))
        cursor = index + len(marker)

    units: list[tuple[str, str]] = []
    for order, (locator, _, body_start) in enumerate(positions):
        end = (
            positions[order + 1][1] - 1
            if order + 1 < len(positions)
            else len(excerpt)
        )
        units.append((locator, excerpt[body_start:end]))
    return units


_NUMBER = re.compile(r"\b(\d{2,5})\b")


def extraction_response(prompt: str) -> str:
    """Emit one claim per line that says something about signing authority.

    Deliberately crude: a keyword and a number. It is not pretending to be an
    extractor — it is a scripted stand-in whose only job is to put well-formed,
    genuinely-grounded claims into the pipeline so the wiring downstream can be
    asserted.
    """
    claims = []
    for locator, text in _excerpt_units(prompt):
        flat = " ".join(text.split())
        if "sign" not in flat.lower():
            continue
        number = _NUMBER.search(flat)
        if not number:
            continue
        quote = flat[:110].rsplit(" ", 1)[0] if len(flat) > 110 else flat
        if quote not in " ".join(text.split()):  # paranoia; keeps it verbatim
            continue
        claims.append(
            {
                "subject": "treasurer",
                "predicate": "may sign up to",
                "predicate_hint": "signing authority",
                "object": number.group(1),
                "quote": quote,
                "anchor": locator,
                "valid_from": None,
                "valid_until": None,
            }
        )
    return json.dumps({"claims": claims})


def adjudication_response(prompt: str) -> str:
    """Call the first candidate a contradiction of the new claim.

    The detector's own retrieval decides *what* is compared — blocking key,
    temporal gate, cap. This stub only supplies the verdict, so a change that
    broke blocking would show up here as an empty prompt and no contradiction,
    which is the failure this test is for.
    """
    candidates = re.findall(r"^\s+- id: (\S+)", prompt, flags=re.M)
    if not candidates:
        return json.dumps({"contradictions": []})
    return json.dumps(
        {
            "contradictions": [
                {
                    "claim_id": candidates[0],
                    "confidence": 0.9,
                    "rationale": (
                        "Both state a signing threshold for the same role over "
                        "overlapping periods, and the amounts differ."
                    ),
                }
            ]
        }
    )


AGENDA_RESPONSE = json.dumps(
    {
        "question": (
            "The records give two different signing limits. Which one did you "
            "actually work to?"
        ),
        "why_it_matters": "It decides who could commit the organization's money.",
    }
)


@pytest.fixture
def client() -> FakeLLMClient:
    return FakeLLMClient(
        {
            "claims.v1": extraction_response,
            "contradictions.v1": adjudication_response,
            "agenda_item.v1": AGENDA_RESPONSE,
        }
    )


@pytest.fixture
def loop(tmp_path, client):
    """Run the whole loop once and hand back everything it produced."""
    store = JsonlEventStore(tmp_path / "events.jsonl")
    reconciler = OnWriteReconciler(client=client, store=store)
    pipeline = IngestionPipeline(
        client=client,
        store=store,
        on_claim=reconciler,
        offline=True,
        # The direct path, explicitly: the ADK agent talks to Vertex through the
        # framework's own model layer, which no fake at this seam can intercept.
        agent_extraction=False,
    )

    specs = [
        SourceSpec(path=path, source_id=source_id, observed_at=observed_at)
        for source_id, path, observed_at in SOURCES
    ]
    report = pipeline.run(specs)

    events = store.read_all()
    state = fold(events)
    ledger = DisputedLedger(state)
    agenda = AgendaGenerator(client).generate(state, audience=Audience.OWNER)
    return {
        "store": store,
        "events": events,
        "report": report,
        "reconciler": reconciler,
        "state": state,
        "ledger": ledger,
        "agenda": agenda,
    }


# ------------------------------------------------------------------- the loop


class TestIngestion:
    def test_three_formats_are_read_and_anchored(self, loop):
        report = loop["report"]
        assert report.sources_read == 3
        assert report.units_registered > 20
        assert report.chunks_built >= 3

    def test_every_claim_that_survived_is_citable(self, loop):
        """The gates are not bypassed by the pipeline that calls them."""
        claims = loop["report"].extraction.claims
        assert claims, "no claims survived; the loop cannot be asserted"
        for claim in claims:
            assert claim.anchor.source_id
            assert claim.anchor.locator
            assert claim.quote_for(Audience.OWNER)

    def test_claims_reach_the_log_as_asserted_events(self, loop):
        types = [e.event_type for e in loop["store"].read_all()]
        assert types.count(EventType.CLAIM_ASSERTED) == len(
            loop["report"].extraction.claims
        )


class TestDetectionHappensOnWrite:
    def test_a_contradiction_is_found_between_two_documents(self, loop):
        reconciler = loop["reconciler"]
        assert reconciler.contradictions_found >= 1, (
            "the corpus disagrees with itself and nothing noticed"
        )

        contradictions = list(loop["state"].contradictions.values())
        assert contradictions
        sources = {
            loop["state"].claims[cid].anchor.source_id
            for c in contradictions
            for cid in c.claim_ids
            if cid in loop["state"].claims
        }
        assert len(sources) >= 2, (
            "every contradiction is inside one document; cross-source detection "
            "is the property that matters and it is not being exercised"
        )

    def test_detection_is_one_bounded_call_per_claim_not_a_sweep(self, loop):
        """BAR-320's cost contract, asserted rather than described."""
        reconciler = loop["reconciler"]
        written = len(loop["report"].extraction.claims)
        assert reconciler.model_calls <= written
        assert reconciler.largest_block <= 20

    def test_the_event_carries_the_run_instant_not_the_authoring_instant(self, loop):
        """Transaction time on the event; valid time in the payload.

        ``contradiction.detected`` used to be stamped with
        ``Contradiction.detected_at`` — ``max(claim.observed_at)``, the instant
        the later source *document* was authored. The corpus is dated 2016 to
        2026-05, so every such event sorted decades before every nightly
        heartbeat, and ``reconcile/job.py``'s differential — which rebuilds last
        night's ledger by folding the log prefix at the previous heartbeat —
        would have swept all of them into every baseline. The result is the worst
        available failure: a differential that is not ``None`` and is always
        empty, on the one surface BAR-323 exists to produce evidence on.

        ``job.py`` was fixed for this; this asserts the CLI's on-write writer
        agrees, so the two writers of this event type cannot drift apart on which
        clock they use.
        """
        reconciler = loop["reconciler"]
        assert reconciler.contradictions_found >= 1

        newest_claim = max(c.observed_at for c in loop["state"].claims.values())
        detected = [
            e
            for e in loop["events"]
            if e.event_type is EventType.CONTRADICTION_DETECTED
        ]
        assert detected

        for event in detected:
            assert event.occurred_at == reconciler.run_instant
            assert event.occurred_at > newest_claim, (
                "the contradiction event sorts before the claims that caused it; "
                "it is carrying a document-authoring instant, not a run instant"
            )
            # Valid time is preserved where it belongs, so ledger recency ranking
            # is unaffected by where transaction time is stamped.
            assert event.payload["contradiction"]["detected_at"] <= newest_claim


class TestTheAgendaIsDerivedNotAuthored:
    def test_an_agenda_item_comes_out_of_the_ledger(self, loop):
        agenda = loop["agenda"]
        assert agenda.items, "the ledger had disagreements and produced no questions"

        item = agenda.items[0]
        assert item.question.strip()
        assert item.contradiction_id in loop["state"].contradictions
        assert item.cited_claim_ids

    def test_the_ledger_and_the_agenda_agree_about_what_is_open(self, loop):
        summary = loop["ledger"].summary(Audience.OWNER)
        assert summary["open_total"] == loop["agenda"].ledger_open_total

    def test_nothing_in_the_loop_promoted_a_claim(self, loop):
        """Ingest and reconcile ran end to end and committed nothing.

        The behavioural half of the promotion boundary. ``test_approval.py``
        asserts it structurally over the tree; this asserts it over a real run.
        """
        types = {e.event_type for e in loop["store"].read_all()}
        assert EventType.CLAIM_COMMITTED not in types
        assert EventType.CLAIM_VISIBILITY_SET not in types
        assert types <= {
            EventType.CLAIM_ASSERTED,
            EventType.CONTRADICTION_DETECTED,
            EventType.ENTITY_ALIAS_LINKED,
        }


# ------------------------------------------------------------ the guardrail


def _fingerprint() -> dict[str, object]:
    return {
        str(path): (path.stat().st_mtime_ns, path.stat().st_size)
        if path.is_file()
        else sorted(p.name for p in path.iterdir())
        if path.is_dir()
        else None
        for path in PROTECTED
    }


def test_this_test_writes_nothing_outside_its_tmp_path(tmp_path, client):
    """The honesty guardrail, mechanical.

    A fake-driven run must never leave a trace in the artifacts that carry
    measured claims. If this fails, something in the loop is writing to a
    repository path and a published number is one refactor away from being
    derived from scripted output.
    """
    before = _fingerprint()

    store = JsonlEventStore(tmp_path / "events.jsonl")
    pipeline = IngestionPipeline(
        client=client,
        store=store,
        on_claim=OnWriteReconciler(client=client, store=store),
        offline=True,
        agent_extraction=False,
    )
    pipeline.run(
        [
            SourceSpec(path=path, source_id=source_id, observed_at=observed_at)
            for source_id, path, observed_at in SOURCES
        ]
    )

    assert _fingerprint() == before
    assert store.path.is_relative_to(tmp_path)
