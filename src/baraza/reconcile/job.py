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
    Re-folds the log, snapshots the ledger, re-runs detection over every claim
    the log does not already record as adjudicated, appends whatever it finds,
    and writes the differential against last night's ledger.

    The work pool is ``retrievable_claims() - adjudicated_claim_ids``: a set
    difference over ``claim.adjudicated`` facts, not a timestamp comparison.
    That distinction is load-bearing rather than stylistic — the timestamp
    version compared ``claim.observed_at`` (the instant a *document was
    authored*, often years ago) against the previous heartbeat (a wall-clock
    instant from last night), so it selected the empty set on every night after
    the first and the reconciler silently stopped doing any work at all. The
    log knows what it examined; nothing else has to guess.

    **Last night's ledger is re-folded from the log, never loaded from disk.**
    A Cloud Run Job execution gets a fresh, empty filesystem, and ``deploy/``
    mounts no volume and writes to no bucket, so a snapshot file written last
    night is simply not there tonight. Reading the differential back off local
    disk therefore produced ``None`` on every deployed night — permanently
    silent, in the one place BAR-323 is supposed to produce evidence, and
    invisible locally because a developer's ``out/snapshots/`` does persist
    between runs. Reconstruction removes the dependency instead of provisioning
    storage for it: the log is the only thing that crosses executions, the fold
    is deterministic, and folding the log's prefix up to the previous heartbeat
    reproduces last night's ledger exactly. Same principle as everything else
    here — there is no cache that can drift from the log, because there is no
    cache.

Every event this Job appends carries ``scheduled``, resolved from
``BARAZA_RUN_TRIGGER`` by :func:`resolve_scheduled` — true only when Cloud
Scheduler started the execution. A scheduled run is never counted as organic
activity, and a manual run is never counted as a scheduled one; the second half
of that sentence is the half that keeps the nightly-run count honest.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from baraza.fold.graph import fold
from baraza.fold.store import EventStore, open_store
from baraza.reconcile.detect import ContradictionDetector, DetectionResult
from baraza.reconcile.differential import (
    LedgerSnapshot,
    diff_snapshots,
    snapshot,
)
from baraza.reconcile.initiate import InitiationResult, propose_session
from baraza.schema.event import Event, EventType
from baraza.schema.visibility import Audience

__all__ = ["run_stub", "run_real", "main"]

SNAPSHOT_DIR = Path("out") / "snapshots"
"""Where tonight's snapshot is written for a human to open.

An **output artifact only**. Nothing in this module reads it back, and nothing
depends on it existing — see ``_snapshot_as_of``. A container-local path is a
fine place to put something a developer wants to look at after a local run, and
a terrible place to put something the next execution needs.
"""


@dataclass(slots=True)
class JobResult:
    run_id: str
    mode: str
    events_appended: int = 0
    contradictions_found: int = 0
    claims_examined: int = 0
    claims_adjudicated: int = 0
    claims_skipped: int = 0
    """Claims whose adjudication call failed. A degraded night, not a lost one.

    They are deliberately left without a ``claim.adjudicated`` event, so the
    next run examines them again. The count is printed because a night that
    skipped forty claims and a night that found nothing produce the same
    ``contradictions found 0`` line, and those are very different nights.
    """

    model_calls: int = 0
    snapshot_path: Path | None = None
    skipped_reasons: list[str] = field(default_factory=list)
    diff_lines: list[str] = None  # type: ignore[assignment]
    initiation: InitiationResult | None = None
    """The session proposal this run ended with — agenda size, the event ID,
    and which notification path was taken. ``None`` only if initiation itself
    raised, which the runners treat as a degraded ending, not a failed night."""

    def describe(self) -> list[str]:
        lines = [
            f"reconcile job [{self.mode}] run_id={self.run_id}",
            f"  events appended        {self.events_appended}",
        ]
        if self.mode == "real":
            lines.extend(
                [
                    f"  claims examined        {self.claims_examined}",
                    f"  adjudications recorded {self.claims_adjudicated} "
                    f"(claim.adjudicated events; the log's record of what was "
                    f"looked at, so tomorrow night does not look again)",
                    f"  contradictions found   {self.contradictions_found}",
                    f"  model calls            {self.model_calls} "
                    f"(one bounded call per claim examined, per BAR-320)",
                ]
            )
            if self.claims_skipped:
                lines.append(
                    f"  claims skipped         {self.claims_skipped} "
                    f"(adjudication call failed; left unexamined in the log so "
                    f"the next run retries them)"
                )
                lines.extend(f"  {line}" for line in self.skipped_reasons)
        if self.snapshot_path:
            lines.append(f"  snapshot               {self.snapshot_path}")
        if self.diff_lines:
            lines.extend(f"  {line}" for line in self.diff_lines)
        if self.initiation is not None:
            lines.extend(self.initiation.describe())
        else:
            lines.append(
                "  session proposed       NO — initiation raised; the reconcile "
                "work above still stands"
            )
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


