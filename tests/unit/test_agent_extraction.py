"""The ADK extractor on a real execution path.

``tests/unit/test_agents.py`` asserts that the agents *are* ADK agents. This
file asserts the thing that was missing for a whole session: that one of them
actually runs, over a real chunk, through the real validation gates, and that
the bounds the module advertises are the framework's and not the docstring's.

Four properties, in the order they matter.

**It extracts.** The agent reads a chunk, calls ``propose_claim``, and a claim
comes out carrying the anchor and quote it cited — the same claim the direct
path would have produced, because both call :func:`build_claim` and there is
only one of those.

**A rejection reaches the model.** The whole argument for paying for a
tool-calling loop instead of one JSON blob is that the model finds out its
anchor was bad while it can still do something about it. So the test asserts the
refusal appears in the *next request* the model receives, not merely in a
rejection list nobody reads until the run ends.

**The turn ceiling is real.** A model that keeps calling a rejected tool forever
is stopped by ADK at ``MAX_AGENT_TURNS``, and the cutoff is reported as a named
rejection rather than swallowed. This is the test that makes the constant a
safety property rather than a claim about one.

**The timeout is real.** Same, for wall-clock.

No test here reaches Vertex. The model is scripted at the framework's seam by
``tests/adk_testkit.py``; nothing it returns is a recording, and nothing
measured here is a performance figure.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from baraza.agents import ADK_AVAILABLE, AgentRole, BarazaAgents, ToolResult
from baraza.ingest.chunking import chunk_source
from baraza.ingest.readers import read_source
from baraza.ingest.sources import SourceRegistry
from baraza.schema.claim import Tier
from baraza.schema.visibility import Audience, Visibility

pytestmark = pytest.mark.skipif(not ADK_AVAILABLE, reason="google-adk not installed")

if ADK_AVAILABLE:
    from adk_testkit import ScriptedAdkModel, function_call, say
    from baraza.ingest.extract import AgentClaimExtractor, build_extractor

NOTES = """\
# Handover notes

The treasurer may sign for amounts up to five hundred dollars.

Anything over two hundred and fifty goes to the chair first.
"""

FIVE_HUNDRED = "The treasurer may sign for amounts up to five hundred dollars."


@pytest.fixture
def chunk_and_registry(tmp_path):
    """One real source, read by the real reader, chunked by the real chunker."""
    path = tmp_path / "handover-notes.md"
    path.write_text(NOTES, encoding="utf-8")
    source = read_source(
        path, source_id="src:handover-notes", observed_at="2026-04-01T00:00:00Z"
    )
    registry = SourceRegistry()
    registry.register(source)
    chunk = next(iter(chunk_source(source)))
    return chunk, registry


def _propose(anchor: str, quote: str, **overrides):
    payload = {
        "subject": "treasurer",
        "predicate": "signs up to",
        "predicate_hint": "signing authority",
        "object": "500",
        "quote": quote,
        "anchor": anchor,
    }
    payload.update(overrides)
    return function_call("propose_claim", **payload)


# ------------------------------------------------------------------ it works


class TestTheAgentExtracts:
    def test_a_claim_comes_out_of_the_loop(self, chunk_and_registry):
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [
                function_call("read_chunk"),
                _propose("L3-L3", FIVE_HUNDRED),
                say("That is every durable fact in the excerpt."),
            ]
        )

        result = AgentClaimExtractor(registry, model=model).extract_chunk(chunk)

        assert len(result.claims) == 1, result.rejected
        claim = result.claims[0]
        assert claim.anchor.locator == "L3-L3"
        assert claim.anchor.source_id == "src:handover-notes"
        assert claim.quote_for(Audience.OWNER) == FIVE_HUNDRED
        assert result.raw_returned == 1
        assert result.rejected == []
        assert result.chunks_processed == 1

    def test_the_agent_cannot_produce_anything_but_a_pending_private_claim(
        self, chunk_and_registry
    ):
        """The extractor's half of the promotion boundary, on the agent path."""
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [_propose("L3-L3", FIVE_HUNDRED), say("done")]
        )

        result = AgentClaimExtractor(registry, model=model).extract_chunk(chunk)

        assert result.claims[0].tier is Tier.PENDING
        assert result.claims[0].visibility is Visibility.PRIVATE

    def test_read_chunk_hands_over_the_locator_tagged_excerpt(
        self, chunk_and_registry
    ):
        """The anchor set the model may choose from is closed, and this is it."""
        chunk, registry = chunk_and_registry
        extractor = AgentClaimExtractor(registry, model=ScriptedAdkModel([say("hi")]))
        extractor._context = None

        assert extractor.read_chunk().ok is False  # nothing under extraction

        model = ScriptedAdkModel([function_call("read_chunk"), say("done")])
        extractor = AgentClaimExtractor(registry, model=model)
        extractor.extract_chunk(chunk)

        shown = "\n".join(model.prompts)
        assert "L3-L3" in shown
        assert FIVE_HUNDRED in shown

    def test_the_fleet_holds_exactly_the_two_published_tools(
        self, chunk_and_registry
    ):
        _, registry = chunk_and_registry
        extractor = AgentClaimExtractor(registry, model=ScriptedAdkModel([say("hi")]))

        matrix = extractor.fleet.tool_matrix()
        assert matrix[AgentRole.EXTRACTOR] == ["propose_claim", "read_chunk"]
        assert matrix[AgentRole.APPROVER] == []


