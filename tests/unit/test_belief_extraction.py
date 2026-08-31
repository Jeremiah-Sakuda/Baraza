"""WS3(a) — belief extraction targets judgment shape, not preference fluff.

The DECISION doc names the failure mode this file exists to prevent: if the
committed dossier reads "prefers concise", the entry dies. So these tests
assert the shape of what gets *through*, not merely that something does:

* **Judgment-shaped in, claim out.** A rule with a condition becomes a claim on
  the user entity, quote mandatory, anchored to the turn, pending and private.
* **Style fluff in, nothing out.** The model is instructed to skip bare taste,
  and when it disobeys — returning an unconditional tone rule — the gate drops
  it mechanically, with a named reason.
* **Fabricated quote in, dropped.** A quote that does not appear in the turn
  (whitespace-normalized) is a fabricated citation, and it is dropped with a
  named reason rather than repaired — the same three-gate discipline the corpus
  extractor runs.

The model is a scripted fake throughout: what a real model would return is
exactly the open question the DECISION doc calls the honest gap, and no test
here pretends to answer it. These tests pin down what the *gates* do with
whatever comes back.
"""

from __future__ import annotations

import json

from baraza.ingest.extract import (
    BELIEF_SCHEMA_NAME,
    BELIEF_TAXONOMY,
    USER_ENTITY_ID,
    BeliefExtractor,
    extract_beliefs,
)
from baraza.schema.claim import Provenance, Tier
from baraza.schema.temporal import to_epoch_millis
from baraza.schema.visibility import Audience, Visibility
from baraza_testkit import FakeLLMClient

TURN = (
    "Draft looks close. Two things before you continue: cite the source before "
    "the number, unless the recipient is internal. And never pad estimates — "
    "if a number is unmeasured, write that it is unmeasured."
)

CITE_QUOTE = (
    "cite the source before the number, unless the recipient is internal"
)


def beliefs(*entries: dict) -> str:
    return json.dumps({"beliefs": list(entries)})


def cite_belief(**overrides) -> dict:
    entry = {
        "rule": "Cite the source before the number.",
        "condition": "unless the recipient is internal",
        "predicate_hint": "citation policy",
        "quote": CITE_QUOTE,
    }
    entry.update(overrides)
    return entry


def extract(response: str, turn: str = TURN, **kwargs):
    client = FakeLLMClient(responses={BELIEF_SCHEMA_NAME: response})
    extractor = BeliefExtractor(client)
    result = extractor.extract_turn(
        turn,
        session_id="ses-partner-1",
        turn_id="t-3",
        observed_at="2026-08-30T12:00:00Z",
        **kwargs,
    )
    return result, client


# ------------------------------------------------- judgment-shaped in, claim out


class TestJudgmentShapedBeliefsBecomeClaims:
    def test_a_conditional_rule_becomes_a_claim(self):
        result, _ = extract(beliefs(cite_belief()))

        assert len(result.claims) == 1, result.rejected
        assert result.rejected == []
        claim = result.claims[0]
        assert claim.subject_id == USER_ENTITY_ID
        assert claim.predicate == "Cite the source before the number."
        assert claim.predicate_hint == "citation policy"
        assert claim.quote_for(Audience.OWNER) == CITE_QUOTE

    def test_the_anchor_points_at_the_turn(self):
        result, _ = extract(beliefs(cite_belief()))

        claim = result.claims[0]
        assert claim.anchor.source_id == "interview:ses-partner-1"
        assert claim.anchor.locator == "turn:t-3"
        assert claim.anchor.key() == "interview:ses-partner-1#turn:t-3"

    def test_the_claim_is_pending_private_interview_provenance(self):
        """The extractor cannot promote and cannot widen visibility.

        Only the approval path writes ``committed``, and only an approver
        chooses visibility — the belief path inherits both properties from
        the corpus path, and this pins them.
        """
        result, _ = extract(beliefs(cite_belief()))

        claim = result.claims[0]
        assert claim.tier is Tier.PENDING
        assert claim.visibility is Visibility.PRIVATE
        assert claim.provenance is Provenance.INTERVIEW

    def test_the_condition_travels_with_the_claim(self):
        """The object carries the full judgment, so the contradiction
        adjudicator sees the scope, not just the verb."""
        result, _ = extract(beliefs(cite_belief()))

        claim = result.claims[0]
        assert claim.extra["condition"] == "unless the recipient is internal"
        assert "unless the recipient is internal" in (claim.object_literal or "")
        assert claim.extra["turn_id"] == "t-3"
        assert claim.session_id == "ses-partner-1"

    def test_observed_at_is_epoch_normalized(self):
        result, _ = extract(beliefs(cite_belief()))

        expected = to_epoch_millis("2026-08-30T12:00:00Z", field="test")
        assert result.claims[0].observed_at == expected

    def test_a_reflowed_quote_still_grounds(self):
        """Whitespace is normalized before comparison — extraction reflows
        text — but nothing else about the quote is forgiven."""
        reflowed = cite_belief(
            quote="cite the source   before the\nnumber, unless the recipient is internal"
        )
        result, _ = extract(beliefs(reflowed))

        assert len(result.claims) == 1, result.rejected


# ----------------------------------------------------- style fluff in, nothing out


