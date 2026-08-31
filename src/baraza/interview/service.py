"""The deployed interview service (BAR-410) — and the owner's session console.

A thin HTTP surface over :class:`~baraza.interview.interviewer.Interviewer`,
:class:`~baraza.interview.session_store.SessionStore` and
:class:`~baraza.interview.approval.ApprovalFlow`, plus the server-rendered
session view, divergence card, and approval queue from :mod:`baraza.web`. The
conversational logic lives in those modules; this file adds transport and the
boundary decisions that only exist once the thing is reachable over a network.

**Not public.** ``deploy/service-interview.yaml`` creates no ``allUsers``
invoker binding. This surface reads as :data:`Audience.OWNER` — it renders the
user's own private testimony back to the user, by design. The dossier service is
the public one and reads a strictly narrower set.

**Every turn is externalized before the next is solicited.** That is BAR-334's
property and it is the reason this service can run with
``containerConcurrency: 8`` and ``minScale: 0``: no session state lives in the
process, so an instance dying mid-session loses nothing that was durably
written, and a resumed request folds the session back out of the log.

**Cross-lane symbols are resolved defensively.** Belief extraction
(``baraza.ingest.extract``) and parts of the interviewer surface are owned by a
parallel lane and change under this service's feet. A symbol that is absent
degrades the one feature that needed it, with the degradation stated in the
response — a missing extractor must cost one turn's beliefs, never the whole
console. A symbol that is present but whose backend is unreachable is a 503
that says so: this service never fabricates a reply.

**Known gap, stated rather than discovered later.** The generated agenda is held
in a per-instance cache. Item IDs and the contradictions behind them are
recovered from the folded ledger on a cache miss, but the *wording* of a
question is a model output and can differ after a cold start or an instance
switch mid-session. Persisting the agenda needs a payload field on
``session.opened``, which is the interview lane's schema change, not this one's.
Until then the honest description is: the agenda is stable within an instance
and re-derived across instances.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from baraza import telemetry
from baraza.fold.graph import GraphState, fold
from baraza.fold.store import EventStore, open_store
from baraza.interview import interviewer as interviewer_mod
from baraza.interview.approval import ApprovalFlow, ApprovalRequest, Decision
from baraza.interview.session_store import SessionStore
from baraza.llm import LLMClient, open_client
from baraza.reconcile.agenda import Agenda, AgendaGenerator, AgendaItem
from baraza.reconcile.detect import ContradictionDetector
from baraza.schema.claim import Anchor, Claim, Provenance, Tier
from baraza.schema.event import Event, EventType
from baraza.schema.session import Session, Turn, TurnKind, TurnRole
from baraza.schema.temporal import EpochMillis, to_epoch_millis, to_iso
from baraza.schema.visibility import Audience, Visibility
from baraza.web import views
from baraza.web.defensive import call_tolerant, resolve_symbol

__all__ = ["app", "create_app"]

SERVICE_NAME = os.environ.get("BARAZA_SERVICE_NAME", "baraza-interview")

# The session reads as the claim's owner. Written once, here, and passed
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

FOLLOW_UP_BUDGET = 2
"""Fixed clarifier ceiling per agenda item on this surface.

