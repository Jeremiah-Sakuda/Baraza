"""BAR-323 — the differential ledger. The autonomy beat.

The claim this exists to make provable: *the agent worked while nobody was
watching, and the record changed as a result.*

The choreography needs real elapsed nights and cannot be compressed
retroactively:

1. **Night 1.** The nightly reconcile Job runs against the corpus as it stands.
   The ledger is snapshotted.
2. **An artifact drops.** A document that did not exist during night 1 — the
   April minutes — lands in the corpus the next day.
3. **Night 2.** The Job runs again, unattended, and finds disagreements between
   the new document and the existing record.
4. **The diff.** Comparing the two snapshots shows exactly what the agent found
   while no human was present: contradictions **added**, contradictions
   **retracted** because the new document settled them, and rankings that moved.

A diff computed from two snapshots taken minutes apart proves nothing. A diff
across two genuine nights, with a Scheduler execution history behind it, is the
evidence. That is why the calendar schedules this rather than assuming it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Set

from baraza.fold.graph import GraphState
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.temporal import EpochMillis, to_iso
from baraza.schema.visibility import Audience

__all__ = ["LedgerSnapshot", "LedgerDiff", "snapshot", "diff_snapshots"]


@dataclass(slots=True)
class LedgerSnapshot:
    """The ledger at one moment, in a form that survives to be compared later."""

    taken_at: EpochMillis
    run_id: str
    scheduled: bool
    """True when taken by a Cloud Scheduler run. A snapshot taken by hand during
    a demo is never presented as autonomy evidence."""

    rows: Dict[str, Dict[str, object]] = field(default_factory=dict)
    event_count: int = 0
    source_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "taken_at": self.taken_at,
            "taken_at_iso": to_iso(self.taken_at),
            "run_id": self.run_id,
            "scheduled": self.scheduled,
            "event_count": self.event_count,
            "source_ids": list(self.source_ids),
            "rows": self.rows,
        }

    def save(self, path: Path | str) -> Path:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8"
        )
        return target

    @staticmethod
    def load(path: Path | str) -> "LedgerSnapshot":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return LedgerSnapshot(
            taken_at=int(payload["taken_at"]),
            run_id=payload.get("run_id", "unknown"),
            scheduled=bool(payload.get("scheduled", False)),
            rows=payload.get("rows") or {},
            event_count=int(payload.get("event_count", 0)),
            source_ids=list(payload.get("source_ids") or []),
        )


def snapshot(
    state: GraphState,
    *,
    run_id: str,
    scheduled: bool,
    audience: Audience = Audience.OWNER,
) -> LedgerSnapshot:
    """Capture the ledger for later comparison."""
    ledger = DisputedLedger(state)
    rows = ledger.rows(audience)
    return LedgerSnapshot(
        taken_at=state.last_event_at or 0,
        run_id=run_id,
        scheduled=scheduled,
        event_count=state.event_count,
        source_ids=sorted(
            {c.anchor.source_id for c in state.claims.values()}
        ),
        rows={
            row.contradiction_id: {
                "subject_id": row.contradiction.subject_id,
                "predicate_hint": row.contradiction.predicate_hint,
                "score": row.score,
                "stakes_label": row.stakes_label,
                "rationale": row.contradiction.rationale,
                "source_ids": row.source_ids,
            }
            for row in rows
        },
    )


@dataclass(slots=True)
class LedgerDiff:
    """What changed between two nights."""

    before: LedgerSnapshot
    after: LedgerSnapshot
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    rescored: List[tuple[str, float, float]] = field(default_factory=list)
    new_sources: List[str] = field(default_factory=list)

    @property
    def nights_apart(self) -> float:
        """Elapsed time between the snapshots, in days.

        Printed with the diff so a reader can see whether this is a real
        overnight differential or two snapshots taken during the same demo.
        """
        return round((self.after.taken_at - self.before.taken_at) / 86_400_000, 2)

    @property
    def is_genuine_overnight(self) -> bool:
        """Both snapshots scheduled, and at least most of a day apart."""
        return (
            self.before.scheduled
            and self.after.scheduled
            and self.nights_apart >= 0.5
        )

    def describe(self) -> List[str]:
        lines = [
            f"differential ledger: {self.before.run_id} → {self.after.run_id}",
            f"  elapsed              {self.nights_apart} day(s)",
            f"  both runs scheduled  {self.before.scheduled and self.after.scheduled}",
        ]
        if not self.is_genuine_overnight:
            # Say it plainly rather than let a reader assume.
            lines.append(
                "  ⚠ NOT a genuine overnight differential — this diff is "
                "illustrative only and must not be presented as autonomy evidence"
            )
        if self.new_sources:
            lines.append(f"  new source(s)        {', '.join(self.new_sources)}")
        lines.extend(
            [
                f"  contradictions added   {len(self.added)}",
                f"  contradictions retired {len(self.removed)}",
                f"  rankings moved         {len(self.rescored)}",
            ]
        )
        for cid in self.added:
            row = self.after.rows[cid]
            lines.append(
                f"    + [{cid[:12]}] {row['subject_id']} — {row['predicate_hint']}"
            )
            lines.append(f"        {row['rationale']}")
        for cid in self.removed:
            row = self.before.rows[cid]
            lines.append(
                f"    - [{cid[:12]}] {row['subject_id']} — {row['predicate_hint']} "
                "(settled or retracted)"
            )
        for cid, old, new in self.rescored:
            direction = "↑" if new > old else "↓"
            lines.append(f"    {direction} [{cid[:12]}] {old:.3f} → {new:.3f}")
        return lines


def diff_snapshots(
    before: LedgerSnapshot, after: LedgerSnapshot, *, score_epsilon: float = 0.01
) -> LedgerDiff:
    """Compare two snapshots."""
    before_ids: Set[str] = set(before.rows)
    after_ids: Set[str] = set(after.rows)

    rescored: List[tuple[str, float, float]] = []
    for cid in sorted(before_ids & after_ids):
        old = float(before.rows[cid].get("score", 0.0))
        new = float(after.rows[cid].get("score", 0.0))
        if abs(new - old) >= score_epsilon:
            rescored.append((cid, old, new))

    return LedgerDiff(
        before=before,
        after=after,
        added=sorted(after_ids - before_ids),
        removed=sorted(before_ids - after_ids),
        rescored=rescored,
        new_sources=sorted(set(after.source_ids) - set(before.source_ids)),
    )
