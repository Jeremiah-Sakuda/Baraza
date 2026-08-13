"""Interview sessions — state that survives a mid-stream kill.

BAR-334's acceptance criterion is a property, not an event: "state survives" is
proven by killing the process mid-turn and resuming, not by the session object
having been passed around. That shapes the design here.

Every turn is externalized to the append-only log **before** the next turn is
solicited. A session is therefore never "in memory only" for longer than the
duration of a single model call, and recovery is a fold over the session's own
events rather than a restore from a snapshot that may not exist.

The kill-test rig in ``tests/emulator/test_kill_survival.py`` SIGKILLs the
interview process partway through turn *n*, restarts it, and asserts the resumed
session replays turns 1..n-1 and re-solicits turn *n*. A turn that was appended
but not answered resumes as unanswered; a turn answered but not appended is
lost, which is the correct direction to fail.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence

from baraza.schema.temporal import EpochMillis, to_epoch_millis

__all__ = ["TurnRole", "SessionStatus", "Turn", "Session", "TurnKind"]


class TurnRole(str, Enum):
    AGENT = "agent"
    OFFICER = "officer"
    """The departing officer being interviewed."""


class TurnKind(str, Enum):
    """What the agent was doing on this turn.

    ``FOLLOW_UP`` is the adaptation signal: BAR-330's metric is mean follow-up
    depth per persona, computed over these labels by a standalone scorer with no
    imports from this package. The label is therefore part of the committed
    transcript's contract, not an implementation detail.
    """

    AGENDA = "agenda"
    """A question drawn directly from the generated agenda."""

    FOLLOW_UP = "follow_up"
    """A clarifying question generated in response to the previous answer."""

    DIVERGENCE = "divergence"
    """The product moment: testimony held against the documentary record."""

    CONFIRMATION = "confirmation"
    APPROVAL = "approval"
    ANSWER = "answer"


class SessionStatus(str, Enum):
    OPEN = "open"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True, slots=True)
class Turn:
    """One exchange, externalized before the next is solicited."""

    turn_id: str
    """Stable, human-quotable identifier — ``t-14``. BAR-330 requires the
    in-session adaptation moment to be locatable by a judge from the README, so
    turn IDs are sequential and readable rather than hashes."""

    session_id: str
    index: int
    role: TurnRole
    kind: TurnKind
    text: str
    occurred_at: EpochMillis
    agenda_item_id: Optional[str] = None
    contradiction_id: Optional[str] = None
    cited_claim_ids: List[str] = field(default_factory=list)
    """Claims quoted into this turn. Empty on an agent turn is a defect: the
    interviewer refuses to ask a citation-grounded question it cannot cite."""

    follow_up_depth: int = 0
    """0 for an agenda question, n for the nth consecutive clarifier. The
    adaptation metric is the mean of this over agent turns, per persona."""

    latency_ms: Optional[int] = None
    first_token_ms: Optional[int] = None
    """Measured in-process on the replay path. Any number derived from this
    field carries that provenance wherever it is displayed — an in-process
    timing is never reported as a deployed measurement."""

    extra: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def create(
        *,
        session_id: str,
        index: int,
        role: TurnRole,
        kind: TurnKind,
        text: str,
        occurred_at: Any,
        agenda_item_id: Optional[str] = None,
        contradiction_id: Optional[str] = None,
        cited_claim_ids: Optional[Sequence[str]] = None,
        follow_up_depth: int = 0,
        latency_ms: Optional[int] = None,
        first_token_ms: Optional[int] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> "Turn":
        return Turn(
            turn_id=f"t-{index}",
            session_id=session_id,
            index=index,
            role=role,
            kind=kind,
            text=text,
            occurred_at=to_epoch_millis(occurred_at, field="turn.occurred_at"),
            agenda_item_id=agenda_item_id,
            contradiction_id=contradiction_id,
            cited_claim_ids=list(cited_claim_ids or []),
            follow_up_depth=follow_up_depth,
            latency_ms=latency_ms,
            first_token_ms=first_token_ms,
            extra=dict(extra or {}),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "index": self.index,
            "role": self.role.value,
            "kind": self.kind.value,
            "text": self.text,
            "occurred_at": self.occurred_at,
            "agenda_item_id": self.agenda_item_id,
            "contradiction_id": self.contradiction_id,
            "cited_claim_ids": list(self.cited_claim_ids),
            "follow_up_depth": self.follow_up_depth,
            "latency_ms": self.latency_ms,
            "first_token_ms": self.first_token_ms,
            "extra": dict(self.extra),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Turn":
        return Turn(
            turn_id=payload["turn_id"],
            session_id=payload["session_id"],
            index=int(payload["index"]),
            role=TurnRole(payload["role"]),
            kind=TurnKind(payload["kind"]),
            text=payload["text"],
            occurred_at=to_epoch_millis(
                payload["occurred_at"], field="turn.occurred_at"
            ),
            agenda_item_id=payload.get("agenda_item_id"),
            contradiction_id=payload.get("contradiction_id"),
            cited_claim_ids=list(payload.get("cited_claim_ids") or []),
            follow_up_depth=int(payload.get("follow_up_depth", 0)),
            latency_ms=payload.get("latency_ms"),
            first_token_ms=payload.get("first_token_ms"),
            extra=dict(payload.get("extra") or {}),
        )


@dataclass(slots=True)
class Session:
    """An interview in progress or completed.

    Rebuilt by folding the session's own events, so a resumed process and a
    fresh one see identical state.
    """

    session_id: str
    persona_id: str
    """Which departing-officer persona is being interviewed. Replay runs use
    this to select canned answers; live runs record it for the metric."""

    opened_at: EpochMillis
    status: SessionStatus = SessionStatus.OPEN
    turns: List[Turn] = field(default_factory=list)
    closed_at: Optional[EpochMillis] = None
    resumed_count: int = 0
    """Incremented each time the session is recovered after a kill. Surfaced in
    the kill-test output so the demo can show a real resume rather than assert
    one."""

    extra: Dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def deterministic_id(*, persona_id: str, opened_at: EpochMillis) -> str:
        digest = hashlib.sha256(f"{persona_id}\x1f{opened_at}".encode()).hexdigest()
        return f"ses_{digest[:24]}"

    @property
    def next_index(self) -> int:
        return len(self.turns)

    def agent_turns(self) -> List[Turn]:
        return [t for t in self.turns if t.role is TurnRole.AGENT]

    def mean_follow_up_depth(self) -> float:
        """Convenience only — never the number that gets published.

        BAR-330 requires the published metric to come from
        ``scripts/adaptation_metric.py``, a standalone scorer with no imports
        from this package, run against the committed transcripts. A metric
        computed by the application over its own personas is one step from the
        hardcoded-literal-displayed-as-a-real-count defect class, so this method
        exists for in-process assertions and is explicitly not the source of any
        published figure.
        """
        agent_turns = self.agent_turns()
        if not agent_turns:
            return 0.0
        return sum(t.follow_up_depth for t in agent_turns) / len(agent_turns)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "persona_id": self.persona_id,
            "opened_at": self.opened_at,
            "status": self.status.value,
            "turns": [t.to_dict() for t in self.turns],
            "closed_at": self.closed_at,
            "resumed_count": self.resumed_count,
            "extra": dict(self.extra),
        }

    @staticmethod
    def from_dict(payload: Dict[str, Any]) -> "Session":
        return Session(
            session_id=payload["session_id"],
            persona_id=payload["persona_id"],
            opened_at=to_epoch_millis(payload["opened_at"], field="session.opened_at"),
            status=SessionStatus(payload.get("status", SessionStatus.OPEN.value)),
            turns=[Turn.from_dict(t) for t in payload.get("turns") or []],
            closed_at=(
                None
                if payload.get("closed_at") is None
                else to_epoch_millis(payload["closed_at"], field="session.closed_at")
            ),
            resumed_count=int(payload.get("resumed_count", 0)),
            extra=dict(payload.get("extra") or {}),
        )
