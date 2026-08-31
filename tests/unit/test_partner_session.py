"""WS4 — the session partner: beliefs captured, collisions surfaced, never absorbed.

The properties under test, in the order the DECISION doc values them:

* **Contradiction-on-the-user fires.** A user turn asserting a rule that
  collides with a committed belief produces a divergence card — both quotes,
  both anchors, "Which governs?" — through the real ``ContradictionDetector``
  over the belief pool, not through a scripted shortcut.
* **The old belief is never silently overwritten.** The colliding belief is
  blocked out of the pool; the prior one stays; nothing on this path resolves
  anything. Resolution belongs to the approval path, and the session only
  surfaces the collision.
* **The compiled doctrine governs the session.** The ``doctrine_system_prompt``
  string is injected ahead of every generate call's own framing — task-step
  work and clarifiers alike. It is a plain string on purpose, so this file
  runs whether or not the doctrine compiler exists yet.
* **The first-token streaming path is intact**, and it still measures the
  presentation path a person actually waits on.
* **Every turn is externalized before the next is solicited** — the session is
  rebuildable from its own events, which is the crash-survival property.
* **The replay harness drives the full loop offline** with canned user turns,
  and refuses to write a transcript over a swallowed model-layer failure.

The model is a scripted fake throughout; nothing here measures a model, and
nothing here claims to.
"""

from __future__ import annotations

import json

import pytest

import baraza.interview.interviewer as interviewer_module
import baraza.interview.replay as replay_module
from baraza.fold.store import JsonlEventStore
from baraza.ingest.extract import BELIEF_SCHEMA_NAME, USER_ENTITY_ID
from baraza.interview.interviewer import (
    FOLLOW_UP_BUDGET,
    PartnerSession,
    task_step_item,
)
from baraza.interview.replay import (
    TRANSCRIPT_SCHEMA,
    PartnerReplayHarness,
    PartnerScript,
    ReplayPreconditionError,
    load_script,
)
from baraza.interview.session_store import SessionStore
from baraza.reconcile.agenda import Agenda, AgendaItem
from baraza.schema.claim import Provenance, Tier
from baraza.schema.session import TurnKind, TurnRole
from baraza_testkit import FakeLLMClient, claim

DOCTRINE = (
    "OPERATING DOCTRINE (compiled from committed beliefs; every rule cites "
    "the claim that put it there):\n"
    "- Never pad estimates. [clm_prior]\n"
)

PAD_TURN = "Let's pad the estimates to be safe — add a buffer everywhere."
PAD_QUOTE = "pad the estimates to be safe"

CITE_TURN = (
    "One more rule: cite the source before the number, unless the recipient "
    "is internal."
)
CITE_QUOTE = "cite the source before the number, unless the recipient is internal"

WORK_TEXT = "Here is a first cut of the overview section. Ready for your review?"


def prior_belief():
    """The committed belief the pool opens with: never pad estimates."""
    return claim(
        subject=USER_ENTITY_ID,
        predicate="Never pad estimates.",
        hint="estimation policy",
        quote="never pad estimates",
        object_literal="Never pad estimates.",
        tier=Tier.COMMITTED,
        provenance=Provenance.INTERVIEW,
        source_id="interview:ses-prior",
        locator="turn:t-9",
        observed_at="2026-08-25T09:00:00Z",
    )


def belief_response(prompt: str) -> str:
    """Scripted extraction: judgment-shaped turns yield beliefs, others none."""
    if PAD_QUOTE in prompt:
        return json.dumps(
            {
                "beliefs": [
                    {
                        "rule": "Pad the estimates.",
                        "condition": "to be safe",
                        "predicate_hint": "estimation policy",
                        "quote": PAD_QUOTE,
                    }
                ]
            }
        )
    if CITE_QUOTE in prompt:
        return json.dumps(
            {
                "beliefs": [
                    {
                        "rule": "Cite the source before the number.",
                        "condition": "unless the recipient is internal",
                        "predicate_hint": "citation policy",
                        "quote": CITE_QUOTE,
                    }
                ]
            }
        )
    return json.dumps({"beliefs": []})


