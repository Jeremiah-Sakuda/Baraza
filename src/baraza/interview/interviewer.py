"""The session partner — working sessions over a dossier of the user's beliefs.

The session is a working session, not an interrogation: the agent works a real
task step-by-step from the agenda, and the agenda's items are either open
contradictions on the user's own beliefs or steps of the task at hand. After
every user turn, two things happen without being asked for:

**Belief extraction.** The turn is mined for judgment-shaped operating rules —
conditions, thresholds, exceptions, scope — by
``baraza.ingest.extract.extract_beliefs``. Each extracted belief is a ``Claim``
about the user entity, quote mandatory, anchored to the turn that asserted it.

**Contradiction detection, aimed at the user.** Each new belief runs through
``reconcile.detect.ContradictionDetector`` against the pool of the user's
committed and pending beliefs — the same on-write, blocked detection the corpus
uses, retargeted at a pool whose every subject is the user entity. When two of
the user's own statements collide, the session surfaces a
:class:`DivergenceCard`: both quotes, both anchors, and the question "Which
governs?". The colliding belief is **blocked** — it does not enter the pool,
and nothing on this path resolves the collision. Resolution flows through the
approval path, because a partner that silently absorbs your latest
contradiction is not adapting to you; it is erasing you.

Two properties carry over from the interview engine unchanged:

* **First-token streaming.** A planned turn's text is decided before streaming
  begins, so ``stream_turn`` measures the interval a person actually waits
  before seeing a word — a presentation figure, never a model
  time-to-first-token, and never a deployed measurement.
* **The visibility boundary.** Every quote rendered into a turn routes through
  ``quote_for(audience)``; a claim the audience cannot read is never quoted at
  them, even to contradict them.

The compiled doctrine governs the session by injection: pass the compiled
policy text as ``doctrine_system_prompt`` and every generate call in the
session runs under it. The parameter is a plain string on purpose — this
module does not import the doctrine compiler, so the session works (and its
tests run) whether or not that module exists yet. Same doctrine, every rule
cited; the doctrine is the deterministic artifact, the model's compliance with
it is not, and nothing here claims otherwise.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from baraza.fold.graph import GraphState
from baraza.ingest.extract import (
    USER_ENTITY_ID,
    BeliefExtractionResult,
    BeliefExtractor,
)
from baraza.llm import LLMClient
from baraza.reconcile.agenda import Agenda, AgendaItem
from baraza.reconcile.detect import ContradictionDetector
from baraza.schema.claim import Anchor, Claim, Provenance, Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.event import Event, EventType
from baraza.schema.session import Session, Turn, TurnKind, TurnRole
from baraza.schema.temporal import EpochMillis, to_epoch_millis
from baraza.schema.visibility import Audience, Visibility, readable_by

__all__ = [
    "Interviewer",
    "PartnerSession",
    "PartnerTurnOutcome",
    "DivergenceCard",
    "DivergenceFinding",
    "TurnPlan",
    "task_step_item",
    "FOLLOW_UP_BUDGET",
    "MAX_FOLLOW_UP_DEPTH",
]

FOLLOW_UP_BUDGET = 2
"""Clarifiers per agenda item before the session moves on.

A fixed budget, deliberately: how hard the agent pushes on a point is a pacing
decision the transcript should make legible, not a hidden variable a reader has
to reconstruct. Callers that want a different pace pass a different number.
"""

MAX_FOLLOW_UP_DEPTH = 4
"""Ceiling regardless of the configured budget.

