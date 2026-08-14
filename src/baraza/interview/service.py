"""The deployed interview service (BAR-410).

A thin HTTP surface over :class:`~baraza.interview.interviewer.Interviewer`,
:class:`~baraza.interview.session_store.SessionStore` and
:class:`~baraza.interview.approval.ApprovalFlow`. The conversational logic lives
in those modules and is exercised identically by ``make demo-interview``; this
file adds transport, tracing, and the boundary decisions that only exist once
the thing is reachable over a network.

**Not public.** ``deploy/service-interview.yaml`` creates no ``allUsers``
invoker binding. This surface reads as :data:`Audience.OWNER` — it renders
private testimony, by design, because that is what an exit interview is. The
successor service is the public one and reads a strictly narrower set.

**Every turn is externalized before the next is solicited.** That is BAR-334's
property and it is the reason this service can run with
``containerConcurrency: 8`` and ``minScale: 0``: no session state lives in the
process, so an instance dying mid-interview loses nothing that was durably
written, and a resumed request folds the session back out of the log.

**Known gap, stated rather than discovered later.** The generated agenda is held
in a per-instance cache. Item IDs and the contradictions behind them are
recovered from the folded ledger on a cache miss, but the *wording* of a
question is a model output and can differ after a cold start or an instance
switch mid-interview. Persisting the agenda needs a payload field on
``session.opened``, which is the interview lane's schema change, not the deploy
lane's. Until then the honest description is: the agenda is stable within an
instance and re-derived across instances.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from baraza import telemetry
from baraza.fold.graph import GraphState, fold
from baraza.fold.store import EventStore, open_store
from baraza.interview.approval import ApprovalFlow, ApprovalRequest, Decision
from baraza.interview.interviewer import AdaptationState, Interviewer, TurnPlan
from baraza.interview.session_store import SessionStore
from baraza.llm import LLMClient, open_client
from baraza.reconcile.agenda import Agenda, AgendaGenerator, AgendaItem
from baraza.schema.claim import Claim
from baraza.schema.session import Session, Turn, TurnKind, TurnRole
from baraza.schema.temporal import EpochMillis, to_epoch_millis
from baraza.schema.visibility import Audience, Visibility

__all__ = ["app", "create_app"]

SERVICE_NAME = os.environ.get("BARAZA_SERVICE_NAME", "baraza-interview")

# The interview reads as the claim's owner. Written once, here, and passed
# explicitly into everything below — an audience that is inferred at a call site
# is an audience that will eventually be inferred wrongly.
SERVICE_AUDIENCE = Audience.OWNER

# How long a folded graph state may be reused across requests.
#
# The fold is over the whole event log, so doing it per request would make every
# turn O(log). Ten seconds is short enough that a claim committed in one request
# is visible to the next turn of the same conversation, and long enough that a
# burst of turns does not re-fold five times. The cache is per instance and
# holds no session state; a stale read costs one turn's freshness, never a lost
# answer.
STATE_TTL_SECONDS = 10.0


def now_millis() -> EpochMillis:
    """Wall clock as integer epoch millis, UTC.

    Routed through ``to_epoch_millis`` rather than computed inline so that every
    instant in the system — corpus, interview, heartbeat — is produced by one
    normalizer. BAR-309 is a rule about comparisons, and the cheapest way to
    keep comparisons correct is to never let an un-normalized instant exist.
    """
    return to_epoch_millis(time.time(), field="service.now")


# --------------------------------------------------------------- process state


class _Runtime:
    """Per-instance handles. Constructed lazily so import never needs credentials.

    Everything here is a cache or a client. Nothing here is state that would be
    lost if the instance died — that all lives in the append-only log, which is
    what makes ``minScale: 0`` safe on a conversational surface.
    """

    def __init__(self) -> None:
        self._store: EventStore | None = None
        self._client: LLMClient | None = None
        self._state: GraphState | None = None
        self._state_at: float = 0.0
        self._agendas: dict[str, Agenda] = {}
        self._adaptation: dict[str, AdaptationState] = {}

    @property
    def store(self) -> EventStore:
        if self._store is None:
            self._store = open_store()
        return self._store

    @property
    def client(self) -> LLMClient:
        if self._client is None:
            self._client = open_client()
        return self._client

    def state(self, *, force: bool = False) -> GraphState:
        if force or self._state is None or (time.monotonic() - self._state_at) > STATE_TTL_SECONDS:
            self._state = fold(self.store.read_all())
            self._state_at = time.monotonic()
        return self._state

    def invalidate(self) -> None:
        """Drop the folded state after a write, so the next read sees it."""
        self._state = None

    def adaptation(self, session: Session) -> AdaptationState:
        return self._adaptation.setdefault(
            session.session_id, AdaptationState(persona_id=session.persona_id)
        )

    def set_agenda(self, session: Session, agenda: Agenda) -> None:
        self._agendas[session.session_id] = agenda

    def agenda(self, session: Session) -> Agenda:
        """The session's agenda, regenerating on a cache miss.

        See the module docstring: regeneration recovers the same items from the
        same ledger, but question wording is a model output and may differ.
        """
        cached = self._agendas.get(session.session_id)
        if cached is not None:
            return cached
        generated = AgendaGenerator(self.client).generate(
            self.state(), audience=SERVICE_AUDIENCE
        )
        self._agendas[session.session_id] = generated
        return generated


_runtime = _Runtime()


# ------------------------------------------------------------------- payloads


class OpenSessionRequest(BaseModel):
    persona_id: str = Field(min_length=1, max_length=64)


class AnswerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class ApprovalItem(BaseModel):
    claim_id: str
    decision: str = Field(pattern="^(approve|reject|defer)$")
    # Absent means the claim keeps `private`. An approver declining to choose is
    # a valid outcome and resolves to the tier that leaks nothing — the default
    # is never "whatever the client sent".
    visibility: str | None = Field(default=None, pattern="^(private|successor|org|public)$")
    contradiction_id: str | None = None
    edited_text: str | None = Field(default=None, max_length=8000)
    note: str = ""


class ApprovalBatch(BaseModel):
    approver_id: str = Field(default="officer", max_length=64)
    items: list[ApprovalItem]


# --------------------------------------------------------------- serialization


def _turn_payload(turn: Turn) -> dict[str, Any]:
    return turn.to_dict()


def _plan_payload(plan: TurnPlan) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": plan.kind.value,
        "text": plan.text,
        "agenda_item_id": plan.agenda_item_id,
        "contradiction_id": plan.contradiction_id,
        "cited_claim_ids": list(plan.cited_claim_ids),
        "follow_up_depth": plan.follow_up_depth,
        "adaptation_note": plan.adaptation_note,
    }
    if plan.divergence is not None:
        # The divergence carries the conflicting quote because this audience is
        # OWNER and `check_divergence` already refused to build the finding for
        # any claim this audience cannot read. The read happened behind the
        # predicate; nothing here re-derives it.
        body["divergence"] = {
            "conflicting_claim_id": plan.divergence.conflicting_claim_id,
            "conflicting_anchor": plan.divergence.conflicting_anchor,
            "conflicting_quote": plan.divergence.conflicting_quote,
            "rationale": plan.divergence.rationale,
            "confidence": plan.divergence.confidence,
        }
    return body


def _current_item(agenda: Agenda, session: Session) -> AgendaItem | None:
    """The agenda item the last agent turn was working on."""
    for turn in reversed(session.turns):
        if turn.role is TurnRole.AGENT and turn.agenda_item_id:
            for item in agenda.items:
                if item.item_id == turn.agenda_item_id:
                    return item
    return agenda.items[0] if agenda.items else None


def _current_depth(session: Session) -> int:
    for turn in reversed(session.turns):
        if turn.role is TurnRole.AGENT:
            return turn.follow_up_depth
    return 0


def _append_agent_turn(
    session: Session, plan: TurnPlan, *, occurred_at: EpochMillis
) -> Turn:
    """Externalize an agent turn BEFORE the answer to it is solicited."""
    turn = Turn.create(
        session_id=session.session_id,
        index=session.next_index,
        role=TurnRole.AGENT,
        kind=plan.kind,
        text=plan.text,
        occurred_at=occurred_at,
        agenda_item_id=plan.agenda_item_id,
        contradiction_id=plan.contradiction_id,
        cited_claim_ids=list(plan.cited_claim_ids),
        follow_up_depth=plan.follow_up_depth,
        extra={"adaptation_note": plan.adaptation_note} if plan.adaptation_note else {},
    )
    SessionStore(_runtime.store).append_turn(turn)
    session.turns.append(turn)
    _runtime.invalidate()
    return turn


# ------------------------------------------------------------------------ app


@asynccontextmanager
async def _lifespan(_: FastAPI):
    telemetry.configure(SERVICE_NAME)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Baraza — interview service",
        version="0.1.0",
        lifespan=_lifespan,
        # No interactive docs on a surface that renders private testimony. The
        # schema would advertise every route to anyone who reaches the service,
        # and the only people who should reach it already have this file.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/healthz")
    def healthz() -> dict[str, Any]:
        """Liveness. Deliberately does no I/O.

        A health check that queries Firestore turns a transient database blip
        into a restart loop, which is strictly worse than serving a request that
        fails once. Store reachability is a separate, explicitly-called check.
        """
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "audience": SERVICE_AUDIENCE.value,
            "tracing": telemetry.exporter_status(),
        }

    @application.get("/readyz")
    def readyz() -> dict[str, Any]:
        """Store reachability, on demand. Not wired to a probe — see /healthz."""
        try:
            events = len(_runtime.store.read_all())
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"store unreachable: {exc}") from exc
        return {"status": "ok", "events": events}

    @application.post("/sessions", status_code=201)
    def open_session(body: OpenSessionRequest) -> dict[str, Any]:
        opened_at = now_millis()
        with telemetry.span(
            "interview.open_session", **{"baraza.persona_id": body.persona_id}
        ) as active:
            state = _runtime.state(force=True)
            agenda = AgendaGenerator(_runtime.client).generate(
                state, audience=SERVICE_AUDIENCE, generated_at=opened_at
            )
            if not agenda.items:
                # No open disagreement means no agenda-led question exists. The
                # interviewer refuses to ask a citation-grounded question it
                # cannot cite, so the honest response is that there is nothing
                # to interview about — not an invented opener.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "the ledger holds no open disagreement, so there is no "
                        "agenda to interview against. Run the reconciler first."
                    ),
                )

            session = SessionStore(_runtime.store).open(
                persona_id=body.persona_id, opened_at=opened_at
            )
            _runtime.set_agenda(session, agenda)
            interviewer = Interviewer(_runtime.client, state, audience=SERVICE_AUDIENCE)
            plan = interviewer.opening_turn(agenda, session)
            turn = _append_agent_turn(session, plan, occurred_at=opened_at)

            active.set_attribute("baraza.session_id", session.session_id)
            active.set_attribute("baraza.agenda_items", len(agenda.items))
            telemetry.record_audience(active, SERVICE_AUDIENCE)

        return {
            "session_id": session.session_id,
            "persona_id": session.persona_id,
            "opened_at": session.opened_at,
            "agenda": agenda.to_dict(),
            "turn": _turn_payload(turn),
        }

    @application.get("/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        session = SessionStore(_runtime.store).load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")
        return session.to_dict()

    @application.post("/sessions/{session_id}/answers")
    def answer(session_id: str, body: AnswerRequest) -> dict[str, Any]:
        """Record an answer and plan the next agent turn.

        The order is load-bearing: the officer's turn is appended first, then
        the agent's next turn is appended before it is returned. A process
        killed between the two resumes with the answer recorded and the question
        re-asked, which is the correct direction to fail — re-asking costs ten
        seconds, silently dropping an answer costs the organization a fact.
        """
        store = _runtime.store
        sessions = SessionStore(store)
        session = sessions.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")

        occurred_at = now_millis()
        agenda = _runtime.agenda(session)
        item = _current_item(agenda, session)
        if item is None:
            raise HTTPException(status_code=409, detail="session has no agenda items")

        officer_turn = Turn.create(
            session_id=session.session_id,
            index=session.next_index,
            role=TurnRole.OFFICER,
            kind=TurnKind.ANSWER,
            text=body.text,
            occurred_at=occurred_at,
            agenda_item_id=item.item_id,
        )
        sessions.append_turn(officer_turn)
        session.turns.append(officer_turn)
        _runtime.invalidate()

        adaptation = _runtime.adaptation(session)
        reason = adaptation.observe(body.text, turn_id=officer_turn.turn_id)

        with telemetry.span(
            "interview.plan_next",
            **{
                "baraza.session_id": session.session_id,
                "baraza.persona_id": session.persona_id,
                "baraza.turn_id": officer_turn.turn_id,
                "baraza.follow_up_budget": adaptation.follow_up_budget,
                "baraza.adaptation_changed": bool(reason),
            },
        ) as active:
            telemetry.record_audience(active, SERVICE_AUDIENCE)
            interviewer = Interviewer(
                _runtime.client, _runtime.state(), audience=SERVICE_AUDIENCE
            )
            plan = interviewer.plan_next(
                agenda=agenda,
                session=session,
                adaptation=adaptation,
                last_answer=body.text,
                current_item=item,
                current_depth=_current_depth(session),
            )
            if plan is None:
                active.set_attribute("baraza.turn_kind", "none")
            else:
                if reason:
                    plan.adaptation_note = reason
                active.set_attribute("baraza.turn_kind", plan.kind.value)
                cited = [
                    claim
                    for claim in (
                        _runtime.state().claims.get(cid) for cid in plan.cited_claim_ids
                    )
                    if claim is not None
                ]
                # Digests and IDs only. The quote never reaches the trace.
                telemetry.record_claims(active, cited)

        if plan is None:
            return {
                "session_id": session.session_id,
                "answer_turn": _turn_payload(officer_turn),
                "turn": None,
                "agenda_exhausted": True,
                "adaptation": adaptation.to_dict(),
            }

        agent_turn = _append_agent_turn(session, plan, occurred_at=now_millis())
        return {
            "session_id": session.session_id,
            "answer_turn": _turn_payload(officer_turn),
            "turn": _turn_payload(agent_turn),
            "plan": _plan_payload(plan),
            "agenda_exhausted": False,
            "adaptation": adaptation.to_dict(),
        }

    @application.post("/sessions/{session_id}/claims")
    def mint_claims(session_id: str) -> dict[str, Any]:
        """Turn this session's answers into pending claims for approval.

        Tier is ``pending`` and visibility is ``private``; only the approval
        path promotes and only an approver chooses visibility. This endpoint
        cannot commit anything, and the service account it runs under is not the
        thing stopping it — the code path simply does not exist here.
        """
        sessions = SessionStore(_runtime.store)
        session = sessions.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")

        agenda = _runtime.agenda(session)
        by_item = {item.item_id: item for item in agenda.items}
        interviewer = Interviewer(
            _runtime.client, _runtime.state(), audience=SERVICE_AUDIENCE
        )

        minted: list[dict[str, Any]] = []
        with telemetry.span("interview.mint_claims", **{"baraza.session_id": session_id}):
            for turn in session.turns:
                if turn.role is not TurnRole.OFFICER:
                    continue
                item = by_item.get(turn.agenda_item_id or "")
                if item is None:
                    continue
                claim = interviewer.claim_from_answer(
                    answer=turn.text,
                    item=item,
                    session=session,
                    turn=turn,
                    occurred_at=turn.occurred_at,
                )
                if claim is None:
                    continue
                minted.append(
                    {
                        "claim_id": claim.claim_id,
                        "turn_id": turn.turn_id,
                        "agenda_item_id": item.item_id,
                        "contradiction_id": item.contradiction_id,
                        "digest": claim.digest(),
                        "text": claim.quote_for(SERVICE_AUDIENCE),
                        "tier": claim.tier.value,
                        "visibility": claim.visibility.value,
                    }
                )
        return {"session_id": session_id, "claims": minted}

    @application.post("/sessions/{session_id}/approvals")
    def approve(session_id: str, body: ApprovalBatch) -> dict[str, Any]:
        """The promotion path. The only one.

        Claims are re-read from the folded log rather than accepted from the
        request body: a client that could post a claim object could post any
        claim object, including one whose quote it wrote itself.
        """
        state = _runtime.state(force=True)
        occurred_at = now_millis()

        requests: list[ApprovalRequest] = []
        for entry in body.items:
            claim: Claim | None = state.claims.get(entry.claim_id)
            if claim is None:
                raise HTTPException(
                    status_code=404, detail=f"no such claim: {entry.claim_id}"
                )
            requests.append(
                ApprovalRequest(
                    claim=claim,
                    decision=Decision(entry.decision),
                    visibility=(
                        Visibility(entry.visibility) if entry.visibility else None
                    ),
                    approver_id=body.approver_id,
                    contradiction_id=entry.contradiction_id,
                    note=entry.note,
                    edited_text=entry.edited_text,
                )
            )

        with telemetry.span(
            "interview.approve",
            **{
                "baraza.session_id": session_id,
                "baraza.approval_count": len(requests),
            },
        ) as active:
            telemetry.record_claims(active, [r.claim for r in requests])
            result = ApprovalFlow(_runtime.store).submit(
                requests, occurred_at=occurred_at, session_id=session_id
            )
            active.set_attribute("baraza.committed_count", len(result.committed))
            active.set_attribute("baraza.rejected_count", len(result.rejected))
            active.set_attribute(
                "baraza.contradictions_resolved", len(result.contradictions_resolved)
            )
        _runtime.invalidate()

        return {
            "committed": result.committed,
            "rejected": result.rejected,
            "deferred": result.deferred,
            "contradictions_resolved": result.contradictions_resolved,
            "visibility_choices": result.visibility_choices,
            "events_appended": result.events_appended,
        }

    @application.post("/sessions/{session_id}/close")
    def close_session(session_id: str) -> dict[str, Any]:
        sessions = SessionStore(_runtime.store)
        session = sessions.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")
        sessions.close(session, closed_at=now_millis())
        _runtime.invalidate()
        return {"session_id": session_id, "status": "closed", "turns": len(session.turns)}

    return application


app = create_app()