def make_client(prior_id: str, *, follow_up: str = '{"question": "SETTLED"}'):
    """One scripted client for the whole loop, keyed by schema name."""

    def adjudicate(prompt: str) -> str:
        # The real detector built the block and the prompt; the fake only
        # plays the adjudicator's part.
        if PAD_QUOTE in prompt:
            return json.dumps(
                {
                    "contradictions": [
                        {
                            "claim_id": prior_id,
                            "confidence": 0.9,
                            "rationale": (
                                "Padding estimates and never padding them "
                                "cannot both govern the same work."
                            ),
                        }
                    ]
                }
            )
        return json.dumps({"contradictions": []})

    return FakeLLMClient(
        responses={
            BELIEF_SCHEMA_NAME: belief_response,
            "contradictions.v1": adjudicate,
            "follow_up.v1": follow_up,
            "": WORK_TEXT,
        }
    )


def make_agenda() -> Agenda:
    """One open contradiction on the user's beliefs, then one task step."""
    contradiction_item = AgendaItem(
        item_id="ag-01",
        contradiction_id="con_estimates",
        subject_id=USER_ENTITY_ID,
        predicate_hint="estimation policy",
        question=(
            "Your beliefs disagree about padding estimates. What should govern?"
        ),
        why_it_matters="An estimate rule changes every number the agent writes.",
        score=1.0,
        stakes_label="high",
        fully_readable=True,
        cited_claim_ids=[],
        source_ids=[],
    )
    return Agenda(
        items=[
            contradiction_item,
            task_step_item(
                index=1,
                question="Draft the submission overview section.",
                why_it_matters="The overview anchors the rest of the document.",
            ),
        ]
    )


def make_partner(tmp_path, client, *, agenda=None, doctrine=DOCTRINE):
    store = JsonlEventStore(tmp_path / "events.jsonl")
    partner = PartnerSession(
        client=client,
        agenda=agenda or make_agenda(),
        session_store=SessionStore(store),
        belief_pool=[prior_belief()],
        doctrine_system_prompt=doctrine,
    )
    return partner, store


# --------------------------------------------------------------- the peak beat


class TestContradictionOnTheUser:
    def test_a_colliding_turn_raises_a_divergence_card(self, tmp_path):
        prior = prior_belief()
        partner, _ = make_partner(tmp_path, make_client(prior.claim_id))
        partner.open()

        outcome = partner.observe_user_turn(PAD_TURN)

        assert len(outcome.cards) == 1
        card = outcome.cards[0]
        assert card.question == "Which governs?"
        assert card.prior_claim_id == prior.claim_id
        assert card.prior_quote == "never pad estimates"
        assert card.prior_anchor == "interview:ses-prior#turn:t-9"
        assert card.new_quote == PAD_QUOTE
        assert card.new_anchor.startswith("interview:")
        assert card.new_anchor.endswith("#turn:t-1")
        assert card.rationale

    def test_the_old_belief_is_not_silently_overwritten(self, tmp_path):
        """The blocked belief stays out of the pool; the prior one stays in.

        Resolution flows through the approval path — this session only
        surfaces the collision, and a pool that absorbed the newer statement
        would be the exact erasure the product exists to refuse.
        """
        prior = prior_belief()
        partner, _ = make_partner(tmp_path, make_client(prior.claim_id))
        partner.open()

        outcome = partner.observe_user_turn(PAD_TURN)

        assert len(outcome.blocked) == 1
        blocked = outcome.blocked[0]
        pool_ids = {c.claim_id for c in partner.belief_pool}
        assert blocked.claim_id not in pool_ids
        assert prior.claim_id in pool_ids
        assert blocked.claim_id in {c.claim_id for c in partner.blocked_beliefs}
        # Blocked, not promoted, not widened: still pending and private.
        assert blocked.tier is Tier.PENDING

    def test_the_card_preempts_everything_in_planning(self, tmp_path):
        prior = prior_belief()
        partner, _ = make_partner(tmp_path, make_client(prior.claim_id))
        partner.open()
        outcome = partner.observe_user_turn(PAD_TURN)

        plan = partner.plan_next(PAD_TURN)

        assert plan is not None
        assert plan.kind is TurnKind.DIVERGENCE
        assert plan.card == outcome.cards[0]
        assert plan.cited_claim_ids == [prior.claim_id]
        assert "never pad estimates" in plan.text
        assert PAD_QUOTE in plan.text
        assert "Which governs?" in plan.text

        turn = partner.speak(plan)
        assert turn.kind is TurnKind.DIVERGENCE
        assert turn.extra["divergence_card"]["prior_claim_id"] == prior.claim_id

    def test_a_non_colliding_belief_joins_the_pending_pool(self, tmp_path):
        prior = prior_belief()
        partner, _ = make_partner(tmp_path, make_client(prior.claim_id))
        partner.open()

        outcome = partner.observe_user_turn(CITE_TURN)

        assert outcome.cards == []
        assert len(outcome.accepted) == 1
        accepted = outcome.accepted[0]
        assert accepted.claim_id in {c.claim_id for c in partner.belief_pool}
        assert accepted.tier is Tier.PENDING
        assert accepted.subject_id == USER_ENTITY_ID

    def test_extraction_runs_after_every_user_turn(self, tmp_path):
        prior = prior_belief()
        client = make_client(prior.claim_id)
        partner, _ = make_partner(tmp_path, client)
        partner.open()

        partner.observe_user_turn("Sounds good, keep going.")
        partner.observe_user_turn(CITE_TURN)

        assert len(client.calls_for(BELIEF_SCHEMA_NAME)) == 2