def resolve_scheduled(trigger: str | None = None) -> bool:
    """Whether this execution was started by Cloud Scheduler.

    Read from ``BARAZA_RUN_TRIGGER``, which ``deploy/entrypoint-job.sh`` sets to
    ``cloud-scheduler`` only when the Scheduler invoked the Job, and which
    defaults to ``manual`` otherwise.

    This exists because the flag used to be hardcoded ``True`` on every append,
    including runs a human started by hand. The rule this project keeps stating
    — a scheduled job is never counted as organic activity — has an inverse that
    matters more here: a **manual** run recorded as scheduled inflates the very
    number BAR-410 puts on camera. The first live deployment produced exactly
    that: a `gcloud run jobs execute` wrote `scheduled=True` while the container
    log two lines above it read `baraza trigger : manual`.

    Anything other than ``cloud-scheduler`` counts as manual. Defaulting the
    other way would make an unset variable silently inflate the count, which is
    the failure this function exists to prevent.
    """
    import os

    resolved = (trigger or os.environ.get("BARAZA_RUN_TRIGGER", "manual")).strip().lower()
    return resolved == "cloud-scheduler"


def _initiate(
    store: EventStore,
    result: JobResult,
    *,
    run_id: str,
    scheduled: bool,
    audience: Audience,
) -> None:
    """The end hook, shared by both modes: propose the next session.

    Re-reads and re-folds so the agenda sees everything this run appended —
    tonight's contradictions are exactly what tomorrow's session is for.
    Initiation failing must not fail the job: the reconcile evidence above is a
    night that cannot be re-run, and a notification bug is not worth it. The
    exception is printed and the result records the absence.
    """
    try:
        events = store.read_all()
        state = fold(events)
        result.initiation = propose_session(
            store,
            state,
            events,
            run_id=run_id,
            proposed_at=_heartbeat_instant(run_id),
            scheduled=scheduled,
            audience=audience,
        )
        result.events_appended += 1 if result.initiation.proposed else 0
    except Exception as exc:  # noqa: BLE001 - deliberate boundary
        print(
            f"initiation failed ({type(exc).__name__}: {exc}); "
            "the reconcile run above is unaffected",
            file=sys.stderr,
        )


def run_stub(
    store: EventStore, *, run_id: str, scheduled: bool | None = None
) -> JobResult:
    """Append a heartbeat and exit. The BAR-021 placeholder."""
    scheduled = resolve_scheduled() if scheduled is None else scheduled
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
            "trigger": "cloud-scheduler" if scheduled else "manual",
        },
        actor="reconcile-job",
        scheduled=scheduled,
    )
    if store.append(event):
        result.events_appended = 1
    # Agenda-only initiation: the stub does no claims work, but it still ends
    # by proposing the next session from whatever the fold already holds, so
    # the initiation habit — and its evidence — starts accruing before the real
    # reconciler lands.
    _initiate(
        store, result, run_id=run_id, scheduled=scheduled, audience=Audience.OWNER
    )
    return result