class TestStyleFluffProducesNothing:
    def test_a_turn_of_taste_yields_no_claims(self):
        """The instructed path: the model returns an empty list for a turn
        that contains only style, and an empty list is a valid answer."""
        result, _ = extract(
            beliefs(), turn="Looks good, I like it concise and friendly."
        )

        assert result.claims == []
        assert result.rejected == []
        assert result.raw_returned == 0

    def test_an_unconditional_tone_rule_is_gated_out(self):
        """The mechanical backstop for when the model disobeys: an
        unconditional tone rule is "prefers concise" wearing rule clothing,
        and the gate names it rather than committing it."""
        fluff = {
            "rule": "Keep responses concise.",
            "condition": None,
            "predicate_hint": "tone policy",
            "quote": "cite the source before the number",
        }
        result, _ = extract(beliefs(fluff))

        assert result.claims == []
        assert len(result.rejected) == 1
        reason, _raw = result.rejected[0]
        assert reason.startswith("style-without-condition")

    def test_a_conditional_tone_rule_survives(self):
        """Tone with a scope is a judgment, and it is exactly the kind of
        belief the taxonomy keeps: the condition is what separates a way of
        thinking from a tone slider."""
        conditional = {
            "rule": "Use a formal register.",
            "condition": "when the recipient is internal",
            "predicate_hint": "tone policy",
            "quote": "unless the recipient is internal",
        }
        result, _ = extract(beliefs(conditional))

        assert len(result.claims) == 1, result.rejected
        assert result.claims[0].predicate_hint == "tone policy"


# --------------------------------------------------- fabricated citations dropped


class TestFabricatedQuotesAreDropped:
    def test_a_quote_not_in_the_turn_is_dropped_with_a_named_reason(self):
        fabricated = cite_belief(
            quote="always attach the quarterly spreadsheet first"
        )
        result, _ = extract(beliefs(fabricated))

        assert result.claims == []
        assert len(result.rejected) == 1
        reason, raw = result.rejected[0]
        assert reason.startswith("quote-not-in-turn")
        assert raw["quote"] == "always attach the quarterly spreadsheet first"

    def test_an_empty_quote_is_dropped(self):
        result, _ = extract(beliefs(cite_belief(quote="")))

        assert result.claims == []
        assert result.rejected[0][0].startswith("quote-not-in-turn")

    def test_one_bad_belief_does_not_sink_the_good_one(self):
        """Gates drop per candidate, not per turn — same as the corpus path."""
        result, _ = extract(
            beliefs(cite_belief(), cite_belief(quote="not in the turn at all"))
        )

        assert len(result.claims) == 1
        assert len(result.rejected) == 1
        assert result.raw_returned == 2


# ----------------------------------------------------------- the other gates


class TestTheRemainingGates:
    def test_a_hint_outside_the_taxonomy_is_dropped(self):
        """The hint is the blocking key for contradiction detection; an
        invented category would scatter related beliefs across blocks that
        never meet."""
        result, _ = extract(beliefs(cite_belief(predicate_hint="vibe policy")))

        assert result.claims == []
        assert result.rejected[0][0].startswith("hint-not-in-taxonomy")

    def test_a_belief_with_no_rule_is_dropped(self):
        result, _ = extract(beliefs(cite_belief(rule="")))

        assert result.claims == []
        assert result.rejected[0][0].startswith("rule-missing")

    def test_an_unparseable_response_is_a_named_rejection(self):
        result, _ = extract("this is not json")

        assert result.claims == []
        assert result.rejected[0][0] == "unparseable-response"

    def test_an_empty_turn_makes_no_model_call(self):
        client = FakeLLMClient(responses={BELIEF_SCHEMA_NAME: beliefs()})
        result = BeliefExtractor(client).extract_turn(
            "   ", session_id="ses-1", turn_id="t-1", observed_at=0
        )

        assert result.claims == []
        assert client.calls == []


# ------------------------------------------------------------------ the prompt


class TestThePromptTargetsJudgmentShape:
    def test_the_call_shape(self):
        _, client = extract(beliefs(cite_belief()))

        calls = client.calls_for(BELIEF_SCHEMA_NAME)
        assert len(calls) == 1
        call = calls[0]
        # The reasoning role, deliberately: judgment shape is a
        # reading-comprehension problem, and the model id itself resolves in
        # schema/models.py — never here.
        assert call.role == "reasoning"
        assert call.temperature == 0.0

    def test_the_prompt_carries_the_turn_and_the_closed_taxonomy(self):
        _, client = extract(beliefs(cite_belief()))

        call = client.calls_for(BELIEF_SCHEMA_NAME)[0]
        assert TURN in call.prompt
        for hint in BELIEF_TAXONOMY:
            assert hint in call.prompt

    def test_the_system_prompt_instructs_the_shape(self):
        """The load-bearing instructions: verbatim quotes, skip bare style,
        never invent a condition, judgment shape by name."""
        _, client = extract(beliefs(cite_belief()))

        system = client.calls_for(BELIEF_SCHEMA_NAME)[0].system
        assert "VERBATIM" in system
        assert "SKIP" in system
        assert "JUDGMENT SHAPE" in system
        assert "never invent" in system.lower()
        for word in ("condition", "threshold", "exception", "scope"):
            assert word in system


# ------------------------------------------------------------- the wrapper


class TestTheConvenienceWrapper:
    def test_extract_beliefs_returns_only_the_accepted_claims(self):
        client = FakeLLMClient(
            responses={
                BELIEF_SCHEMA_NAME: beliefs(
                    cite_belief(), cite_belief(quote="fabricated entirely")
                )
            }
        )
        claims = extract_beliefs(
            TURN, "ses-partner-1", "t-3", client, observed_at=1_756_512_000_000
        )

        assert len(claims) == 1
        assert claims[0].subject_id == USER_ENTITY_ID