# ----------------------------------------------------------- doctrine governs


class TestDoctrineInjection:
    def test_task_step_work_runs_under_the_doctrine(self, tmp_path):
        prior = prior_belief()
        client = make_client(prior.claim_id)
        agenda = Agenda(
            items=[task_step_item(index=1, question="Draft the overview.")]
        )
        partner, _ = make_partner(tmp_path, client, agenda=agenda)

        opening = partner.open()

        assert opening.text == WORK_TEXT
        work_calls = client.calls_for("")
        assert len(work_calls) == 1
        assert work_calls[0].system.startswith(DOCTRINE.rstrip())

    def test_follow_ups_run_under_the_doctrine(self, tmp_path):
        prior = prior_belief()
        client = make_client(
            prior.claim_id, follow_up='{"question": "What counts as routine?"}'
        )
        partner, _ = make_partner(tmp_path, client)
        partner.open()
        partner.observe_user_turn("Sounds good, keep going.")

        plan = partner.plan_next("Sounds good, keep going.")

        assert plan is not None
        assert plan.kind is TurnKind.FOLLOW_UP
        follow_calls = client.calls_for("follow_up.v1")
        assert len(follow_calls) == 1
        assert follow_calls[0].system.startswith(DOCTRINE.rstrip())

    def test_an_empty_doctrine_changes_nothing(self, tmp_path):
        prior = prior_belief()
        client = make_client(prior.claim_id)
        agenda = Agenda(
            items=[task_step_item(index=1, question="Draft the overview.")]
        )
        partner, _ = make_partner(tmp_path, client, agenda=agenda, doctrine="")

        partner.open()

        system = client.calls_for("")[0].system
        assert DOCTRINE not in system


# ------------------------------------------------------------------- the loop


class TestTheWorkingLoop:
    def test_the_budget_bounds_clarifiers_then_the_agenda_advances(self, tmp_path):
        prior = prior_belief()
        client = make_client(
            prior.claim_id, follow_up='{"question": "Can you say more?"}'
        )
        partner, _ = make_partner(tmp_path, client)
        partner.open()

        answer = "Sounds good, keep going."
        for expected_depth in range(1, FOLLOW_UP_BUDGET + 1):
            partner.observe_user_turn(answer)
            plan = partner.plan_next(answer)
            assert plan is not None and plan.kind is TurnKind.FOLLOW_UP
            assert plan.follow_up_depth == expected_depth
            partner.speak(plan)

        partner.observe_user_turn(answer)
        plan = partner.plan_next(answer)
        assert plan is not None
        assert plan.kind is TurnKind.AGENDA
        assert plan.agenda_item_id == "ts-01"
        assert plan.text == WORK_TEXT  # the task step is worked, not recited

        partner.speak(plan)
        partner.observe_user_turn(answer)
        # The budget applies anew on the next item: depth reset with the item.
        next_plan = partner.plan_next(answer)
        assert next_plan is not None
        assert next_plan.kind is TurnKind.FOLLOW_UP
        assert next_plan.follow_up_depth == 1

    def test_streaming_first_token_is_intact(self, tmp_path):
        prior = prior_belief()
        partner, _ = make_partner(tmp_path, make_client(prior.claim_id))

        chunks: list[str] = []
        turn = partner.open(emit=chunks.append)

        assert "".join(chunks) == turn.text
        assert turn.first_token_ms is not None
        assert turn.first_token_ms >= 0

    def test_turns_are_externalized_before_the_next_is_solicited(self, tmp_path):
        """The session rebuilds from its own events — the crash-survival
        property is inherited from the store, not reimplemented here."""
        prior = prior_belief()
        partner, store = make_partner(tmp_path, make_client(prior.claim_id))
        partner.open()
        partner.observe_user_turn(PAD_TURN)

        assert partner.session is not None
        rebuilt = SessionStore(store).load(partner.session.session_id)

        assert rebuilt is not None
        assert len(rebuilt.turns) == 2
        assert rebuilt.turns[0].role is TurnRole.AGENT
        assert rebuilt.turns[1].role is TurnRole.OFFICER
        assert rebuilt.turns[1].text == PAD_TURN

    def test_an_empty_agenda_is_refused_at_construction(self, tmp_path):
        store = JsonlEventStore(tmp_path / "events.jsonl")
        with pytest.raises(ValueError, match="agenda is empty"):
            PartnerSession(
                client=FakeLLMClient(default="{}"),
                agenda=Agenda(items=[]),
                session_store=SessionStore(store),
            )