Pacing policy belongs to the interview lane; the web face passes a constant so
its behavior is the same on every instance and every replay. Four unanswered
clarifiers in a row is a worse session than one missed nuance."""

_UNREACHABLE_DETAIL = (
    "The model backend could not be reached. Your turn was recorded in the "
    "append-only log, but no beliefs were extracted and no reply was generated "
    "— nothing is ever fabricated in its place. Retry when the backend is up; "
    "the recorded turn will still be there."
)


def now_millis() -> EpochMillis:
    """Wall clock as integer epoch millis, UTC.

    Routed through ``to_epoch_millis`` rather than computed inline so that every
    instant in the system — corpus, session, heartbeat — is produced by one
    normalizer. BAR-309 is a rule about comparisons, and the cheapest way to
    keep comparisons correct is to never let an un-normalized instant exist.
    """
    return to_epoch_millis(time.time(), field="service.now")


@dataclass(slots=True)
class _FixedPacing:
    """The constant follow-up budget, shaped like what ``plan_next`` expects.

    Exists so the interviewer's planner can be called whether or not the
    interview lane still accepts a pacing argument — ``call_tolerant`` drops the
    keyword if the parameter is gone.
    """

    follow_up_budget: int = FOLLOW_UP_BUDGET


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


def _interviewer(state: GraphState) -> Any:
    """The interview lane's ``Interviewer``, resolved at call time.

    The class is expected to exist; resolving it per call rather than at import
    means a mid-integration rename takes down the turns that need it with an
    honest 503 instead of preventing the whole service from starting.
    """
    cls = getattr(interviewer_mod, "Interviewer", None)
    if cls is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "the interviewer module exposes no Interviewer on this build; "
                "the session console cannot plan a reply and will not invent one."
            ),
        )
    return cls(_runtime.client, state, audience=SERVICE_AUDIENCE)


# ------------------------------------------------------------------- payloads


class OpenSessionRequest(BaseModel):
    persona_id: str = Field(min_length=1, max_length=64)


class AnswerRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class DivergenceDecision(BaseModel):
    """One adjudication of a divergence card.

    ``this_governs`` commits the new statement and retracts the old belief;
    ``that_governs`` reaffirms the old belief and retracts the new statement;
    ``both_conditional`` records a new conditional rule, superseding the new
    statement's wording, and retires the disagreement. All three run through
    :class:`ApprovalFlow` — this endpoint constructs no promotion events itself.
    """

    choice: str = Field(pattern="^(this_governs|that_governs|both_conditional)$")
    new_claim_id: str = Field(min_length=1)
    old_claim_id: str = Field(min_length=1)
    contradiction_id: str | None = None
    conditional_text: str | None = Field(default=None, max_length=8000)
    approver_id: str = Field(default="builder", max_length=64)


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
    approver_id: str = Field(default="builder", max_length=64)
    items: list[ApprovalItem]


# --------------------------------------------------------------- serialization


def _turn_payload(turn: Turn) -> dict[str, Any]:
    return turn.to_dict()


def _plan_payload(plan: Any) -> dict[str, Any]:
    """Serialize a ``TurnPlan`` through ``getattr`` — the shape is owned by the
    interview lane and may gain or lose fields between integrate passes."""
    body: dict[str, Any] = {
        "kind": getattr(getattr(plan, "kind", None), "value", None),
        "text": getattr(plan, "text", ""),
        "agenda_item_id": getattr(plan, "agenda_item_id", None),
        "contradiction_id": getattr(plan, "contradiction_id", None),
        "cited_claim_ids": list(getattr(plan, "cited_claim_ids", []) or []),
        "follow_up_depth": getattr(plan, "follow_up_depth", 0),
    }
    divergence = getattr(plan, "divergence", None)
    if divergence is not None:
        # The divergence carries the conflicting quote because this audience is
        # OWNER and `check_divergence` already refused to build the finding for
        # any claim this audience cannot read. The read happened behind the
        # predicate; nothing here re-derives it.
        body["divergence"] = {
            "conflicting_claim_id": divergence.conflicting_claim_id,
            "conflicting_anchor": divergence.conflicting_anchor,
            "conflicting_quote": divergence.conflicting_quote,
            "rationale": divergence.rationale,
            "confidence": divergence.confidence,
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
    session: Session,
    plan: Any,
    *,
    occurred_at: EpochMillis,
    extra: dict[str, Any] | None = None,
) -> Turn:
    """Externalize an agent turn BEFORE the answer to it is solicited."""
    turn = Turn.create(
        session_id=session.session_id,
        index=session.next_index,
        role=TurnRole.AGENT,
        kind=getattr(plan, "kind", TurnKind.AGENDA),
        text=getattr(plan, "text", ""),
        occurred_at=occurred_at,
        agenda_item_id=getattr(plan, "agenda_item_id", None),
        contradiction_id=getattr(plan, "contradiction_id", None),
        cited_claim_ids=list(getattr(plan, "cited_claim_ids", []) or []),
        follow_up_depth=getattr(plan, "follow_up_depth", 0),
        extra=dict(extra or {}),
    )
    SessionStore(_runtime.store).append_turn(turn)
    session.turns.append(turn)
    _runtime.invalidate()
    return turn


# ---------------------------------------------------- belief extraction (WS3)


def _extract_beliefs(
    *,
    session: Session,
    turn: Turn,
    occurred_at: EpochMillis,
) -> tuple[list[Claim], str | None]:
    """Mine the partner's turn for belief claims, via the extraction lane.

    Returns the extracted claims and an optional degradation note. The symbol is
    resolved by name at call time; a missing extractor is a stated degradation,
    while an extractor that raises means the backend is down and the caller must
    answer 503 — the two failures are different facts and are reported as such.
    """
    extract_fn = resolve_symbol(
        "baraza.ingest.extract",
        "claims_from_turn",
        "extract_turn_claims",
        "extract_beliefs",
        "beliefs_from_turn",
        "mine_turn",
    )
    if extract_fn is None:
        return [], (
            "belief extraction is not wired on this surface yet; the turn was "
            "recorded verbatim and no belief was invented in its place."
        )

    claims = call_tolerant(
        extract_fn,
        client=_runtime.client,
        turn_text=turn.text,
        text=turn.text,
        turn=turn,
        turn_id=turn.turn_id,
        session=session,
        session_id=session.session_id,
        state=_runtime.state(),
        occurred_at=occurred_at,
        observed_at=occurred_at,
        audience=SERVICE_AUDIENCE,
    )
    out: list[Claim] = [c for c in (claims or []) if isinstance(c, Claim)]
    return out, None


def _append_pending_claim(claim: Claim, *, occurred_at: EpochMillis, actor: str) -> None:
    """Append a ``claim.asserted`` event. Tier stays pending, visibility private.

    Promotion is not possible from here: only the approval flow constructs
    ``claim.committed`` and ``claim.visibility_set``.
    """
    _runtime.store.append(
        Event.create(
            event_type=EventType.CLAIM_ASSERTED,
            occurred_at=occurred_at,
            payload={"claim": claim.to_dict()},
            actor=actor,
        )
    )
    _runtime.invalidate()


def _detect_on_write(claims: list[Claim]) -> int:
    """On-write contradiction detection for freshly asserted beliefs.

    Reuses the reconciler's blocked, temporally-gated detector — no sweep. A
    detector failure is swallowed per claim: the nightly job re-examines
    anything missed, so losing one on-write detection costs freshness, not
    facts.
    """
    if not claims:
        return 0
    state = _runtime.state(force=True)
    detector = ContradictionDetector(_runtime.client)
    pool = state.retrievable_claims()
    found = 0
    for claim in claims:
        try:
            detection = detector.detect(claim, pool, aliases=state.aliases)
        except Exception:  # noqa: BLE001 — the nightly job is the backstop
            continue
        for contradiction in detection.contradictions:
            _runtime.store.append(
                Event.create(
                    event_type=EventType.CONTRADICTION_DETECTED,
                    occurred_at=contradiction.detected_at,
                    payload={"contradiction": contradiction.to_dict()},
                    actor="interview-on-write",
                )
            )
            found += 1
    if found:
        _runtime.invalidate()
    return found


def _claim_from_partner_turn(
    *,
    session: Session,
    turn: Turn,
    item: AgendaItem | None,
    occurred_at: EpochMillis,
) -> Claim | None:
    """A pending claim quoting the partner's own words, anchored to the turn.

    Used when a divergence fires so the adjudication has a concrete new side to
    commit or retract. Prefers the interviewer's own minting when an agenda item
    exists; falls back to a direct construction with the same anchor discipline
    (``turn:<id>`` is a real, registered, resolvable location).
    """
    text = turn.text.strip()
    if len(text) < 8:
        return None
    if item is not None:
        interviewer = _interviewer(_runtime.state())
        minter = getattr(interviewer, "claim_from_answer", None)
        if minter is not None:
            minted = call_tolerant(
                minter,
                answer=text,
                item=item,
                session=session,
                turn=turn,
                occurred_at=occurred_at,
            )
            if minted is not None:
                return minted
    return Claim.create(
        subject_id=f"ent:{session.persona_id}",
        predicate=(item.predicate_hint if item else "stated"),
        predicate_hint=(item.predicate_hint if item else "stated preference"),
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
        extra={"turn_id": turn.turn_id},
    )


# ------------------------------------------------------------ view projection


def _session_turn_rows(session: Session) -> list[dict[str, Any]]:
    return [
        {
            "role": t.role.value,
            "kind": t.kind.value,
            "text": t.text,
            "occurred_at_iso": to_iso(t.occurred_at),
            "is_partner": t.role is not TurnRole.AGENT,
        }
        for t in session.turns
    ]


def _agenda_rows(agenda: Agenda, state: GraphState) -> tuple[list[dict[str, Any]], int]:
    """Agenda items with their retirement ticks, from the folded log.

    An item is retired when the contradiction that spawned it is no longer
    open — resolution events retire agenda items, so the closed loop is visible
    on screen rather than asserted in prose.
    """
    open_ids = {c.contradiction_id for c in state.open_contradictions()}
    rows = []
    retired = 0
    for item in agenda.items:
        is_retired = item.contradiction_id not in open_ids
        retired += int(is_retired)
        rows.append(
            {
                "item_id": item.item_id,
                "question": item.question,
                "why_it_matters": item.why_it_matters,
                "retired": is_retired,
            }
        )
    return rows, retired


def _open_divergence(session: Session, state: GraphState) -> dict[str, Any] | None:
    """Rebuild the divergence card for the last unadjudicated divergence turn.

    The card is a projection of the log — the agent's divergence turn cites the
    conflicting claim, and the new side's pending claim ID is carried in the
    turn's ``extra`` — so a reloaded page shows the same card the live response
    did. The old side's quote is re-read through the audience predicate on
    every render; it is never cached in the turn.
    """
    for turn in reversed(session.turns):
        if turn.role is not TurnRole.AGENT:
            continue
        if turn.kind is not TurnKind.DIVERGENCE:
            return None
        old_claim_id = (turn.cited_claim_ids or [None])[0]
        new_claim_id = turn.extra.get("divergence_new_claim_id")
        old = state.claims.get(old_claim_id or "")
        new = state.claims.get(new_claim_id or "")
        if new is None or new.tier is not Tier.PENDING:
            return None  # already adjudicated (committed or retracted)
        return {
            "contradiction_id": turn.contradiction_id,
            "rationale": turn.extra.get("divergence_rationale", ""),
            "old_claim_id": old_claim_id,
            "old_quote": old.quote_for(SERVICE_AUDIENCE) if old else None,
            "old_anchor": old.anchor.key() if old else "",
            "new_claim_id": new_claim_id,
            "new_quote": new.quote_for(SERVICE_AUDIENCE),
            "new_anchor": new.anchor.key(),
        }
    return None


def _pending_rows(state: GraphState, *, session_id: str | None) -> list[dict[str, Any]]:
    """Pending beliefs for the approval queue, quotes read as OWNER.

    This surface is the owner's console — see ``SERVICE_AUDIENCE`` — so pending
    private claims are legible here and only here.
    """
    rows = []
    for claim in state.retrievable_claims():
        if claim.tier is not Tier.PENDING:
            continue
        if session_id and claim.session_id and claim.session_id != session_id:
            continue
        rows.append(
            {
                "claim_id": claim.claim_id,
                "rule": claim.predicate_hint or claim.predicate,
                "quote": claim.quote_for(SERVICE_AUDIENCE),
                "anchor": claim.anchor.key(),
                "learned_at_iso": to_iso(claim.observed_at),
            }
        )
    rows.sort(key=lambda r: r["claim_id"])
    return rows


# ------------------------------------------------------------------------ app


@asynccontextmanager
async def _lifespan(_: FastAPI):
    telemetry.configure(SERVICE_NAME)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Baraza — interview service",
        version="0.2.0",
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

    # ------------------------------------------------------------ HTML views

    @application.get("/", response_class=HTMLResponse)
    def session_index() -> HTMLResponse:
        sessions = []
        store = SessionStore(_runtime.store)
        for session_id in store.list_sessions():
            session = store.load(session_id)
            if session is None:
                continue
            sessions.append(
                {
                    "session_id": session.session_id,
                    "persona_id": session.persona_id,
                    "opened_at_iso": to_iso(session.opened_at),
                }
            )
        return HTMLResponse(views.render_session_index(sessions))

    @application.post("/sessions/open")
    def open_session_form(persona_id: str = Form(default="builder")) -> RedirectResponse:
        """Form target for the index page; delegates to the JSON endpoint."""
        payload = open_session(OpenSessionRequest(persona_id=persona_id))
        return RedirectResponse(
            url=f"/sessions/{payload['session_id']}/view", status_code=303
        )

    @application.get("/sessions/{session_id}/view", response_class=HTMLResponse)
    def session_view(session_id: str) -> HTMLResponse:
        session = SessionStore(_runtime.store).load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")
        state = _runtime.state()
        agenda = _runtime.agenda(session)
        agenda_rows, retired = _agenda_rows(agenda, state)
        pending = _pending_rows(state, session_id=session_id)
        return HTMLResponse(
            views.render_session_view(
                session_id=session.session_id,
                persona_id=session.persona_id,
                turns=_session_turn_rows(session),
                agenda_items=agenda_rows,
                retired_count=retired,
                divergence=_open_divergence(session, state),
                pending_count=len(pending),
            )
        )

    @application.get("/approvals", response_class=HTMLResponse)
    def approval_queue(session_id: str | None = None) -> HTMLResponse:
        state = _runtime.state(force=True)
        pending = _pending_rows(state, session_id=session_id)
        return HTMLResponse(
            views.render_approval_queue(session_id=session_id, pending=pending)
        )

    # --------------------------------------------------------- JSON endpoints

    @application.post("/sessions", status_code=201)
    def open_session(body: OpenSessionRequest) -> dict[str, Any]:
        opened_at = now_millis()
        with telemetry.span(
            "interview.open_session", **{"baraza.persona_id": body.persona_id}
        ) as active:
            state = _runtime.state(force=True)
            try:
                agenda = AgendaGenerator(_runtime.client).generate(
                    state, audience=SERVICE_AUDIENCE, generated_at=opened_at
                )
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=503, detail=_UNREACHABLE_DETAIL) from exc
            if not agenda.items:
                # No open disagreement means no agenda-led question exists. The
                # agent refuses to ask a citation-grounded question it cannot
                # cite, so the honest response is that there is nothing to open
                # a session about — not an invented opener.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "the ledger holds no open disagreement, so there is no "
                        "agenda to open a session against. Run the reconciler first."
                    ),
                )

            session = SessionStore(_runtime.store).open(
                persona_id=body.persona_id, opened_at=opened_at
            )
            _runtime.set_agenda(session, agenda)
            plan = _interviewer(state).opening_turn(agenda, session)
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

    @application.get("/sessions/{session_id}/state")
    def session_state(session_id: str) -> dict[str, Any]:
        """The polling endpoint behind the session view. Read-only."""
        session = SessionStore(_runtime.store).load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")
        state = _runtime.state()
        agenda = _runtime.agenda(session)
        agenda_rows, retired = _agenda_rows(agenda, state)
        return {
            "session_id": session.session_id,
            "turn_count": len(session.turns),
            "turns": _session_turn_rows(session),
            "agenda": agenda_rows,
            "retired_count": retired,
            "pending_count": len(_pending_rows(state, session_id=session_id)),
            "divergence": _open_divergence(session, state),
        }

    @application.post("/sessions/{session_id}/turns")
    def partner_turn(session_id: str, body: AnswerRequest) -> dict[str, Any]:
        """Ingest one partner turn: record, extract, detect, reply.

        The order is load-bearing: the partner's turn is appended first, then
        everything model-dependent runs, then the agent's reply is appended
        before it is returned. A process killed anywhere in between resumes
        with the turn recorded, which is the correct direction to fail — losing
        a reply costs a page reload, silently dropping a turn costs the user a
        fact about themselves.
        """
        store = _runtime.store
        sessions = SessionStore(store)
        session = sessions.load(session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="no such session")

        occurred_at = now_millis()
        agenda = _runtime.agenda(session)
        item = _current_item(agenda, session)

        turn = Turn.create(
            session_id=session.session_id,
            index=session.next_index,
            role=TurnRole.OFFICER,
            kind=TurnKind.ANSWER,
            text=body.text,
            occurred_at=occurred_at,
            agenda_item_id=item.item_id if item else None,
        )
        sessions.append_turn(turn)
        session.turns.append(turn)
        _runtime.invalidate()

        notes: list[str] = []
        with telemetry.span(
            "interview.partner_turn",
            **{
                "baraza.session_id": session.session_id,
                "baraza.turn_id": turn.turn_id,
            },
        ) as active:
            telemetry.record_audience(active, SERVICE_AUDIENCE)

            # 1. Belief extraction (cross-lane, defensive).
            try:
                extracted, degradation = _extract_beliefs(
                    session=session, turn=turn, occurred_at=occurred_at
                )
            except Exception as exc:  # noqa: BLE001 — backend down, be honest
                raise HTTPException(status_code=503, detail=_UNREACHABLE_DETAIL) from exc
            if degradation:
                notes.append(degradation)
            for claim in extracted:
                _append_pending_claim(claim, occurred_at=occurred_at, actor="extract")

            # 2. On-write contradiction detection over the new beliefs.
            detected = _detect_on_write(extracted)
            active.set_attribute("baraza.extracted", len(extracted))
            active.set_attribute("baraza.detected", detected)

            # 3. Plan the reply. The planner runs divergence-first.
            state = _runtime.state(force=True)
            interviewer = _interviewer(state)
            if item is None:
                plan = None
            else:
                try:
                    plan = call_tolerant(
                        interviewer.plan_next,
                        agenda=agenda,
                        session=session,
                        adaptation=_FixedPacing(),
                        last_answer=body.text,
                        current_item=item,
                        current_depth=_current_depth(session),
                    )
                except HTTPException:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise HTTPException(
                        status_code=503, detail=_UNREACHABLE_DETAIL
                    ) from exc

        if plan is None:
            return {
                "session_id": session.session_id,
                "turn": _turn_payload(turn),
                "reply": None,
                "agenda_exhausted": True,
                "extracted_claim_ids": [c.claim_id for c in extracted],
                "divergence": None,
                "notes": notes,
            }

        # 4. If a divergence fired, mint the new side as a pending claim so the
        #    card's actions have something concrete to commit or retract.
        divergence_card: dict[str, Any] | None = None
        agent_extra: dict[str, Any] = {}
        finding = getattr(plan, "divergence", None)
        if finding is not None:
            new_claim = _claim_from_partner_turn(
                session=session, turn=turn, item=item, occurred_at=occurred_at
            )
            if new_claim is not None:
                _append_pending_claim(
                    new_claim, occurred_at=occurred_at, actor="interview"
                )
                agent_extra = {
                    "divergence_new_claim_id": new_claim.claim_id,
                    "divergence_rationale": finding.rationale,
                }
                divergence_card = {
                    "contradiction_id": getattr(plan, "contradiction_id", None),
                    "rationale": finding.rationale,
                    "old_claim_id": finding.conflicting_claim_id,
                    "old_quote": finding.conflicting_quote,
                    "old_anchor": finding.conflicting_anchor,
                    "new_claim_id": new_claim.claim_id,
                    "new_quote": new_claim.quote_for(SERVICE_AUDIENCE),
                    "new_anchor": new_claim.anchor.key(),
                }

        agent_turn = _append_agent_turn(
            session, plan, occurred_at=now_millis(), extra=agent_extra
        )
        return {
            "session_id": session.session_id,
            "turn": _turn_payload(turn),
            "reply": _turn_payload(agent_turn),
            "plan": _plan_payload(plan),
            "agenda_exhausted": False,
            "extracted_claim_ids": [c.claim_id for c in extracted],
            "divergence": divergence_card,
            "notes": notes,
        }

    @application.post("/sessions/{session_id}/divergence")
    def adjudicate_divergence(
        session_id: str, body: DivergenceDecision
    ) -> dict[str, Any]:
        """Resolve a divergence card. Every path runs through the approval flow.

        The agent refuses to silently overwrite the old rule; this endpoint is
        where the user overwrites it out loud, with both claims named and the
        decision recorded as append-only events.
        """
        state = _runtime.state(force=True)
        occurred_at = now_millis()

        new_claim = state.claims.get(body.new_claim_id)
        old_claim = state.claims.get(body.old_claim_id)
        if new_claim is None or old_claim is None:
            raise HTTPException(
                status_code=404, detail="one side of the divergence is not in the log"
            )

        requests: list[ApprovalRequest] = []
        if body.choice == "this_governs":
            # The new statement wins: commit it, retract the old belief.
            requests = [
                ApprovalRequest(
                    claim=new_claim,
                    decision=Decision.APPROVE,
                    approver_id=body.approver_id,
                    contradiction_id=body.contradiction_id,
                    note="divergence adjudicated: the new statement governs",
                ),
                ApprovalRequest(
                    claim=old_claim,
                    decision=Decision.REJECT,
                    approver_id=body.approver_id,
                    note="superseded by the statement adjudicated to govern",
                ),
            ]
        elif body.choice == "that_governs":
            # The record stands: retract the new statement, reaffirm the old
            # belief (the re-approval is what carries the contradiction_id and
            # retires the disagreement from every future agenda).
            requests = [
                ApprovalRequest(
                    claim=new_claim,
                    decision=Decision.REJECT,
                    approver_id=body.approver_id,
                    note="divergence adjudicated: the recorded belief governs",
                ),
                ApprovalRequest(
                    claim=old_claim,
                    decision=Decision.APPROVE,
                    approver_id=body.approver_id,
                    contradiction_id=body.contradiction_id,
                    note="reaffirmed against a diverging statement",
                ),
            ]
        else:  # both_conditional
            text = (body.conditional_text or "").strip()
            if not text:
                raise HTTPException(
                    status_code=422,
                    detail=(
                        "splitting into a conditional requires the conditional's "
                        "wording — the rule is the user's, not the system's to invent"
                    ),
                )
            # The conditional supersedes the new statement's wording (a new
            # claim citing the same turn) and retires the disagreement. The old
            # belief stays committed: the conditional narrows it rather than
            # retracting it, and a future contradiction between them is the
            # detector's job to catch, not this endpoint's to preempt.
            requests = [
                ApprovalRequest(
                    claim=new_claim,
                    decision=Decision.APPROVE,
                    approver_id=body.approver_id,
                    contradiction_id=body.contradiction_id,
                    edited_text=text,
                    note="divergence split into a conditional governing both cases",
                ),
            ]

        result = ApprovalFlow(_runtime.store).submit(
            requests, occurred_at=occurred_at, session_id=session_id
        )
        _runtime.invalidate()
        return {
            "choice": body.choice,
            "committed": result.committed,
            "rejected": result.rejected,
            "contradictions_resolved": result.contradictions_resolved,
            "events_appended": result.events_appended,
        }

    @application.post("/sessions/{session_id}/answers")
    def answer(session_id: str, body: AnswerRequest) -> dict[str, Any]:
        """Record an answer and plan the next agent turn.

        The pre-web JSON path, kept for the replay harness and scripts. The
        session view posts to ``/turns``, which additionally extracts beliefs
        and mints the divergence card's pending claim.
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

        with telemetry.span(
            "interview.plan_next",
            **{
                "baraza.session_id": session.session_id,
                "baraza.persona_id": session.persona_id,
                "baraza.turn_id": officer_turn.turn_id,
            },
        ) as active:
            telemetry.record_audience(active, SERVICE_AUDIENCE)
            interviewer = _interviewer(_runtime.state())
            plan = call_tolerant(
                interviewer.plan_next,
                agenda=agenda,
                session=session,
                adaptation=_FixedPacing(),
                follow_up_budget=FOLLOW_UP_BUDGET,
                last_answer=body.text,
                current_item=item,
                current_depth=_current_depth(session),
            )
            if plan is None:
                active.set_attribute("baraza.turn_kind", "none")
            else:
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
            }

        agent_turn = _append_agent_turn(session, plan, occurred_at=now_millis())
        return {
            "session_id": session.session_id,
            "answer_turn": _turn_payload(officer_turn),
            "turn": _turn_payload(agent_turn),
            "plan": _plan_payload(plan),
            "agenda_exhausted": False,
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
        interviewer = _interviewer(_runtime.state())

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