A person who has answered four clarifiers on one point has given what they
have. Pushing further trades goodwill for nothing, and an agent that cannot
stop asking is a worse failure than one that asks too little.
"""


@dataclass(frozen=True, slots=True)
class DivergenceFinding:
    """A statement held against the record. The product moment."""

    testimony: str
    conflicting_claim_id: str
    conflicting_quote: str
    conflicting_anchor: str
    rationale: str
    confidence: float

    def render(self) -> str:
        return (
            f"That differs from what the records say. "
            f"{self.conflicting_anchor} reads: “{self.conflicting_quote}”. "
            f"{self.rationale}"
        )


@dataclass(frozen=True, slots=True)
class DivergenceCard:
    """Two of the user's own statements, on screen, with the question.

    This is the data the web surface renders: both quotes, both anchors, and
    "Which governs?". The card never resolves anything — it exists to make the
    collision impossible to miss and the resolution impossible to skip. The
    blocked belief stays out of the pool until the approval path adjudicates.
    """

    contradiction_id: str
    predicate_hint: str
    new_claim_id: str
    new_quote: str
    new_anchor: str
    prior_claim_id: str
    prior_quote: str
    prior_anchor: str
    rationale: str
    confidence: float
    question: str = "Which governs?"

    def render(self) -> str:
        return (
            f"Earlier you told me: “{self.prior_quote}” ({self.prior_anchor}). "
            f"Just now: “{self.new_quote}” ({self.new_anchor}). "
            f"{self.question} I will not overwrite the earlier rule until you "
            "decide."
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contradiction_id": self.contradiction_id,
            "predicate_hint": self.predicate_hint,
            "new_claim_id": self.new_claim_id,
            "new_quote": self.new_quote,
            "new_anchor": self.new_anchor,
            "prior_claim_id": self.prior_claim_id,
            "prior_quote": self.prior_quote,
            "prior_anchor": self.prior_anchor,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "question": self.question,
        }


@dataclass(slots=True)
class TurnPlan:
    """What the agent intends to say next, and why."""

    kind: TurnKind
    text: str
    agenda_item_id: str | None = None
    contradiction_id: str | None = None
    cited_claim_ids: list[str] = field(default_factory=list)
    follow_up_depth: int = 0
    divergence: DivergenceFinding | None = None
    card: DivergenceCard | None = None


def task_step_item(
    *,
    index: int,
    question: str,
    why_it_matters: str = "",
    subject_id: str = USER_ENTITY_ID,
) -> AgendaItem:
    """An agenda item that is a task step rather than an open contradiction.

    The partner session's agenda interleaves both kinds; a task step carries an
    empty ``contradiction_id`` and no citations, which is how
    :meth:`PartnerSession.speak` knows to *work* the item — generate the next
    piece of the task under the doctrine — instead of asking a question the
    ledger wrote.
    """
    return AgendaItem(
        item_id=f"ts-{index:02d}",
        contradiction_id="",
        subject_id=subject_id,
        predicate_hint="",
        question=question,
        why_it_matters=why_it_matters,
        score=0.0,
        stakes_label="task",
        fully_readable=True,
        cited_claim_ids=[],
        source_ids=[],
    )


_FOLLOW_UP_SYSTEM = """\
You are working through a task with the person whose session this is. You have \
just received an answer that does not fully settle the current point.

Write ONE short clarifying question — under 25 words — that targets the \
specific gap. Requirements:

* Target what is MISSING, not what was said. If they gave a rule but not its \
scope, ask for the scope.
* Never repeat the original question in different words.
* Never ask two things at once.
* Be warm and brief. Their time is the budget this session spends.
* If the answer genuinely settles the point, return the single word: SETTLED

Return JSON only: {"question": "..."} or {"question": "SETTLED"}
"""

_DIVERGENCE_SYSTEM = """\
You compare a person's statement against the written record.

You will be given a statement and a set of claims extracted from records. \
Decide whether the statement CONTRADICTS any of them.

Be strict. Only report a contradiction when both cannot be true:

* The statement asserts a different value for the same thing over the same \
period → contradiction.
* The statement describes a different period, a later change, or a practice \
that differs from a policy without denying the policy → NOT a contradiction.
* The statement is vague, hedged, or says "I don't remember" → NOT a \
contradiction.
* The statement adds information the record lacks → NOT a contradiction.

Never treat a person as lying. A divergence between memory and record is \
information about both, and the most common cause is that the record is stale.

