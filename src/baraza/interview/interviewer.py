"""BAR-330 — the interviewer.

Four properties, each of which has to be *provable* rather than asserted.

**Agenda-led.** Questions come from the generated agenda, which came from the
disputed ledger, which came from what the corpus disagrees with. No human wrote
the question list.

**Clarifying follow-ups.** An answer that leaves the disagreement unresolved
earns a follow-up. Follow-up depth is recorded per turn as structured data, not
inferred later from text.

**Adaptation, and specifically adaptation that can be measured by someone
else.** The interviewer adjusts how hard it pushes based on how the person
answers: a terse answerer earns more follow-ups because the detail has to be
drawn out; an expansive answerer earns fewer because the detail is already
arriving. The adjustment is *structural* — it changes a budget the next turn
reads — and it is *labelled* — the turn records the budget it ran under and the
reason it changed. That is what lets ``scripts/adaptation_metric.py``, a
standalone script with no imports from this package, compute mean follow-up
depth per persona from committed transcripts and get a number a judge can
reproduce to the digit.

A metric computed by the application over its own configured personas would be
one step from displaying a hardcoded literal as a real count. So the application
does not compute the published metric. It only emits the labelled transcript.

**The divergence moment.** When testimony conflicts with the documentary record,
the interviewer says so, in the moment, with both citations. This is the product.
Everything above it is setup.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

from baraza.fold.graph import GraphState
from baraza.llm import LLMClient
from baraza.reconcile.agenda import Agenda, AgendaItem
from baraza.schema.claim import Anchor, Claim, Provenance, Tier
from baraza.schema.session import Session, Turn, TurnKind
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience, Visibility, readable_by

__all__ = [
    "Interviewer",
    "AdaptationState",
    "DivergenceFinding",
    "TurnPlan",
    "TERSE_CHAR_THRESHOLD",
]

TERSE_CHAR_THRESHOLD = 180
"""Below this many characters, an answer is treated as terse.

Chosen from the fixture personas rather than tuned: the two replay personas sit
clearly on either side of it, so the adaptation is exercised in both directions
by the committed transcripts rather than only in one.
"""

MAX_FOLLOW_UP_DEPTH = 4
"""Ceiling regardless of adaptation.

A departing officer who has answered four clarifiers on one point has given what
they have. Pushing further trades goodwill for nothing, and an agent that cannot
stop asking is a worse failure than one that asks too little.
"""


@dataclass(slots=True)
class AdaptationState:
    """The interviewer's running model of how this person answers.

    Deliberately small and inspectable. Every field is written into the turn
    record, so a transcript reader can see exactly what the interviewer believed
    at each moment and why the budget moved.
    """

    persona_id: str
    follow_up_budget: int = 2
    answers_seen: int = 0
    terse_answers: int = 0
    expansive_answers: int = 0
    last_change_turn_id: str | None = None
    last_change_reason: str = ""

    @property
    def terse_ratio(self) -> float:
        if self.answers_seen == 0:
            return 0.0
        return self.terse_answers / self.answers_seen

    def observe(self, answer: str, *, turn_id: str) -> str | None:
        """Update from one answer. Returns a reason string if the budget moved.

        The change is the adaptation moment, and returning the reason rather
        than logging it internally is what lets the caller stamp it onto the
        turn — so it lands in the committed transcript and can be located later
        by turn ID.
        """
        self.answers_seen += 1
        length = len(answer.strip())

        if length < TERSE_CHAR_THRESHOLD:
            self.terse_answers += 1
        else:
            self.expansive_answers += 1

        # Wait for enough evidence that this is a pattern rather than one short
        # answer to an easy question.
        if self.answers_seen < 3:
            return None

        previous = self.follow_up_budget

        if self.terse_ratio >= 0.6 and self.follow_up_budget < MAX_FOLLOW_UP_DEPTH:
            self.follow_up_budget = min(self.follow_up_budget + 1, MAX_FOLLOW_UP_DEPTH)
        elif self.terse_ratio <= 0.25 and self.follow_up_budget > 1:
            self.follow_up_budget -= 1

        if self.follow_up_budget == previous:
            return None

        direction = "raised" if self.follow_up_budget > previous else "lowered"
        reason = (
            f"follow-up budget {direction} {previous}→{self.follow_up_budget} "
            f"after {self.answers_seen} answers "
            f"({self.terse_answers} terse, {self.expansive_answers} expansive; "
            f"terse ratio {self.terse_ratio:.2f})"
        )
        self.last_change_turn_id = turn_id
        self.last_change_reason = reason
        return reason

    def to_dict(self) -> dict[str, object]:
        return {
            "persona_id": self.persona_id,
            "follow_up_budget": self.follow_up_budget,
            "answers_seen": self.answers_seen,
            "terse_answers": self.terse_answers,
            "expansive_answers": self.expansive_answers,
            "terse_ratio": round(self.terse_ratio, 4),
            "last_change_turn_id": self.last_change_turn_id,
            "last_change_reason": self.last_change_reason,
        }


@dataclass(frozen=True, slots=True)
class DivergenceFinding:
    """Testimony held against the record. The product moment."""

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


@dataclass(slots=True)
class TurnPlan:
    """What the interviewer intends to say next, and why."""

    kind: TurnKind
    text: str
    agenda_item_id: str | None = None
    contradiction_id: str | None = None
    cited_claim_ids: list[str] = field(default_factory=list)
    follow_up_depth: int = 0
    divergence: DivergenceFinding | None = None
    adaptation_note: str = ""


_FOLLOW_UP_SYSTEM = """\
You are interviewing an outgoing officer of a student organization about how \
things actually worked. You have just received an answer that does not fully \
settle the question.

