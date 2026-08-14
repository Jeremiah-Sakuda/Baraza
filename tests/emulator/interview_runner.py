#!/usr/bin/env python3
"""A real interview process, written to be killed.

This is the subject of ``test_kill_survival.py``. It is a separate executable
rather than a thread or a mocked loop because the acceptance criterion is a
property about a **process**: BAR-334 says state survives a mid-stream kill, and
the only way to prove that is to SIGKILL something that cannot catch the signal,
clean up, or flush a buffer on the way out.

The loop does exactly what the interview service does, in the order that
matters:

1. Append the agent's question to the append-only log, durably (``fsync``).
2. *Then* solicit the answer.
3. Append the answer.

The window in which state exists only in memory is therefore one solicitation
wide. ``--stall-at N`` parks the process inside that window on exchange *N*,
which is where the test kills it.

Turn instants are derived from ``--opened-at`` plus the exchange index rather
than from the wall clock. Content-addressed event IDs then make re-appending a
question the process already recorded a no-op, so a resumed run re-asks without
duplicating — which is the behaviour under test, not a convenience.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from baraza.interview.session_store import SessionStore
from baraza.schema.session import Session, Turn, TurnKind, TurnRole

QUESTIONS = [
    "The records give two signing ceilings for the same year. Which did you use?",
    "Who actually approved spending between those two figures?",
    "Where is the reserve account paperwork kept now?",
    "What did the handover to your successor cover, and what did it miss?",
]

ANSWERS = [
    "Five hundred, in practice, all year.",
    "The chair signed off on anything over two fifty, verbally.",
    "In the filing cabinet, second drawer, in a folder marked reserve.",
    "We covered the bank login and nothing else, honestly.",
]


def build_store(args):
    """Pick the backend. Both are append-only; only durability differs."""
    if args.backend == "firestore":
        from baraza.fold.store import FirestoreEventStore

        return FirestoreEventStore(collection=args.collection)

    from baraza.fold.store import JsonlEventStore

    return JsonlEventStore(args.log)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="An interview loop that can be killed")
    parser.add_argument("--backend", choices=("jsonl", "firestore"), default="jsonl")
    parser.add_argument("--log", default="out/events.jsonl")
    parser.add_argument("--collection", default="events")
    parser.add_argument("--persona", default="persona-a")
    parser.add_argument("--opened-at", type=int, required=True)
    parser.add_argument("--exchanges", type=int, default=4)
    parser.add_argument("--stall-at", type=int, default=0)
    parser.add_argument("--stall-marker", default="")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)

    store = build_store(args)
    sessions = SessionStore(store)
    session_id = Session.deterministic_id(
        persona_id=args.persona, opened_at=args.opened_at
    )

    session = sessions.resume(session_id) if args.resume else None
    if session is None:
        session = sessions.open(persona_id=args.persona, opened_at=args.opened_at)
        print(f"OPENED {session.session_id}", flush=True)
    else:
        print(
            f"RESUMED {session.session_id} turns={len(session.turns)} "
            f"resumed_count={session.resumed_count}",
            flush=True,
        )
        pending = sessions.next_unanswered(session)
        print(f"PENDING {pending.turn_id if pending else 'none'}", flush=True)

    recorded = {turn.turn_id for turn in session.turns}

    for exchange in range(1, args.exchanges + 1):
        question_id = f"t-{2 * exchange - 1}"
        answer_id = f"t-{2 * exchange}"

        if answer_id in recorded:
            # Answered and durable. Replayed, not re-asked.
            print(f"REPLAY {question_id} {answer_id}", flush=True)
            continue

        at = args.opened_at + exchange * 60_000
        question = Turn.create(
            session_id=session_id,
            index=2 * exchange - 1,
            role=TurnRole.AGENT,
            kind=TurnKind.AGENDA,
            text=QUESTIONS[(exchange - 1) % len(QUESTIONS)],
            occurred_at=at,
            agenda_item_id=f"ag-{exchange:02d}",
        )
        written = sessions.append_turn(question)
        if question_id not in recorded:
            session.turns.append(question)
            recorded.add(question_id)
        print(f"{'ASK' if written else 'RE-ASK'} {question_id}", flush=True)

        if exchange == args.stall_at:
            # The question is durable; the answer has not arrived. This is the
            # one-solicitation-wide window, and the test kills the process here.
            print(f"SOLICIT {question_id}", flush=True)
            if args.stall_marker:
                Path(args.stall_marker).write_text(question_id, encoding="utf-8")
            while True:
                time.sleep(0.05)

        answer = Turn.create(
            session_id=session_id,
            index=2 * exchange,
            role=TurnRole.OFFICER,
            kind=TurnKind.ANSWER,
            text=ANSWERS[(exchange - 1) % len(ANSWERS)],
            occurred_at=at + 30_000,
            agenda_item_id=f"ag-{exchange:02d}",
        )
        sessions.append_turn(answer)
        session.turns.append(answer)
        recorded.add(answer_id)
        print(f"ANSWER {answer_id}", flush=True)

    sessions.close(session, closed_at=args.opened_at + (args.exchanges + 1) * 60_000)
    print("CLOSED", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