Return JSON only:
{"divergence": null}
or
{"divergence": {"claim_id": "...", "confidence": 0.0-1.0, \
"rationale": "one neutral sentence naming the specific difference"}}
"""

_TASK_STEP_SYSTEM = """\
You are working a task step-by-step with the person whose session this is. \
Produce the next concrete piece of work for the step you are given — a draft, \
a list, a decision to put to them — then ask ONE question inviting their \
review. Keep it under 120 words. Never invent facts; where a fact is missing, \
say so and ask for it.
"""


def _joined_system(doctrine: str, base: str) -> str:
    """Doctrine first, task framing second.

    The compiled doctrine is the session's operating policy; putting it ahead
    of the task framing is what "the doctrine governs the session" means at the
    call site. An empty doctrine changes nothing.
    """
    if not doctrine.strip():
        return base
    return f"{doctrine.rstrip()}\n\n{base}"


class Interviewer:
    """Plans one conversation's agent turns.

    The class holds no session state of its own — state lives in the session
    passed in and in the append-only log — so a resumed process constructs a
    fresh ``Interviewer`` and continues correctly.
    """

    def __init__(
        self,
        client: LLMClient,
        state: GraphState | None,
        *,
        audience: Audience = Audience.OWNER,
        doctrine_system_prompt: str = "",
    ):
        self.client = client
        self.state = state
        self.audience = audience
        self.doctrine_system_prompt = doctrine_system_prompt

    def _system(self, base: str) -> str:
        return _joined_system(self.doctrine_system_prompt, base)

    # --------------------------------------------------------------- planning

    def opening_turn(self, agenda: Agenda, session: Session) -> TurnPlan:
        item = agenda.items[0]
        return TurnPlan(
            kind=TurnKind.AGENDA,
            text=item.question,
            agenda_item_id=item.item_id,
            contradiction_id=item.contradiction_id or None,
            cited_claim_ids=list(item.cited_claim_ids),
            follow_up_depth=0,
        )

    def plan_next(
        self,
        *,
        agenda: Agenda,
        session: Session,
        last_answer: str,
        current_item: AgendaItem,
        current_depth: int,
        follow_up_budget: int = FOLLOW_UP_BUDGET,
    ) -> TurnPlan | None:
        """Decide the next agent turn: divergence, follow-up, or move on."""

        # 1. Divergence check runs first and always. It is the highest-value
        #    thing that can happen in a session, and a follow-up asked *before*
        #    noticing a contradiction wastes the moment.
        divergence = self.check_divergence(last_answer, current_item)
        if divergence is not None:
            return TurnPlan(
                kind=TurnKind.DIVERGENCE,
                text=divergence.render(),
                agenda_item_id=current_item.item_id,
                contradiction_id=current_item.contradiction_id or None,
                cited_claim_ids=[divergence.conflicting_claim_id],
                follow_up_depth=current_depth,
                divergence=divergence,
            )

        # 2. Follow up, if the budget allows and the answer left a gap.
        if current_depth < min(follow_up_budget, MAX_FOLLOW_UP_DEPTH):
            follow_up = self.compose_follow_up(current_item, last_answer)
            if follow_up is not None:
                return TurnPlan(
                    kind=TurnKind.FOLLOW_UP,
                    text=follow_up,
                    agenda_item_id=current_item.item_id,
                    contradiction_id=current_item.contradiction_id or None,
                    cited_claim_ids=list(current_item.cited_claim_ids),
                    follow_up_depth=current_depth + 1,
                )

        # 3. Move to the next agenda item.
        remaining = [
            item
            for item in agenda.items
            if item.item_id > current_item.item_id
        ]
        if not remaining:
            return None
        nxt = remaining[0]
        return TurnPlan(
            kind=TurnKind.AGENDA,
            text=nxt.question,
            agenda_item_id=nxt.item_id,
            contradiction_id=nxt.contradiction_id or None,
            cited_claim_ids=list(nxt.cited_claim_ids),
            follow_up_depth=0,
        )

    # -------------------------------------------------------------- follow-up

    def compose_follow_up(self, item: AgendaItem, answer: str) -> str | None:
        prompt = (
            f"Original question: {item.question}\n"
            f"Why it matters: {item.why_it_matters}\n"
            f"Their answer: {answer}\n"
        )
        try:
            response = self.client.generate(
                role="fast",
                prompt=prompt,
                system=self._system(_FOLLOW_UP_SYSTEM),
                schema_name="follow_up.v1",
                temperature=0.4,
                max_output_tokens=200,
            )
            question = str(response.json().get("question", "")).strip()
        except Exception:  # noqa: BLE001
            # A failed follow-up generation moves the session on rather than
            # stalling it. Losing one clarifier is cheap; hanging on a live
            # session with a person waiting is not.
            return None

        if not question or question.upper().startswith("SETTLED"):
            return None
        return question

    # ------------------------------------------------------------- divergence

    def check_divergence(
        self, testimony: str, item: AgendaItem
    ) -> DivergenceFinding | None:
        """Hold a statement against the record.

        Candidates are restricted to claims **readable by this audience**. The
        agent cannot quote a private claim at someone in order to contradict
        them — that would leak the claim's content through the divergence
        message, which is precisely the leak the boundary exists to prevent.
        """
        if self.state is None:
            # No record to hold the statement against. The partner session runs
            # this way on purpose: its collisions come from the belief pool via
            # ContradictionDetector, not from the corpus graph.
            return None
        if len(testimony.strip()) < 20:
            return None

        candidates: list[Claim] = []
        for claim_id in item.cited_claim_ids:
            claim = self.state.claims.get(claim_id)
            if claim is None or not claim.in_retrieval_pool:
                continue
            if not readable_by(claim, self.audience):
                continue
            candidates.append(claim)

        if not candidates:
            return None

        rendered = "\n".join(
            f"  - id: {c.claim_id}\n"
            f"    asserts: {c.object_for(self.audience)}\n"
            f'    quote:   "{c.quote_for(self.audience)}"\n'
            f"    source:  {c.anchor.key()}"
            for c in candidates
        )
        prompt = f"STATEMENT\n  {testimony.strip()}\n\nTHE RECORD\n{rendered}\n"

        try:
            response = self.client.generate(
                role="reasoning",
                prompt=prompt,
                system=self._system(_DIVERGENCE_SYSTEM),
                schema_name="divergence.v1",
                temperature=0.0,
            )
            payload = response.json()
        except Exception:  # noqa: BLE001
            return None

        finding = payload.get("divergence")
        if not finding:
            return None

        claim = self.state.claims.get(finding.get("claim_id", ""))
        if claim is None or not readable_by(claim, self.audience):
            # The model named a claim that is not readable here. Refusing is the
            # only safe response: rendering it would leak, and rendering a
            # different one would be a fabricated citation.
            return None

        quote = claim.quote_for(self.audience)
        if not quote:
            return None

        return DivergenceFinding(
            testimony=testimony.strip(),
            conflicting_claim_id=claim.claim_id,
            conflicting_quote=quote,
            conflicting_anchor=claim.anchor.key(),
            rationale=str(finding.get("rationale", "")).strip(),
            confidence=float(finding.get("confidence", 0.0)),
        )

    # ---------------------------------------------------------------- streaming

    def stream_turn(self, plan: TurnPlan) -> Iterator[tuple[str, int]]:
        """Yield ``(chunk, elapsed_ms)`` for a planned turn.

        A planned turn's text is already decided, so streaming it is a
        presentation choice rather than a generation one — which is exactly why
        the first-token measurement is honest: it measures the path a person
        actually waits on.
        """
        started = time.perf_counter()
        for chunk in re.findall(r"\S+\s*", plan.text):
            yield chunk, int((time.perf_counter() - started) * 1000)

    # ------------------------------------------------------------ claim minting

    def claim_from_answer(
        self,
        *,
        answer: str,
        item: AgendaItem,
        session: Session,
        turn: Turn,
        occurred_at: EpochMillis,
    ) -> Claim | None:
        """Turn an approved answer into a citable claim.

        The anchor points at the session turn itself — ``turn:t-14`` — which is
        a real, registered, resolvable location. A person's answers are a
        source like any other, and treating them as one is what lets a later
        session find a contradiction between two of their own statements.

        Tier is ``PENDING`` and visibility is ``PRIVATE``. Only the approval
        path promotes, and only an approver chooses visibility.
        """
        text = answer.strip()
        if len(text) < 8:
            return None

        return Claim.create(
            subject_id=item.subject_id,
            predicate=item.predicate_hint or "recalled",
            predicate_hint=item.predicate_hint,
            quote=text,
            anchor=Anchor(
                source_id=f"interview:{session.session_id}",
                locator=f"turn:{turn.turn_id}",
            ),
            observed_at=occurred_at,
            object_literal=text[:200],
            tier=Tier.PENDING,
            visibility=Visibility.PRIVATE,
            provenance=Provenance.INTERVIEW,
            author_id=session.persona_id,
            session_id=session.session_id,
            extra={
                "agenda_item_id": item.item_id,
                "contradiction_id": item.contradiction_id,
                "turn_id": turn.turn_id,
            },
        )


# ---------------------------------------------------------- partner session


@dataclass(slots=True)
class PartnerTurnOutcome:
    """Everything one user turn changed, including what it failed to change."""

    user_turn: Turn
    accepted: list[Claim] = field(default_factory=list)
    """New beliefs that entered the pending pool without colliding."""

    blocked: list[Claim] = field(default_factory=list)
    """New beliefs held out of the pool because they collide with a prior one.
    They stay blocked until the approval path adjudicates; this session only
    surfaces the collision."""

    cards: list[DivergenceCard] = field(default_factory=list)
    dropped: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    """Belief candidates rejected by the extraction gates, with named reasons.
    Surfaced so a failing extractor cannot impersonate a rule-free turn."""

    raw_returned: int = 0


class PartnerSession:
    """One working session: task steps, belief capture, collisions surfaced.

    The driving loop the caller (web surface, replay harness, terminal) runs:

    1. :meth:`open` — appends the session and speaks the first agenda item.
    2. :meth:`observe_user_turn` — externalizes the user's turn, extracts
       beliefs, runs contradiction detection against the belief pool, and
       returns what happened.
    3. :meth:`plan_next` then :meth:`speak` — a queued divergence card wins,
       then a clarifier within budget, then the next agenda item; ``None``
       means the agenda is exhausted.

    Every turn is externalized to the append-only log before the next is
    solicited, same as the interview engine — the property BAR-334 proves with
    a mid-stream kill is inherited, not reimplemented.
    """

    def __init__(
        self,
        *,
        client: LLMClient,
        agenda: Agenda,
        session_store: Any,
        belief_pool: Sequence[Claim] = (),
        detector: ContradictionDetector | None = None,
        extractor: BeliefExtractor | None = None,
        doctrine_system_prompt: str = "",
        audience: Audience = Audience.OWNER,
        user_id: str = USER_ENTITY_ID,
        user_label: str = "the-builder",
        follow_up_budget: int = FOLLOW_UP_BUDGET,
        aliases: dict[str, str] | None = None,
        clock: Callable[[], float] = time.time,
    ):
        if not agenda.items:
            raise ValueError(
                "the agenda is empty. A partner session with nothing to work "
                "on would open, extract nothing, and close — run the agenda "
                "generator first."
            )
        self.client = client
        self.agenda = agenda
        self.session_store = session_store
        self.doctrine_system_prompt = doctrine_system_prompt
        self.audience = audience
        self.user_id = user_id
        self.user_label = user_label
        self.follow_up_budget = follow_up_budget
        self.aliases = dict(aliases or {})
        self.clock = clock

        self.detector = detector or ContradictionDetector(client)
        self.extractor = extractor or BeliefExtractor(client)
        # The planner runs stateless over the belief loop: its corpus-graph
        # divergence check is off (state=None) because this session's
        # collisions come from the detector over the belief pool instead.
        self.interviewer = Interviewer(
            client,
            None,
            audience=audience,
            doctrine_system_prompt=doctrine_system_prompt,
        )

        # The pool detection runs against: the user's committed and pending
        # beliefs. Rejected claims are retracted and never re-enter; claims
        # about anything but the user entity are someone else's problem.
        self._pool: dict[str, Claim] = {
            c.claim_id: c
            for c in belief_pool
            if c.subject_id == user_id and c.in_retrieval_pool
        }
        self._blocked: dict[str, Claim] = {}
        self._cards: list[DivergenceCard] = []
        self._pending_cards: list[DivergenceCard] = []

        self._items_by_id = {item.item_id: item for item in agenda.items}
        # Positional order, not item-id order: the agenda interleaves
        # contradiction items (ag-NN) and task steps (ts-NN), and comparing
        # those ids as strings would push every task step to the end.
        self._item_order = {
            item.item_id: position for position, item in enumerate(agenda.items)
        }
        self._current_item: AgendaItem = agenda.items[0]
        self._depth = 0
        self._last_instant: EpochMillis | None = None
        self.session: Session | None = None

    # ------------------------------------------------------------------ views

    @property
    def belief_pool(self) -> list[Claim]:
        return list(self._pool.values())

    @property
    def blocked_beliefs(self) -> list[Claim]:
        return list(self._blocked.values())

    @property
    def divergence_cards(self) -> list[DivergenceCard]:
        return list(self._cards)

    @property
    def current_item(self) -> AgendaItem:
        return self._current_item

    # ------------------------------------------------------------------ clock

    def _now(self) -> EpochMillis:
        """Strictly increasing epoch millis.

        Two turns inside the same millisecond would give the session a
        non-total order under BAR-309's integer comparison. Nudging forward is
        honest at millisecond resolution and keeps the ordering a property of
        the data rather than of the reader.
        """
        instant = to_epoch_millis(self.clock(), field="partner.turn")
        if self._last_instant is not None and instant <= self._last_instant:
            instant = self._last_instant + 1
        self._last_instant = instant
        return instant

    # ------------------------------------------------------------------- open

    def open(
        self,
        *,
        opened_at: Any = None,
        emit: Callable[[str], None] | None = None,
    ) -> Turn:
        """Open the session and speak the first agenda item."""
        instant = (
            self._now()
            if opened_at is None
            else to_epoch_millis(opened_at, field="partner.opened_at")
        )
        self._last_instant = max(self._last_instant or instant, instant)
        self.session = self.session_store.open(
            persona_id=self.user_label, opened_at=instant
        )
        return self.speak(self._plan_for_item(self.agenda.items[0]), emit=emit)

    # ------------------------------------------------------------------ turns

    def speak(
        self,
        plan: TurnPlan,
        *,
        emit: Callable[[str], None] | None = None,
    ) -> Turn:
        """Deliver a planned turn: stream it, then externalize it.

        The turn is appended to the log before the caller can solicit an
        answer, which is the whole of the crash-survival property.
        """
        session = self._require_session()
        occurred_at = self._now()

        first_token_ms: int | None = None
        for chunk, elapsed_ms in self.interviewer.stream_turn(plan):
            if first_token_ms is None:
                first_token_ms = elapsed_ms
            if emit is not None:
                emit(chunk)

        turn = Turn.create(
            session_id=session.session_id,
            index=session.next_index,
            role=TurnRole.AGENT,
            kind=plan.kind,
            text=plan.text,
            occurred_at=occurred_at,
            agenda_item_id=plan.agenda_item_id,
            contradiction_id=plan.contradiction_id,
            cited_claim_ids=plan.cited_claim_ids,
            follow_up_depth=plan.follow_up_depth,
            first_token_ms=first_token_ms,
            extra={
                "divergence_card": None if plan.card is None else plan.card.to_dict(),
            },
        )
        session.turns.append(turn)
        self.session_store.append_turn(turn)

        if plan.agenda_item_id and plan.agenda_item_id != self._current_item.item_id:
            self._current_item = self._items_by_id[plan.agenda_item_id]
        self._depth = plan.follow_up_depth
        return turn

    def observe_user_turn(
        self, text: str, *, occurred_at: Any = None
    ) -> PartnerTurnOutcome:
        """One user turn: externalize, extract beliefs, detect collisions.

        The turn is appended before the extraction call runs, so a crash inside
        the model call loses at most the extraction — never the user's words.
        """
        session = self._require_session()
        instant = (
            self._now()
            if occurred_at is None
            else to_epoch_millis(occurred_at, field="partner.user_turn")
        )
        turn = Turn.create(
            session_id=session.session_id,
            index=session.next_index,
            # Schema role name predates the pivot; on this path it is the user.
            role=TurnRole.OFFICER,
            kind=TurnKind.ANSWER,
            text=text,
            occurred_at=instant,
            agenda_item_id=self._current_item.item_id,
            contradiction_id=self._current_item.contradiction_id or None,
            follow_up_depth=self._depth,
            extra={"speaker": "user"},
        )
        session.turns.append(turn)
        self.session_store.append_turn(turn)

        extraction: BeliefExtractionResult = self.extractor.extract_turn(
            text,
            session_id=session.session_id,
            turn_id=turn.turn_id,
            observed_at=instant,
        )

        outcome = PartnerTurnOutcome(
            user_turn=turn,
            dropped=list(extraction.rejected),
            raw_returned=extraction.raw_returned,
        )

        for claim in extraction.claims:
            # Externalized before detection, exactly like the turn itself. A
            # belief that lives only in this object's pool dies with the
            # process, and the approval path folds the log, so a belief the
            # log never saw can never be ratified — the first cassette-backed
            # demo accepted a belief and then compiled a doctrine of zero
            # rules because this append was the web service's private habit
            # rather than the session's contract (2026-08-31). Blocked
            # beliefs are appended too: the collision is adjudicated by the
            # approval path, which can only adjudicate what the log holds.
            self.session_store.store.append(
                Event.create(
                    event_type=EventType.CLAIM_ASSERTED,
                    occurred_at=claim.observed_at,
                    payload={"claim": claim.to_dict()},
                    actor="partner-session",
                )
            )
            detection = self.detector.detect(
                claim, list(self._pool.values()), aliases=self.aliases
            )
            if detection.contradictions:
                # The old belief is not overwritten, silently or otherwise.
                # The new one is held out of the pool; the approval path is the
                # only place the collision resolves.
                self._blocked[claim.claim_id] = claim
                outcome.blocked.append(claim)
                for contradiction in detection.contradictions:
                    card = self._card(claim, contradiction)
                    self._cards.append(card)
                    self._pending_cards.append(card)
                    outcome.cards.append(card)
            else:
                self._pool[claim.claim_id] = claim
                outcome.accepted.append(claim)
        return outcome

    def plan_next(self, last_answer: str) -> TurnPlan | None:
        """The next agent turn: card first, then clarifier, then next item.

        A queued divergence card preempts everything — the collision is the
        highest-value thing the session can surface, and burying it under a
        follow-up would waste the moment. ``None`` means the agenda is done.
        """
        if self._pending_cards:
            card = self._pending_cards.pop(0)
            return TurnPlan(
                kind=TurnKind.DIVERGENCE,
                text=card.render(),
                agenda_item_id=self._current_item.item_id,
                contradiction_id=card.contradiction_id,
                cited_claim_ids=[card.prior_claim_id],
                follow_up_depth=self._depth,
                card=card,
            )

        if self._depth < min(self.follow_up_budget, MAX_FOLLOW_UP_DEPTH):
            follow_up = self.interviewer.compose_follow_up(
                self._current_item, last_answer
            )
            if follow_up is not None:
                return TurnPlan(
                    kind=TurnKind.FOLLOW_UP,
                    text=follow_up,
                    agenda_item_id=self._current_item.item_id,
                    contradiction_id=self._current_item.contradiction_id or None,
                    cited_claim_ids=list(self._current_item.cited_claim_ids),
                    follow_up_depth=self._depth + 1,
                )

        nxt = self._next_item(self._current_item)
        if nxt is None:
            return None
        return self._plan_for_item(nxt)

    def close(self) -> None:
        session = self._require_session()
        self.session_store.close(session, closed_at=self._now())

    # ------------------------------------------------------------------ inner

    def _require_session(self) -> Session:
        if self.session is None:
            raise RuntimeError(
                "the session is not open. Call open() before speaking or "
                "observing turns; a turn appended to no session is a turn the "
                "log cannot replay."
            )
        return self.session

    def _next_item(self, current: AgendaItem) -> AgendaItem | None:
        position = self._item_order[current.item_id] + 1
        if position >= len(self.agenda.items):
            return None
        return self.agenda.items[position]

    def _plan_for_item(self, item: AgendaItem) -> TurnPlan:
        """A question for a contradiction item; worked output for a task step."""
        if item.contradiction_id:
            return TurnPlan(
                kind=TurnKind.AGENDA,
                text=item.question,
                agenda_item_id=item.item_id,
                contradiction_id=item.contradiction_id,
                cited_claim_ids=list(item.cited_claim_ids),
                follow_up_depth=0,
            )
        return TurnPlan(
            kind=TurnKind.AGENDA,
            text=self._work_step(item),
            agenda_item_id=item.item_id,
            contradiction_id=None,
            cited_claim_ids=[],
            follow_up_depth=0,
        )

    def _work_step(self, item: AgendaItem) -> str:
        """Generate the next concrete piece of work, under the doctrine."""
        prompt = (
            f"Task step: {item.question}\n"
            f"Why it matters: {item.why_it_matters or 'not stated'}\n"
        )
        try:
            response = self.client.generate(
                role="reasoning",
                prompt=prompt,
                system=_joined_system(
                    self.doctrine_system_prompt, _TASK_STEP_SYSTEM
                ),
                schema_name="",
                temperature=0.3,
                max_output_tokens=1024,
            )
            text = response.text.strip()
        except Exception:  # noqa: BLE001
            # A failed generation must not stall the session with a person
            # waiting. Falling back to the step's own wording keeps the loop
            # moving and keeps the failure visible in the transcript — the
            # turn reads as the bare step, not as invented work.
            text = ""
        return text or item.question

    def _card(
        self, new_claim: Claim, contradiction: Contradiction
    ) -> DivergenceCard:
        """Render one collision for this audience, failing closed per quote."""
        prior_id = next(
            (cid for cid in contradiction.claim_ids if cid != new_claim.claim_id),
            "",
        )
        prior = self._pool.get(prior_id)
        return DivergenceCard(
            contradiction_id=contradiction.contradiction_id,
            predicate_hint=new_claim.predicate_hint,
            new_claim_id=new_claim.claim_id,
            new_quote=self._quote(new_claim),
            new_anchor=new_claim.anchor.key(),
            prior_claim_id=prior_id,
            prior_quote=self._quote(prior) if prior is not None else "",
            prior_anchor=prior.anchor.key() if prior is not None else "",
            rationale=contradiction.rationale,
            confidence=contradiction.confidence,
        )

    def _quote(self, claim: Claim) -> str:
        """A quote for the card, through the boundary.

        ``quote_for`` returning ``None`` means this audience may not read the
        claim; the card then says so instead of leaking or fabricating.
        """
        quote = claim.quote_for(self.audience)
        return quote if quote is not None else "[not readable by this audience]"