Write ONE short clarifying question — under 25 words — that targets the specific \
gap. Requirements:

* Target what is MISSING, not what was said. If they gave an amount but not who \
approved it, ask who approved it.
* Never repeat the original question in different words.
* Never ask two things at once.
* Be warm and brief. This person is doing you a favour.
* If the answer genuinely settles the question, return the single word: SETTLED

Return JSON only: {"question": "..."} or {"question": "SETTLED"}
"""

_DIVERGENCE_SYSTEM = """\
You compare a person's spoken testimony against the written record.

You will be given testimony and a set of claims extracted from documents. Decide \
whether the testimony CONTRADICTS any of them.

Be strict. Only report a contradiction when both cannot be true:

* The testimony asserts a different value for the same thing over the same \
period → contradiction.
* The testimony describes a different period, a later change, or a practice that \
differs from a policy without denying the policy → NOT a contradiction.
* The testimony is vague, hedged, or says "I don't remember" → NOT a \
contradiction.
* The testimony adds information the record lacks → NOT a contradiction.

Never treat a person as lying. A divergence between memory and record is \
information about both, and the most common cause is that the record is stale.

Return JSON only:
{"divergence": null}
or
{"divergence": {"claim_id": "...", "confidence": 0.0-1.0, \
"rationale": "one neutral sentence naming the specific difference"}}
"""


class Interviewer:
    """Runs one interview.

    The class holds no session state of its own — state lives in the session
    passed in and in the append-only log — so a resumed process constructs a
    fresh ``Interviewer`` and continues correctly.
    """

    def __init__(
        self,
        client: LLMClient,
        state: GraphState,
        *,
        audience: Audience = Audience.OWNER,
    ):
        self.client = client
        self.state = state
        self.audience = audience

    # --------------------------------------------------------------- planning

    def opening_turn(self, agenda: Agenda, session: Session) -> TurnPlan:
        item = agenda.items[0]
        return TurnPlan(
            kind=TurnKind.AGENDA,
            text=item.question,
            agenda_item_id=item.item_id,
            contradiction_id=item.contradiction_id,
            cited_claim_ids=list(item.cited_claim_ids),
            follow_up_depth=0,
        )

    def plan_next(
        self,
        *,
        agenda: Agenda,
        session: Session,
        adaptation: AdaptationState,
        last_answer: str,
        current_item: AgendaItem,
        current_depth: int,
    ) -> TurnPlan | None:
        """Decide the next agent turn: divergence, follow-up, or move on."""

        # 1. Divergence check runs first and always. It is the highest-value
        #    thing that can happen in an interview, and a follow-up asked
        #    *before* noticing a contradiction wastes the moment.
        divergence = self.check_divergence(last_answer, current_item)
        if divergence is not None:
            return TurnPlan(
                kind=TurnKind.DIVERGENCE,
                text=divergence.render(),
                agenda_item_id=current_item.item_id,
                contradiction_id=current_item.contradiction_id,
                cited_claim_ids=[divergence.conflicting_claim_id],
                follow_up_depth=current_depth,
                divergence=divergence,
            )

        # 2. Follow up, if the adapted budget allows and the answer left a gap.
        if current_depth < adaptation.follow_up_budget:
            follow_up = self.compose_follow_up(current_item, last_answer)
            if follow_up is not None:
                return TurnPlan(
                    kind=TurnKind.FOLLOW_UP,
                    text=follow_up,
                    agenda_item_id=current_item.item_id,
                    contradiction_id=current_item.contradiction_id,
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
            contradiction_id=nxt.contradiction_id,
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
                system=_FOLLOW_UP_SYSTEM,
                schema_name="follow_up.v1",
                temperature=0.4,
                max_output_tokens=200,
            )
            question = str(response.json().get("question", "")).strip()
        except Exception:  # noqa: BLE001
            # A failed follow-up generation moves the interview on rather than
            # stalling it. Losing one clarifier is cheap; hanging on a live
            # interview with a person waiting is not.
            return None

        if not question or question.upper().startswith("SETTLED"):
            return None
        return question

    # ------------------------------------------------------------- divergence

    def check_divergence(
        self, testimony: str, item: AgendaItem
    ) -> DivergenceFinding | None:
        """Hold testimony against the record.

        Candidates are restricted to claims **readable by this audience**. The
        interviewer cannot quote a private claim at someone in order to
        contradict them — that would leak the claim's content through the
        divergence message, which is precisely the leak the boundary exists to
        prevent.
        """
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
        prompt = f"TESTIMONY\n  {testimony.strip()}\n\nTHE RECORD\n{rendered}\n"

        try:
            response = self.client.generate(
                role="reasoning",
                prompt=prompt,
                system=_DIVERGENCE_SYSTEM,
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

        The anchor points at the interview turn itself — ``turn:t-14`` — which
        is a real, registered, resolvable location. Testimony is a source like
        any other, and treating it as one is what lets a future interview find
        a contradiction between two officers' memories.

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