# ------------------------------------------------------- the heuristic is gone


class TestTheOldHeuristicIsGone:
    def test_no_adaptation_state_in_the_live_path(self):
        assert not hasattr(interviewer_module, "AdaptationState")
        assert not hasattr(replay_module, "AdaptationState")

    def test_no_terse_threshold_either(self):
        assert not hasattr(interviewer_module, "TERSE_CHAR_THRESHOLD")


# ------------------------------------------------------------------ the replay


def write_script(tmp_path, turns) -> PartnerScript:
    path = tmp_path / "builder-session.json"
    path.write_text(
        json.dumps(
            {
                "script_id": "builder-session",
                "description": "The builder drafting the submission docs.",
                "typing": {
                    "chars_per_minute": 600,
                    "min_pause_ms": 0,
                    "max_pause_ms": 0,
                },
                "turns": [{"text": t} for t in turns],
            }
        ),
        encoding="utf-8",
    )
    return load_script(path)


class TestThePartnerReplay:
    def test_the_offline_loop_exercises_extraction_and_detection(self, tmp_path):
        prior = prior_belief()
        script = write_script(tmp_path, [PAD_TURN, CITE_TURN, "Looks done."])
        harness = PartnerReplayHarness(
            client=make_client(prior.claim_id),
            agenda=make_agenda(),
            session_store=SessionStore(JsonlEventStore(tmp_path / "events.jsonl")),
            script=script,
            belief_pool=[prior],
            doctrine_system_prompt=DOCTRINE,
            paced=False,
        )

        result = harness.run()

        assert result.cards_raised == 1
        assert result.beliefs_blocked == 1
        assert result.beliefs_accepted == 1
        assert result.stop_reason
        assert result.model_calls > 0
        assert result.llm_source == "fake"

        # The user-turn records carry the belief bookkeeping the web surface
        # and any scorer will read.
        user_records = [t for t in result.turns if t["role"] == "officer"]
        assert user_records[0]["beliefs"]["blocked"][0]["predicate_hint"] == (
            "estimation policy"
        )
        assert user_records[0]["cards"][0]["question"] == "Which governs?"

    def test_the_transcript_is_versioned_and_writable(self, tmp_path):
        prior = prior_belief()
        script = write_script(tmp_path, [PAD_TURN])
        harness = PartnerReplayHarness(
            client=make_client(prior.claim_id),
            agenda=make_agenda(),
            session_store=SessionStore(JsonlEventStore(tmp_path / "events.jsonl")),
            script=script,
            belief_pool=[prior],
            paced=False,
        )
        result = harness.run()

        out_dir = tmp_path / "transcripts"
        path = result.save(out_dir)

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["schema"] == TRANSCRIPT_SCHEMA
        assert payload["script"]["fixture_sha256"] == script.fixture_sha256
        assert payload["run"]["paced"] is False
        assert "Not a deployed measurement" in payload["run"]["timing_provenance"]

    def test_a_swallowed_model_failure_refuses_the_transcript(self, tmp_path):
        """``compose_follow_up`` swallows everything so a live session cannot
        hang; the harness must therefore refuse to publish a transcript over
        the swallowed failure rather than average around it."""
        prior = prior_belief()
        client = FakeLLMClient(
            responses={
                BELIEF_SCHEMA_NAME: belief_response,
                "contradictions.v1": json.dumps({"contradictions": []}),
                "": WORK_TEXT,
                # follow_up.v1 deliberately unscripted: the call raises, the
                # session swallows it, and the watcher must still see it.
            }
        )
        script = write_script(tmp_path, ["Sounds good, keep going."])
        harness = PartnerReplayHarness(
            client=client,
            agenda=make_agenda(),
            session_store=SessionStore(JsonlEventStore(tmp_path / "events.jsonl")),
            script=script,
            belief_pool=[prior],
            paced=False,
        )

        with pytest.raises(ReplayPreconditionError, match="swallowed"):
            harness.run()