# ------------------------------------------------------- refusals, not raises


class TestRejectionsReachTheModel:
    def test_a_hallucinated_anchor_comes_back_as_a_structured_refusal(
        self, chunk_and_registry
    ):
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [
                _propose("p.9 ¶1", FIVE_HUNDRED),  # not a locator in this chunk
                _propose("L3-L3", FIVE_HUNDRED),
                say("done"),
            ]
        )

        result = AgentClaimExtractor(registry, model=model).extract_chunk(chunk)

        # The bad one was dropped with a named reason; the good one survived.
        assert len(result.claims) == 1
        assert result.raw_returned == 2
        assert result.rejection_summary() == {"anchor-not-in-chunk": 1}

        # And the model was told, in the turn after the attempt. This is the
        # entire reason the agent path exists; if the refusal never reaches the
        # model, the loop is an expensive way to issue one call.
        refusals = [r for r in model.tool_results() if r.get("ok") is False]
        assert refusals, "the model was never shown the rejection"
        assert "anchor-not-in-chunk" in refusals[0]["reason"]

    def test_a_paraphrased_quote_is_refused_by_the_grounding_gate(
        self, chunk_and_registry
    ):
        """Gate 2, reached through the tool: the anchor is real, the quote is not."""
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [
                _propose("L3-L3", "The treasurer can spend up to $500 at will."),
                say("done"),
            ]
        )

        result = AgentClaimExtractor(registry, model=model).extract_chunk(chunk)

        assert result.claims == []
        assert result.rejection_summary() == {"quote-not-grounded": 1}

    def test_a_tool_that_raises_is_still_a_refusal(self, chunk_and_registry):
        """The guard, exercised where it matters rather than on a stub."""
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [function_call("propose_claim", anchor="L3-L3"), say("done")]
        )

        # Missing required arguments: ADK will reject or the tool will raise.
        # Either way the run completes and the pipeline survives.
        result = AgentClaimExtractor(registry, model=model).extract_chunk(chunk)
        assert result.claims == []


# ------------------------------------------------------------- the two bounds


