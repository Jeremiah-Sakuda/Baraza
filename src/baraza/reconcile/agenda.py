"""The interview agenda — questions no human wrote.

The agenda is generated from the disputed ledger, unattended, on a cold corpus.
Nobody sits down and lists what to ask a departing treasurer; the system reads
what the records disagree about and derives the list.

**The closed loop is the property that makes this a system rather than a demo.**
A contradiction resolved in an interview emits ``contradiction.resolved``. The
fold drops it from ``open_contradictions``. The next agenda is therefore built
from a smaller ledger, and the next interview is shorter than the last. Nothing
retires an agenda item except an answer — and nothing has to remember to.

**The boundary applies here too.** An agenda item derived from a contradiction
whose sides the interviewee cannot read is downgraded, not dropped: the item
survives as an open-ended prompt ("the records disagree about X; what do you
remember?") with no quotes attached. Dropping it would let the boundary silently
shrink the agenda, which would make the visibility choice look free when it is
not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from baraza.fold.graph import GraphState
from baraza.llm import LLMClient
from baraza.reconcile.ledger import DisputedLedger, LedgerRow
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience

__all__ = ["AgendaItem", "Agenda", "AgendaGenerator", "DEFAULT_AGENDA_SIZE"]

DEFAULT_AGENDA_SIZE = 12
"""How many items an interview opens with.

Chosen against attention, not against coverage: a departing officer gives you
twenty minutes and a diminishing willingness to be precise. The ledger keeps
everything; the agenda takes what fits.
"""

_SYSTEM = """\
You write interview questions for an outgoing officer of a student organization.

You will be given a disagreement found between the organization's own records. \
Write ONE question that puts the disagreement to the person directly.

Requirements:

* Ground the question in the records. Quote or paraphrase what each side says.
* Be specific and answerable in a sentence or two. Never ask "tell me about the \
budget".
* Be neutral. The person is a volunteer who did their best with bad tooling, not \
a suspect. Never imply fault, never imply someone lied.
* Never name a person as having done something wrong. Refer to roles and \
records.
* If the disagreement is about money or authority, ask what was ACTUALLY done in \
practice, not only what the document says.

Return JSON only: {"question": "...", "why_it_matters": "one short sentence"}
"""


@dataclass(frozen=True, slots=True)
class AgendaItem:
    """One question, traceable to the disagreement that produced it."""

    item_id: str
    contradiction_id: str
    subject_id: str
    predicate_hint: str
    question: str
    why_it_matters: str
    score: float
    stakes_label: str
    fully_readable: bool
    cited_claim_ids: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "item_id": self.item_id,
            "contradiction_id": self.contradiction_id,
            "subject_id": self.subject_id,
            "predicate_hint": self.predicate_hint,
            "question": self.question,
            "why_it_matters": self.why_it_matters,
            "score": self.score,
            "stakes_label": self.stakes_label,
            "fully_readable": self.fully_readable,
            "cited_claim_ids": list(self.cited_claim_ids),
            "source_ids": list(self.source_ids),
        }


@dataclass(slots=True)
class Agenda:
    """A generated interview agenda."""

    items: list[AgendaItem] = field(default_factory=list)
    generated_at: EpochMillis | None = None
    audience: Audience = Audience.OWNER
    ledger_open_total: int = 0
    retired_since_last: int = 0

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "audience": self.audience.value,
            "ledger_open_total": self.ledger_open_total,
            "retired_since_last": self.retired_since_last,
            "items": [i.to_dict() for i in self.items],
        }

    def save(self, path) -> None:
        from pathlib import Path

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    def describe(self) -> list[str]:
        lines = [
            f"agenda: {len(self.items)} item(s) from {self.ledger_open_total} "
            f"open disagreement(s)",
        ]
        if self.retired_since_last:
            lines.append(
                f"  {self.retired_since_last} item(s) retired since the last "
                "interview — the loop closed on those"
            )
        redacted = sum(1 for i in self.items if not i.fully_readable)
        if redacted:
            lines.append(
                f"  {redacted} item(s) downgraded to open-ended prompts "
                "(sides not readable by this audience)"
            )
        return lines


class AgendaGenerator:
    """Turns the ranked ledger into questions."""

    def __init__(self, client: LLMClient):
        self.client = client

    def generate(
        self,
        state: GraphState,
        *,
        audience: Audience = Audience.OWNER,
        size: int = DEFAULT_AGENDA_SIZE,
        generated_at: EpochMillis | None = None,
    ) -> Agenda:
        ledger = DisputedLedger(state)
        rows = ledger.rows(audience)

        agenda = Agenda(
            generated_at=generated_at or state.last_event_at,
            audience=audience,
            ledger_open_total=len(rows),
            # The closed loop, counted: contradictions that have been answered
            # and are therefore absent from this agenda by construction.
            retired_since_last=sum(
                1 for c in state.contradictions.values() if not c.is_open
            ),
        )

        for index, row in enumerate(rows[:size], start=1):
            agenda.items.append(self._item(row, index))
        return agenda

    def _item(self, row: LedgerRow, index: int) -> AgendaItem:
        item_id = f"ag-{index:02d}"

        if not row.rendered.fully_readable:
            # Downgraded, not dropped. The item still occupies a slot and still
            # gets asked; it just carries no quotes.
            return AgendaItem(
                item_id=item_id,
                contradiction_id=row.contradiction_id,
                subject_id=row.contradiction.subject_id,
                predicate_hint=row.contradiction.predicate_hint,
                question=(
                    f"The records disagree about {row.contradiction.predicate_hint} "
                    f"for {_humanize(row.contradiction.subject_id)}, but part of "
                    "that record is outside what I can show you. What do you "
                    "remember about how this actually worked?"
                ),
                why_it_matters=(
                    "A disagreement exists here that cannot be quoted to this "
                    "audience."
                ),
                score=row.score,
                stakes_label=row.stakes_label,
                fully_readable=False,
                cited_claim_ids=[],
                source_ids=row.source_ids,
            )

        sides = "\n".join(f"  - {side}" for side in row.rendered.sides)
        prompt = (
            f"Subject: {_humanize(row.contradiction.subject_id)}\n"
            f"Relation: {row.contradiction.predicate_hint}\n"
            f"Why the adjudicator flagged this: {row.contradiction.rationale}\n"
            f"What the records say:\n{sides}\n"
        )

        response = self.client.generate(
            role="reasoning",
            prompt=prompt,
            system=_SYSTEM,
            schema_name="agenda_item.v1",
            temperature=0.3,
        )

        try:
            payload = response.json()
            question = str(payload["question"]).strip()
            why = str(payload.get("why_it_matters", "")).strip()
        except (json.JSONDecodeError, ValueError, KeyError, TypeError):
            # Fall back to a plain, honest question rather than skipping the
            # item. A malformed generation must not silently shrink the agenda.
            question = (
                f"The records give different answers about "
                f"{row.contradiction.predicate_hint} for "
                f"{_humanize(row.contradiction.subject_id)}. Which is right, and "
                "what happened in practice?"
            )
            why = row.contradiction.rationale

        return AgendaItem(
            item_id=item_id,
            contradiction_id=row.contradiction_id,
            subject_id=row.contradiction.subject_id,
            predicate_hint=row.contradiction.predicate_hint,
            question=question,
            why_it_matters=why,
            score=row.score,
            stakes_label=row.stakes_label,
            fully_readable=True,
            cited_claim_ids=list(row.contradiction.claim_ids),
            source_ids=row.source_ids,
        )


def _humanize(entity_id: str) -> str:
    return entity_id.removeprefix("ent:").replace("-", " ")
