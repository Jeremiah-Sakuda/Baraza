"""BAR-321/322 — the disputed ledger.

A ranked view of everything the corpus disagrees with itself about, rendered for
one audience at a time.

Ranking is deliberate rather than by confidence alone. A high-confidence
disagreement about a defunct committee's meeting time matters less than a
medium-confidence one about who can sign a cheque, and an interview agenda
ordered purely by model confidence would spend a departing officer's scarce
attention on trivia. The score combines:

* **detector confidence** — how sure the adjudicator was;
* **stakes** — whether the predicate touches money, authority, or obligation;
* **recency** — how recent the newer of the two claims is;
* **spread** — whether the two sides come from *different* source documents,
  which is a stronger signal than one document contradicting itself.

Every component is inspectable and printed alongside the row, because a ranking
nobody can audit is a ranking nobody should trust.

**Redaction.** Rows are rendered per audience through
``Contradiction.render_for``. A row whose sides are not all readable still
appears — the count is honest — but its text is replaced by a placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from baraza.fold.graph import GraphState
from baraza.schema.contradiction import Contradiction, RenderedContradiction
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience

__all__ = ["LedgerRow", "DisputedLedger", "STAKES_PATTERNS"]

# Predicate hints that raise the stakes of a disagreement. Ordered, first match
# wins. These are a judgement about what matters in a succession handover, and
# they are written here as data so they can be argued with rather than buried.
STAKES_PATTERNS: List[tuple[str, float, str]] = [
    (r"sign|authoriz|approv|access|credential|password|admin", 1.0, "authority"),
    (r"budget|dues|fee|spend|reimburs|invoice|account|money|\$", 0.9, "money"),
    (r"deadline|renew|file|submit|compliance|required|must", 0.8, "obligation"),
    (r"term|elect|succeed|officer|role|chair|position", 0.7, "role"),
    (r"contact|vendor|advisor|partner", 0.5, "relationship"),
]


def _stakes(predicate_hint: str) -> tuple[float, str]:
    text = predicate_hint.lower()
    for pattern, weight, label in STAKES_PATTERNS:
        if re.search(pattern, text):
            return weight, label
    return 0.3, "other"


@dataclass(frozen=True, slots=True)
class LedgerRow:
    """One disagreement, ranked and rendered for a specific audience."""

    contradiction: Contradiction
    rendered: RenderedContradiction
    score: float
    stakes_weight: float
    stakes_label: str
    recency_weight: float
    spread_weight: float
    newest_claim_at: EpochMillis
    source_ids: List[str] = field(default_factory=list)

    @property
    def contradiction_id(self) -> str:
        return self.contradiction.contradiction_id

    def explain(self) -> str:
        """Why this row sits where it does. Printed in the ledger view."""
        return (
            f"score {self.score:.3f} = "
            f"confidence {self.contradiction.confidence:.2f} × "
            f"stakes {self.stakes_weight:.2f} ({self.stakes_label}) × "
            f"recency {self.recency_weight:.2f} × "
            f"spread {self.spread_weight:.2f}"
        )

    def render_lines(self) -> List[str]:
        lines = [
            f"[{self.contradiction_id[:12]}] {self.contradiction.subject_id} "
            f"— {self.contradiction.predicate_hint}",
            f"    {self.rendered.summary}",
        ]
        lines.extend(f"    · {side}" for side in self.rendered.sides)
        lines.append(f"    {self.explain()}")
        if not self.rendered.fully_readable:
            lines.append(
                "    (one or more sides redacted for this audience; counted, "
                "not quoted)"
            )
        return lines


class DisputedLedger:
    """The ranked view over a folded graph state."""

    def __init__(self, state: GraphState):
        self.state = state

    def rows(
        self,
        audience: Audience,
        *,
        limit: Optional[int] = None,
        min_score: float = 0.0,
    ) -> List[LedgerRow]:
        """Rank and render open contradictions for one audience.

        Resolved and retracted contradictions are absent by construction:
        ``GraphState.open_contradictions`` already excludes them, which is the
        closed loop — a disagreement answered in an interview never appears in
        a ledger again.
        """
        open_contradictions = self.state.open_contradictions()
        if not open_contradictions:
            return []

        newest_overall = max(
            self._newest_claim_at(c) for c in open_contradictions
        )
        oldest_overall = min(
            self._newest_claim_at(c) for c in open_contradictions
        )
        span = max(newest_overall - oldest_overall, 1)

        rows: List[LedgerRow] = []
        for contradiction in open_contradictions:
            stakes_weight, stakes_label = _stakes(contradiction.predicate_hint)
            newest = self._newest_claim_at(contradiction)
            recency_weight = 0.5 + 0.5 * ((newest - oldest_overall) / span)

            source_ids = sorted(
                {
                    self.state.claims[cid].anchor.source_id
                    for cid in contradiction.claim_ids
                    if cid in self.state.claims
                }
            )
            # Two documents disagreeing is a stronger signal than one document
            # being internally inconsistent, which is often just a typo.
            spread_weight = 1.0 if len(source_ids) > 1 else 0.75

            score = (
                contradiction.confidence
                * stakes_weight
                * recency_weight
                * spread_weight
            )
            if score < min_score:
                continue

            rows.append(
                LedgerRow(
                    contradiction=contradiction,
                    rendered=contradiction.render_for(self.state.claims, audience),
                    score=round(score, 4),
                    stakes_weight=stakes_weight,
                    stakes_label=stakes_label,
                    recency_weight=round(recency_weight, 4),
                    spread_weight=spread_weight,
                    newest_claim_at=newest,
                    source_ids=source_ids,
                )
            )

        rows.sort(key=lambda r: (-r.score, -r.newest_claim_at, r.contradiction_id))
        return rows[:limit] if limit else rows

    def _newest_claim_at(self, contradiction: Contradiction) -> EpochMillis:
        instants = [
            self.state.claims[cid].observed_at
            for cid in contradiction.claim_ids
            if cid in self.state.claims
        ]
        return max(instants) if instants else contradiction.detected_at

    def summary(self, audience: Audience) -> Dict[str, object]:
        """Counts for the console and the differential comparison.

        ``redacted`` is reported separately so the ledger can be honest about
        how much of itself this audience cannot see.
        """
        rows = self.rows(audience)
        return {
            "open_total": len(rows),
            "fully_readable": sum(1 for r in rows if r.rendered.fully_readable),
            "redacted": sum(1 for r in rows if not r.rendered.fully_readable),
            "by_stakes": _tally(r.stakes_label for r in rows),
            "cross_source": sum(1 for r in rows if len(r.source_ids) > 1),
        }


def _tally(labels) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for label in labels:
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