def run_real(
    store: EventStore,
    *,
    run_id: str,
    client=None,
    audience: Audience = Audience.OWNER,
    snapshot_dir: Path = SNAPSHOT_DIR,
    scheduled: bool | None = None,
) -> JobResult:
    """Re-fold, detect over new claims, snapshot, diff against last night."""
    from baraza.llm import open_client

    scheduled = resolve_scheduled() if scheduled is None else scheduled
    result = JobResult(run_id=run_id, mode="real")
    client = client or open_client()

    # Read once. These are the events as they stood before tonight touched
    # anything, which is exactly what last night's ledger has to be rebuilt
    # from, so keeping the list is cheaper and more honest than re-reading and
    # hoping nothing moved underneath.
    events = store.read_all()
    state = fold(events)
    prior = _prior_run(events, exclude_run_id=run_id)

    # Only claims the reconciler has not already examined need examining. The
    # whole point of on-write detection is that last night's claims were already
    # adjudicated; re-running them would turn a bounded nightly cost into one
    # that grows with the corpus.
    #
    # "Already examined" is read out of the log as a set of `claim.adjudicated`
    # facts, not inferred from a timestamp. The inference this replaced compared
    # `claim.observed_at` against the previous heartbeat, and `observed_at` is
    # the instant the *document was authored* (see ``ingest/pipeline.py``), not
    # the instant the claim was written. The corpus is dated 2016 onwards, so
    # every claim was older than every heartbeat and the filter selected nothing
    # on every night after the first: the job reported success, made zero model
    # calls, and found zero contradictions, forever. A set difference over
    # recorded facts has no such failure mode — a claim is unexamined until the
    # log says otherwise.
    examined = state.adjudicated_claim_ids
    pool = state.retrievable_claims()
    fresh = [c for c in pool if c.claim_id not in examined]
    result.claims_examined = len(fresh)

    adjudicated_at = _heartbeat_instant(run_id)
    detector = ContradictionDetector(client)
    for claim in fresh:
        try:
            detection = detector.detect(claim, pool, aliases=state.aliases)
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            # One claim's adjudication failing must not end the night. Note what
            # is *not* done here: no ``claim.adjudicated`` event is appended, so
            # the claim stays unexamined in the log and tomorrow night picks it
            # up. The cost of a transient failure is one repeated model call,
            # never a claim that quietly falls out of the system.
            result.claims_skipped += 1
            result.skipped_reasons.append(
                DetectionResult(
                    claim_id=claim.claim_id,
                    skipped_reason=f"detection-call-failed: {type(exc).__name__}: {exc}",
                ).describe()
            )
            continue
        result.model_calls += detection.model_calls
        for contradiction in detection.contradictions:
            event = Event.create(
                event_type=EventType.CONTRADICTION_DETECTED,
                # The instant this run found it, not
                # ``contradiction.detected_at`` — which the detector sets to the
                # later of the two claims' ``observed_at``, i.e. the instant a
                # *document was authored*. Every corpus date is years before
                # every run instant, so stamping the event that way filed
                # tonight's discovery in 2016 and put it on the wrong side of
                # every time prefix of the log, including the one
                # ``_snapshot_as_of`` takes. The contradiction keeps its own
                # ``detected_at`` field untouched in the payload; this is the
                # log saying when the fact entered the record.
                occurred_at=adjudicated_at,
                payload={"contradiction": contradiction.to_dict()},
                actor="reconcile-job",
                scheduled=scheduled,
            )
            if store.append(event):
                result.events_appended += 1
                result.contradictions_found += 1

        # Record the examination itself. Appended after detection, so a Job that
        # dies mid-claim leaves that claim unexamined and the next night picks it
        # up — the failure mode is a repeated model call, not a silent gap.
        # Deterministic ID over (run instant, claim id) keeps a retried Job
        # idempotent.
        adjudication = Event.create(
            event_type=EventType.CLAIM_ADJUDICATED,
            occurred_at=adjudicated_at,
            payload={"claim_id": claim.claim_id, "run_id": run_id},
            actor="reconcile-job",
            scheduled=scheduled,
        )
        if store.append(adjudication):
            result.events_appended += 1
            result.claims_adjudicated += 1

    heartbeat = Event.create(
        event_type=EventType.HEARTBEAT,
        occurred_at=_heartbeat_instant(run_id),
        payload={"run_id": run_id, "mode": "real"},
        actor="reconcile-job",
        scheduled=scheduled,
    )
    if store.append(heartbeat):
        result.events_appended += 1

    # Snapshot after appending, so the snapshot reflects tonight's findings.
    state = fold(store.read_all())
    tonight = snapshot(state, run_id=run_id, scheduled=scheduled, audience=audience)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    result.snapshot_path = tonight.save(snapshot_dir / f"{run_id}.json")

    # BAR-323. Last night's ledger comes out of the log, not out of
    # ``snapshot_dir`` — the directory above may be, and on Cloud Run always is,
    # empty at this point.
    if prior is not None:
        last_night = _snapshot_as_of(events, prior, audience=audience)
        result.diff_lines = diff_snapshots(last_night, tonight).describe()

    # The end hook: after the night's real work, propose tomorrow's session.
    _initiate(
        store, result, run_id=run_id, scheduled=scheduled, audience=audience
    )
    return result


