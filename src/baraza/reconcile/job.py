"""The nightly reconcile Job — BAR-021 (stub) and BAR-321 (real), same entrypoint.

Deployed as a Cloud Run Job triggered by Cloud Scheduler. It exists in two
modes and the deployment is **replaced in place** when the real one lands, so
the execution history is continuous across the changeover and the replacement
date is identifiable in it.

``--stub``
    Appends a heartbeat event and exits. Deployed on day two of the build for
    one reason: execution history is the cheapest honest evidence of autonomy a
    project can accumulate, and it only accumulates in real time. A Scheduler
    stood up in the final week yields two nights of history by recording day; one
    stood up on day two yields a dozen.

``--real``
    Re-folds the log, snapshots the ledger, re-runs detection over claims
    written since the previous run, appends whatever it finds, and writes the
    differential against last night's snapshot.

Every event this Job appends is marked ``scheduled=True``. A scheduled run is
never counted as organic activity, in any accounting, anywhere.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from baraza.fold.graph import fold
from baraza.fold.store import EventStore, open_store
from baraza.reconcile.detect import ContradictionDetector
from baraza.reconcile.differential import (
    LedgerSnapshot,
    diff_snapshots,
    snapshot,
)
from baraza.schema.event import Event, EventType
from baraza.schema.visibility import Audience

__all__ = ["run_stub", "run_real", "main"]

SNAPSHOT_DIR = Path("out") / "snapshots"


@dataclass(slots=True)
class JobResult:
    run_id: str
    mode: str
    events_appended: int = 0
    contradictions_found: int = 0
    claims_examined: int = 0
    model_calls: int = 0
    snapshot_path: Optional[Path] = None
    diff_lines: List[str] = None  # type: ignore[assignment]

    def describe(self) -> List[str]:
        lines = [
            f"reconcile job [{self.mode}] run_id={self.run_id}",
            f"  events appended        {self.events_appended}",
        ]
        if self.mode == "real":
            lines.extend(
                [
                    f"  claims examined        {self.claims_examined}",
                    f"  contradictions found   {self.contradictions_found}",
                    f"  model calls            {self.model_calls} "
                    f"(one bounded call per claim examined, per BAR-320)",
                ]
            )
        if self.snapshot_path:
            lines.append(f"  snapshot               {self.snapshot_path}")
        if self.diff_lines:
            lines.extend(f"  {line}" for line in self.diff_lines)
        return lines


def _heartbeat_instant(run_id: str) -> int:
    """Derive the heartbeat instant from the run ID.

    Cloud Scheduler passes a run ID containing the scheduled time. Deriving the
    instant from it rather than from ``time.time()`` keeps event IDs
    deterministic, so a Job that is retried after a transient failure appends
    the same heartbeat rather than a second one — and the nightly-run count
    stays a count of nights rather than a count of attempts.
    """
    import re

    match = re.search(r"(\d{13})", run_id)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d{10})", run_id)
    if match:
        return int(match.group(1)) * 1000
    raise ValueError(
        f"run_id {run_id!r} carries no timestamp. Pass --run-id with an epoch "
        "millis or seconds component; the instant is never taken from wall "
        "clock, because that would make retries append duplicate heartbeats."
    )


def run_stub(store: EventStore, *, run_id: str) -> JobResult:
    """Append a heartbeat and exit. The BAR-021 placeholder."""
    result = JobResult(run_id=run_id, mode="stub")
    event = Event.create(
        event_type=EventType.HEARTBEAT,
        occurred_at=_heartbeat_instant(run_id),
        payload={
            "run_id": run_id,
            "mode": "stub",
            "note": (
                "BAR-021 stub reconcile Job. No-op beyond this heartbeat. "
                "Replaced in place by the real reconciler; the replacement date "
                "is identifiable in the Scheduler execution history."
            ),
        },
        actor="reconcile-job",
        scheduled=True,
    )
    if store.append(event):
        result.events_appended = 1
    return result


def run_real(
    store: EventStore,
    *,
    run_id: str,
    client=None,
    audience: Audience = Audience.OWNER,
    snapshot_dir: Path = SNAPSHOT_DIR,
) -> JobResult:
    """Re-fold, detect over new claims, snapshot, diff against last night."""
    from baraza.llm import open_client

    result = JobResult(run_id=run_id, mode="real")
    client = client or open_client()

    state = fold(store.read_all())

    # Only claims written since the previous heartbeat need examining. The whole
    # point of on-write detection is that last night's claims were already
    # adjudicated; re-running them would turn a bounded nightly cost into one
    # that grows with the corpus.
    previous = _previous_heartbeat(state)
    pool = state.retrievable_claims()
    fresh = [c for c in pool if c.observed_at > previous] if previous else pool
    result.claims_examined = len(fresh)

    detector = ContradictionDetector(client)
    for claim in fresh:
        detection = detector.detect(claim, pool, aliases=state.aliases)
        result.model_calls += detection.model_calls
        for contradiction in detection.contradictions:
            event = Event.create(
                event_type=EventType.CONTRADICTION_DETECTED,
                occurred_at=contradiction.detected_at,
                payload={"contradiction": contradiction.to_dict()},
                actor="reconcile-job",
                scheduled=True,
            )
            if store.append(event):
                result.events_appended += 1
                result.contradictions_found += 1

    heartbeat = Event.create(
        event_type=EventType.HEARTBEAT,
        occurred_at=_heartbeat_instant(run_id),
        payload={"run_id": run_id, "mode": "real"},
        actor="reconcile-job",
        scheduled=True,
    )
    if store.append(heartbeat):
        result.events_appended += 1

    # Snapshot after appending, so the snapshot reflects tonight's findings.
    state = fold(store.read_all())
    tonight = snapshot(state, run_id=run_id, scheduled=True, audience=audience)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    result.snapshot_path = tonight.save(snapshot_dir / f"{run_id}.json")

    last_night = _previous_snapshot(snapshot_dir, exclude=run_id)
    if last_night is not None:
        result.diff_lines = diff_snapshots(last_night, tonight).describe()

    return result


def _previous_heartbeat(state) -> Optional[int]:
    return max(state.heartbeats) if state.heartbeats else None


def _previous_snapshot(directory: Path, *, exclude: str) -> Optional[LedgerSnapshot]:
    if not directory.exists():
        return None
    candidates = [
        LedgerSnapshot.load(path)
        for path in sorted(directory.glob("*.json"))
        if path.stem != exclude
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.taken_at)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Baraza nightly reconcile job")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--stub", action="store_true", help="BAR-021 heartbeat only")
    mode.add_argument("--real", action="store_true", help="BAR-321 full reconciliation")
    parser.add_argument(
        "--run-id",
        required=True,
        help="Scheduler run id; must contain an epoch component",
    )
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    store = open_store(offline=args.offline)
    result = (
        run_stub(store, run_id=args.run_id)
        if args.stub
        else run_real(store, run_id=args.run_id)
    )

    if args.json:
        print(
            json.dumps(
                {
                    "run_id": result.run_id,
                    "mode": result.mode,
                    "events_appended": result.events_appended,
                    "contradictions_found": result.contradictions_found,
                    "claims_examined": result.claims_examined,
                    "model_calls": result.model_calls,
                    "scheduled": True,
                }
            )
        )
    else:
        for line in result.describe():
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