class TestTheBoundsAreEnforced:
    def test_a_looping_agent_stops_at_the_turn_ceiling(self, chunk_and_registry):
        """The failure the ceiling exists for: a model that never gives up.

        ``repeat_last`` makes the script infinite on purpose. If the ceiling
        were not enforced this test would not fail — it would hang, which is
        precisely what it costs in production.
        """
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [_propose("p.9 ¶1", FIVE_HUNDRED)], repeat_last=True
        )

        result = AgentClaimExtractor(
            registry, model=model, max_turns=4
        ).extract_chunk(chunk)

        assert model.calls <= 4, "ADK let the agent past its ceiling"
        assert "agent-turn-ceiling" in result.rejection_summary()
        assert result.claims == []

    def test_the_ceiling_defaults_to_the_published_constant(self, chunk_and_registry):
        from baraza.agents import MAX_AGENT_TURNS, agent_run_config

        assert agent_run_config().max_llm_calls == MAX_AGENT_TURNS

    def test_a_hanging_model_is_cut_off_and_the_cutoff_is_reported(
        self, chunk_and_registry
    ):
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel([say("...")], delay_seconds=5.0)

        result = AgentClaimExtractor(
            registry, model=model, timeout_seconds=0.05
        ).extract_chunk(chunk)

        assert "agent-timeout" in result.rejection_summary()
        assert result.claims == []

    def test_a_cutoff_does_not_discard_the_claims_already_proposed(
        self, chunk_and_registry
    ):
        """A partial chunk is worth more than nothing, and is labelled."""
        chunk, registry = chunk_and_registry
        model = ScriptedAdkModel(
            [_propose("L3-L3", FIVE_HUNDRED), _propose("p.9 ¶1", FIVE_HUNDRED)],
            repeat_last=True,
        )

        result = AgentClaimExtractor(
            registry, model=model, max_turns=5
        ).extract_chunk(chunk)

        assert len(result.claims) == 1
        assert "agent-turn-ceiling" in result.rejection_summary()


# -------------------------------------------------- isolation, at construction


class TestPromotionIsolationAtConstruction:
    def test_building_the_agent_extractor_runs_the_check(self, chunk_and_registry):
        """Not a mock: constructing the real extractor must run the real check."""
        _, registry = chunk_and_registry
        extractor = AgentClaimExtractor(registry, model=ScriptedAdkModel([say("x")]))
        extractor.fleet.assert_promotion_isolated()  # must not raise

    def test_a_renamed_promotion_tool_is_caught_by_capability(self, tmp_path):
        """The check the name-set test cannot make.

        A tool called ``note_outcome`` passes any list of forbidden names. What
        gives it away is where it lives: beside the code that writes the
        promotion event. The token is assembled from fragments for the same
        reason ``tests/unit/test_compliance_lints.py`` assembles its probes —
        so this file does not itself become a place the event type is named.
        """
        module_path = tmp_path / "promotion_adjacent_tools.py"
        module_path.write_text(
            "from baraza.agents import ToolResult\n"
            "from baraza.schema.event import EventType\n"
            "\n"
            "PROMOTION = EventType." + "CLAIM_" + "COMMITTED\n"
            "\n"
            "def note_outcome(claim_id: str) -> ToolResult:\n"
            '    """An innocuous name for a tool that sits next to the writer."""\n'
            "    return ToolResult(ok=True)\n",
            encoding="utf-8",
        )
        sys.path.insert(0, str(tmp_path))
        try:
            module = importlib.import_module("promotion_adjacent_tools")
            leaky = BarazaAgents(extractor=build_extractor([module.note_outcome]))
            with pytest.raises(RuntimeError, match="promotion event type"):
                leaky.assert_promotion_isolated()
        finally:
            sys.modules.pop("promotion_adjacent_tools", None)
            sys.path.remove(str(tmp_path))

    def test_an_unauditable_tool_is_refused_rather_than_waved_through(self):
        """Fail closed. A tool whose source cannot be found is not proven safe."""

        def unauditable(x: str) -> ToolResult:
            """A tool with no resolvable source file."""
            return ToolResult(ok=True)

        unauditable.__code__ = compile(
            "def unauditable(x):\n    return None\n", "<not-a-file>", "exec"
        ).co_consts[0]

        fleet = BarazaAgents(extractor=build_extractor([unauditable]))
        with pytest.raises(RuntimeError, match="cannot be located"):
            fleet.assert_promotion_isolated()


def test_the_gates_are_shared_between_the_two_paths():
    """One implementation of "is this claim citable", imported by both."""
    from baraza.ingest import extract as module

    source = Path(module.__file__).read_text(encoding="utf-8")
    assert source.count("def build_claim(") == 1
    assert "return build_claim(" in source  # the direct path delegates
    assert "build_claim(\n" in source or "build_claim(" in source