@dataclass(frozen=True, slots=True)
class _PriorRun:
    """The previous night, as the log records it."""

    instant: int
    run_id: str
    scheduled: bool
    """Taken from the heartbeat event, not assumed. A differential whose earlier
    side was produced by a hand-run job is not overnight evidence, and
    ``LedgerDiff.is_genuine_overnight`` can only say so if this is truthful."""


def _prior_run(
    events: Sequence[Event], *, exclude_run_id: str
) -> _PriorRun | None:
    """The most recent heartbeat that is not this run's own.

    The exclusion matters on a retry. Heartbeat IDs are content-addressed, so a
    Job that is retried after a partial failure finds its own heartbeat already
    in the log; without the filter it would diff tonight against tonight and
    report "nothing changed" on precisely the nights where something went wrong
    the first time.

    Returns ``None`` on the first night ever. That is not a failure — there is
    genuinely nothing to compare against, and saying so is better than
    manufacturing an empty baseline that would make night one look like a night
    on which the agent found nothing.
    """
    latest: Event | None = None
    for event in events:
        if event.event_type is not EventType.HEARTBEAT:
            continue
        if event.payload.get("run_id") == exclude_run_id:
            continue
        if latest is None or event.order_key > latest.order_key:
            latest = event
    if latest is None:
        return None
    return _PriorRun(
        instant=latest.occurred_at,
        run_id=str(latest.payload.get("run_id") or f"heartbeat@{latest.occurred_at}"),
        scheduled=latest.scheduled,
    )


def _snapshot_as_of(
    events: Sequence[Event], prior: _PriorRun, *, audience: Audience
) -> LedgerSnapshot:
    """Rebuild the ledger as it stood at the end of ``prior``, from the log.

    Comparison is on epoch millis (BAR-309), and the prefix is taken inclusively
    at the heartbeat instant so the snapshot lands where last night's run
    finished rather than just before it — last night's own findings are stamped
    at exactly that instant.

    **What this prefix can and cannot see, stated rather than assumed.** This
    log carries two kinds of instant on purpose. Events the reconciler appends
    — ``heartbeat``, ``claim.adjudicated``, and its ``contradiction.detected``
    — are stamped when the run happened. ``claim.asserted`` is stamped at
    ``claim.observed_at``, the instant the *source document was authored*
    (``ingest/pipeline.py``), which for this corpus is 2016 onwards and always
    below any run instant.

    So the prefix reconstructs the **adjudication** history exactly: everything
    tonight found falls after the cut, everything last night found falls on or
    before it, and ``added`` is precisely what this run contributed. It cannot
    reconstruct the **arrival** history: a document ingested this morning is
    backdated to the year it was written, so it sits inside the baseline and
    ``LedgerDiff.new_sources`` will not report it. That line stays in
    ``describe()`` because a hand-run comparison of two saved snapshots can
    still populate it; a nightly differential should not be read as evidence
    about when a source arrived. Giving arrival its own instant would mean a
    second timestamp on every claim event, which is a schema change, not a
    reconciler change.
    """
    prior_state = fold(e for e in events if e.occurred_at <= prior.instant)
    return snapshot(
        prior_state,
        run_id=prior.run_id,
        scheduled=prior.scheduled,
        audience=audience,
    )


def main(argv: list[str] | None = None) -> int:
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
                    "claims_adjudicated": result.claims_adjudicated,
                    # Emitted even when zero. A field that appears only on a bad
                    # night is a field nobody's dashboard has a series for.
                    "claims_skipped": result.claims_skipped,
                    "model_calls": result.model_calls,
                    # Resolved, never assumed. This line used to be the literal
                    # True, which reported every hand-run job as a scheduled one
                    # in the machine-readable output — the exact inflation
                    # resolve_scheduled() exists to prevent.
                    "scheduled": resolve_scheduled(),
                    "session_proposed": result.initiation is not None
                    and result.initiation.proposed,
                    "agenda_items": (
                        len(result.initiation.agenda)
                        if result.initiation is not None
                        else 0
                    ),
                    "invitation_channel": (
                        result.initiation.channel
                        if result.initiation is not None
                        else "none"
                    ),
                }
            )
        )
    else:
        for line in result.describe():
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
