"""BAR-334 — session state that survives a mid-stream kill.

The acceptance criterion is a property, not an event: "state survives" is proven
by killing the process partway through a turn and resuming, not by a session
object having been passed around. So the design is shaped by what a SIGKILL can
interrupt.

**Externalize before soliciting.** Every turn is appended to the log *before*
the next turn is requested. The window in which state exists only in memory is
therefore exactly one model call wide, and nothing outside that window can be
lost.

**Recover by folding, not by restoring.** A resumed process rebuilds the session
from its own events. There is no snapshot to be stale, no checkpoint to be
missing, and a resumed process and a fresh one see byte-identical state.

**Fail toward re-asking.** A turn appended but unanswered resumes as unanswered.
A turn answered but not yet appended is lost and re-solicited. That direction is
correct: re-asking a question costs a departing officer ten seconds, while
silently dropping their answer costs the organization the fact.

``tests/emulator/test_kill_survival.py`` SIGKILLs a live interview mid-turn,
restarts it, and asserts the resumed session replays turns 1..n-1 and
re-solicits turn n. It is a real kill of a real process, not a simulated one.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from baraza.fold.store import EventStore
from baraza.schema.event import Event, EventType
from baraza.schema.session import Session, SessionStatus, Turn, TurnKind, TurnRole
from baraza.schema.temporal import EpochMillis

__all__ = ["SessionStore"]


class SessionStore:
    """Append-only session persistence over the same event log as everything else.

    Sessions are not a separate store with separate durability characteristics.
    Putting them in the same append-only log is what makes "the interview
    survived a crash" the same guarantee as "the claim log survived a crash",
    rather than two guarantees that have to be reasoned about separately.
    """

    def __init__(self, store: EventStore):
        self.store = store

    # ------------------------------------------------------------------ write

    def open(
        self, *, persona_id: str, opened_at: EpochMillis, agenda_id: str = ""
    ) -> Session:
        session_id = Session.deterministic_id(
            persona_id=persona_id, opened_at=opened_at
        )
        event = Event.create(
            event_type=EventType.SESSION_OPENED,
            occurred_at=opened_at,
            payload={
                "session_id": session_id,
                "persona_id": persona_id,
                "agenda_id": agenda_id,
            },
            actor="interview",
        )
        self.store.append(event)
        return Session(
            session_id=session_id, persona_id=persona_id, opened_at=opened_at
        )

    def append_turn(self, turn: Turn) -> bool:
        """Externalize one turn. Call this BEFORE soliciting the next.

        Returns False if the turn was already recorded — which is what a resumed
        process sees when it re-appends a turn it had already durably written,
        and is not an error.
        """
        event = Event.create(
            event_type=EventType.SESSION_TURN,
            occurred_at=turn.occurred_at,
            payload={"turn": turn.to_dict()},
            actor="interview",
        )
        return self.store.append(event)

    def close(self, session: Session, *, closed_at: EpochMillis) -> None:
        event = Event.create(
            event_type=EventType.SESSION_CLOSED,
            occurred_at=closed_at,
            payload={
                "session_id": session.session_id,
                "turn_count": len(session.turns),
            },
            actor="interview",
        )
        self.store.append(event)

    # ------------------------------------------------------------------- read

    def load(self, session_id: str) -> Optional[Session]:
        """Rebuild a session by folding its own events.

        Turns are ordered by ``(occurred_at, turn index)`` — epoch millis, never
        a serialized string — so a session whose turns crossed a DST boundary
        or were written by processes in different regions still replays in the
        order they happened.
        """
        opened: Optional[Event] = None
        turns: Dict[str, Turn] = {}
        closed: Optional[Event] = None

        for event in self.store.read_all():
            payload = event.payload
            if (
                event.event_type is EventType.SESSION_OPENED
                and payload.get("session_id") == session_id
            ):
                opened = event
            elif event.event_type is EventType.SESSION_TURN:
                raw = payload.get("turn") or {}
                if raw.get("session_id") == session_id:
                    turn = Turn.from_dict(raw)
                    turns[turn.turn_id] = turn
            elif (
                event.event_type is EventType.SESSION_CLOSED
                and payload.get("session_id") == session_id
            ):
                closed = event

        if opened is None:
            return None

        session = Session(
            session_id=session_id,
            persona_id=opened.payload.get("persona_id", "unknown"),
            opened_at=opened.occurred_at,
            turns=sorted(turns.values(), key=lambda t: (t.occurred_at, t.index)),
            status=SessionStatus.COMPLETED if closed else SessionStatus.OPEN,
            closed_at=closed.occurred_at if closed else None,
        )
        return session

    def resume(self, session_id: str) -> Optional[Session]:
        """Load a session for continuation, recording that a resume happened.

        ``resumed_count`` is surfaced in the kill-test output so the demo shows
        a real resume rather than asserting one.
        """
        session = self.load(session_id)
        if session is None:
            return None
        session.resumed_count += 1
        return session

    def next_unanswered(self, session: Session) -> Optional[Turn]:
        """The agent turn awaiting an answer, if any.

        This is what makes recovery correct: a question that was durably written
        but never answered is exactly the question a resumed process must ask
        again.
        """
        for turn in reversed(session.turns):
            if turn.role is TurnRole.AGENT and turn.kind is not TurnKind.CONFIRMATION:
                following = [
                    t
                    for t in session.turns
                    if t.index > turn.index and t.role is TurnRole.OFFICER
                ]
                return None if following else turn
        return None

    def list_sessions(self) -> List[str]:
        return sorted(
            {
                event.payload["session_id"]
                for event in self.store.read_by_type(EventType.SESSION_OPENED)
                if event.payload.get("session_id")
            }
        )
