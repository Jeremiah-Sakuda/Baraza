"""The deployed successor service (BAR-410, BAR-411) — and the public surface.

This is the hosted URL a judge visits while logged out. Everything about it is
shaped by that.

**It reads one set and only one set: claims that are ``committed`` *and*
``readable_by(Audience.PUBLIC)``.** Both halves matter and they are different
axes. ``committed`` is the retraction axis — a claim reaches it because a human
approved it, and a rejected claim leaves permanently. ``PUBLIC`` is the
visibility axis — an approver explicitly chose to publish. ``visibility``
defaults to ``private``, so a claim nobody made a decision about is invisible
here by construction rather than by filter.

**A fresh deployment therefore shows nothing, and that is the boundary working.**
The page says so in as many words. The failure this project keeps naming is a
demo surface that renders private testimony because somebody forgot a predicate;
an empty page is what the correct version looks like before anyone has approved
anything, and dressing it up with sample content would make the one surface a
judge actually visits the one surface that lies.

**The refusal is a feature.** ``Librarian`` answers only from the readable
committed record and refuses when that record cannot support an answer. It does
not fall back on general knowledge about how student organizations usually work.
A successor cannot tell a remembered fact from a fluent guess, and a guess about
who can sign a cheque is worse than silence — silence is recoverable.

**Counts are honest, contents are not disclosed.** Where records exist that this
audience may not read, the page reports how many. Telling a visitor that three
records exist which they cannot see is the truth; showing them would break the
boundary; showing nothing would be a lie by omission.

The service account behind this surface holds a read-only Firestore role. Even
if a request path here were wrong, it could not append, promote, or publish
anything — `deploy/README.md` carries the matrix of which layer enforces which
row, including the rows IAM cannot express. The one deliberate exception is the
dossier's Reject control, which routes through :class:`ApprovalFlow` (the only
module that may construct promotion events; rejection retracts, it never
promotes) and can only target a claim this audience already reads. Deployed
under the read-only role that append is refused by the store, and the endpoint
reports the refusal honestly instead of pretending the retraction happened.
"""

from __future__ import annotations

import html
import os
import time
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from baraza import telemetry
from baraza.dossier.librarian import Librarian
from baraza.fold.graph import GraphState, fold
from baraza.fold.store import EventStore, open_store
from baraza.interview.approval import ApprovalFlow, ApprovalRequest, Decision
from baraza.llm import LLMClient, open_client
from baraza.reconcile.ledger import DisputedLedger, LedgerRow
from baraza.schema.claim import Claim, Tier
from baraza.schema.temporal import to_epoch_millis, to_iso
from baraza.schema.visibility import Audience, readable_by
from baraza.web import views
from baraza.web.defensive import call_tolerant, resolve_symbol

__all__ = ["app", "create_app", "public_audience"]

SERVICE_NAME = os.environ.get("BARAZA_SERVICE_NAME", "baraza-successor")

# See STATE_TTL_SECONDS in the interview service: the fold is over the whole log
# and this surface can take a burst of simultaneous visitors, so a short cache
# is the difference between one fold and fifty. Longer than the interview's
# because nothing here writes, so there is no read-your-own-write to preserve.
STATE_TTL_SECONDS = 30.0


def public_audience() -> Audience:
    """The audience this service reads as, resolved from configuration.

    Set in ``deploy/service-successor.yaml`` so the value is visible in
    ``gcloud run services describe`` rather than only in code. An unrecognized
    value raises at import time and the container fails to start — it does not
    fall back to a default, because every available default other than the one
    that was intended would widen what a logged-out visitor can read.
    """
    raw = os.environ.get("BARAZA_PUBLIC_AUDIENCE", Audience.PUBLIC.value)
    try:
        return Audience(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"BARAZA_PUBLIC_AUDIENCE={raw!r} is not a known audience. "
            f"Expected one of {[a.value for a in Audience]}. Refusing to start "
            "rather than guessing which side of the boundary to read from."
        ) from exc


AUDIENCE = public_audience()


class _Runtime:
    """Per-instance handles. Read-only; nothing here can append to the log."""

    def __init__(self) -> None:
        self._store: EventStore | None = None
        self._client: LLMClient | None = None
        self._state: GraphState | None = None
        self._state_at: float = 0.0

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
        """Drop the folded state after the one write this surface can make."""
        self._state = None


_runtime = _Runtime()


class AskRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)


# --------------------------------------------------------------- record shapes


def _public_claims(state: GraphState) -> list[Claim]:
    """Committed AND readable by this audience. The only set this service reads.

    ``readable_claims`` applies both axes in the one place they are defined; no
    second filter is written here, because a second filter is a second thing
    that can be wrong.
    """
    return sorted(state.readable_claims(AUDIENCE), key=lambda c: (-c.observed_at, c.claim_id))


def _claim_payload(claim: Claim) -> dict[str, Any]:
    """Render one published claim.

    The quote is read through ``quote_for(audience)``. If the predicate said no
    the value is ``None`` and the caller drops the record — it cannot silently
    become an empty string that renders as a citation with nothing in it.
    """
    quote = claim.quote_for(AUDIENCE)
    return {
        "claim_id": claim.claim_id,
        "digest": claim.digest(),
        "subject": claim.subject_id.removeprefix("ent:").replace("-", " "),
        "predicate": claim.predicate_hint or claim.predicate,
        "asserts": claim.object_for(AUDIENCE),
        "quote": quote,
        "source": claim.anchor.key(),
        "observed_at": claim.observed_at,
        "observed_at_iso": to_iso(claim.observed_at),
        "visibility": claim.visibility.value,
        "tier": claim.tier.value,
    }


def _record_summary(state: GraphState) -> dict[str, Any]:
    """Live counts. Every number here is a query over the folded log.

    Nothing on this page is a literal typed into a template. ``withheld`` is the
    count of committed records this audience may not read — honest as a number,
    undisclosed as content.
    """
    committed = state.committed_claims()
    public = _public_claims(state)
    return {
        "published": len(public),
        "withheld": len(committed) - len(public),
        "events_folded": state.event_count,
        # Labelled, always. A Cloud Scheduler run is never counted as organic
        # activity, so it is reported under its own name and never folded into
        # a general "runs" or "activity" figure.
        "scheduled_reconcile_runs": len(state.heartbeats),
    }


# ------------------------------------------------------------------------ page


def _render_page(state: GraphState) -> str:
    summary = _record_summary(state)
    claims = _public_claims(state)

    if claims:
        cards = "\n".join(_render_card(claim) for claim in claims)
    else:
        cards = (
            '<div class="empty">'
            "<h2>Nothing has been published yet.</h2>"
            "<p>This is not an error and it is not an empty database. Every claim "
            "in this system is created <strong>private</strong>. A claim becomes "
            "visible here only when its owner ratified it "
            "<em>and</em> chose to publish it — two separate decisions, recorded "
            "as two separate events.</p>"
            "<p>Until someone makes both decisions, this page shows nothing. "
            "That is the boundary doing its job.</p>"
            "</div>"
        )

    withheld_note = ""
    if summary["withheld"]:
        withheld_note = (
            f'<p class="withheld">{summary["withheld"]} further record(s) are '
            "committed but not published. They exist; their contents are not "
            "disclosed here, and no logged-out request can reach them.</p>"
        )

    return views.render_record_home(
        summary=summary, cards=cards, withheld_note=withheld_note
    )


def _render_card(claim: Claim) -> str:
    payload = _claim_payload(claim)
    if not payload["quote"]:
        # Unreachable if the predicate and the filter agree — which is exactly
        # why it is checked. A disagreement between them must produce nothing,
        # never a card with an empty citation.
        return ""
    return (
        '<article class="claim">'
        f'<h3>{html.escape(payload["subject"])}'
        f'<span class="pred">{html.escape(payload["predicate"])}</span></h3>'
        f'<blockquote>{html.escape(payload["quote"])}</blockquote>'
        '<footer>'
        f'<span class="src">{html.escape(payload["source"])}</span>'
        f'<span class="dot">·</span>'
        f'<span class="when">{html.escape(payload["observed_at_iso"])}</span>'
        f'<span class="dot">·</span>'
        f'<span class="dig">digest {html.escape(payload["digest"])}</span>'
        '</footer>'
        '</article>'
    )


def _render_ledger_row(row: LedgerRow) -> str:
    """Render an audience-filtered ledger row without reopening its claims.

    ``LedgerRow.rendered`` is the counting-safe projection made by
    ``Contradiction.render_for``.  In particular, a public request never needs
    to look up either side and therefore has no tempting path to a protected
    quote.  A redacted row remains visible as an existence signal, never as a
    disclosure.
    """
    sides = "".join(f"<li>{html.escape(side)}</li>" for side in row.rendered.sides)
    note = ""
    if not row.rendered.fully_readable:
        note = '<p class="withheld">One or more sides are not published.</p>'
    return (
        '<article class="claim">'
        f"<h3>{html.escape(row.contradiction.predicate_hint)}"
        f'<span class="pred">{html.escape(row.stakes_label)}</span></h3>'
        f"<p>{html.escape(row.rendered.summary)}</p>"
        f"<ul>{sides}</ul>"
        f'<footer>{html.escape(row.explain())}</footer>{note}'
        "</article>"
    )


def _render_ledger_page(state: GraphState) -> str:
    """Static, public ledger view promised by BAR-411.

    The ledger is derived from the folded log on every cache refresh, rather
    than being a second mutable store.  It intentionally exposes no action to
    resolve, publish, or alter a claim: this is a read-only judge surface.
    """
    rows = DisputedLedger(state).rows(AUDIENCE)
    cards = "".join(_render_ledger_row(row) for row in rows)
    if not cards:
        cards = (
            '<div class="empty"><h2>No published disputes yet.</h2>'
            '<p>Disputes can be counted without exposing private evidence. '
            'This public view shows only the evidence readable by this audience.</p></div>'
        )
    return views.render_public_shell(
        title="Baraza — disputed ledger",
        heading="The disputed ledger",
        lede="A ranked, read-only view of what the published record disagrees about.",
        body=cards,
        active="ledger",
    )


def _render_agenda_page(state: GraphState) -> str:
    """Render the public-safe agenda preview without invoking a model.

    Generating questions on a public GET would create an unbounded Vertex bill
    and would make a supposedly static surface non-deterministic.  This page
    therefore renders only fully readable ledger items as citation-backed
    prompts.  The owner interview agenda remains generated by the reconciler;
    redacted rows are deliberately not turned into public prompts.
    """
    rows = [row for row in DisputedLedger(state).rows(AUDIENCE) if row.rendered.fully_readable]
    cards = "".join(
        '<article class="claim">'
        f"<h3>Question {index}</h3>"
        f"<p>What should a successor understand about {html.escape(row.contradiction.predicate_hint)} "
        f"for {html.escape(row.contradiction.subject_id.removeprefix('ent:').replace('-', ' '))}?</p>"
        f"<footer>Sources: {html.escape(', '.join(row.source_ids))}</footer>"
        "</article>"
        for index, row in enumerate(rows, start=1)
    )
    if not cards:
        cards = (
            '<div class="empty"><h2>No public agenda items yet.</h2>'
            '<p>Owner-facing questions are generated from the full permitted ledger. '
            'This public preview never derives a question from unpublished evidence.</p></div>'
        )
    return views.render_public_shell(
        title="Baraza — interview agenda",
        heading="The interview agenda",
        lede="Citation-backed public prompts derived from the readable disputed ledger.",
        body=cards,
        active="agenda",
    )




# ------------------------------------------------------- dossier and doctrine


class RejectRequest(BaseModel):
    claim_id: str = Field(min_length=1, max_length=128)


def _belief_rows(state: GraphState) -> list[dict[str, Any]]:
    """The dossier's rows: committed AND readable by this audience, nothing else.

    Same predicate as everything on this surface. ``learned_at`` is rendered as
    ISO for display only; the sort key is the integer instant.
    """
    rows = []
    for claim in _public_claims(state):
        quote = claim.quote_for(AUDIENCE)
        if not quote:
            # Unreachable if the predicate and the filter agree — checked anyway
            # so a disagreement produces a dropped row, never an empty citation.
            continue
        rows.append(
            {
                "claim_id": claim.claim_id,
                "rule": claim.predicate_hint or claim.predicate,
                "quote": quote,
                "anchor": claim.anchor.key(),
                "learned_at_iso": to_iso(claim.observed_at),
                "tier": claim.tier.value,
                "visibility": claim.visibility.value,
            }
        )
    return rows


_DOCTRINE_UNAVAILABLE = (
    "The doctrine compiler (baraza.doctrine) is not present in this build. The "
    "compiled policy exists only where the compiler produced it from ratified "
    "beliefs, with a rule-to-claim provenance map."
)


def _resolve_doctrine(state: GraphState) -> tuple[list[dict[str, Any]] | None, str]:
    """Compile the doctrine via the doctrine lane's module, resolved defensively.

    Returns ``(rules, reason)`` where ``rules`` is ``None`` when the compiler is
    absent or failed — the view renders the reason instead of a substitute
    policy. Each rendered rule's quote is re-read here through
    ``quote_for(AUDIENCE)`` by claim ID: the compiler's output is trusted for
    rule text and provenance IDs, never for what this audience may read.
    """
    compile_fn = resolve_symbol(
        "baraza.doctrine.compiler", "compile_doctrine", "compile_policy", "compile"
    ) or resolve_symbol(
        "baraza.doctrine", "compile_doctrine", "compile_policy", "compile"
    )
    if compile_fn is None:
        return None, _DOCTRINE_UNAVAILABLE
    try:
        doctrine = call_tolerant(
            compile_fn,
            state=state,
            audience=AUDIENCE,
            claims=state.readable_claims(AUDIENCE),
        )
    except Exception as exc:  # noqa: BLE001 — degrade honestly, never invent
        return None, f"the doctrine compiler failed on this fold: {type(exc).__name__}"

    raw_rules = (
        doctrine.get("rules") if isinstance(doctrine, dict) else getattr(doctrine, "rules", None)
    )
    if raw_rules is None:
        return None, (
            "the doctrine compiler returned a shape without rules; nothing is "
            "rendered in its place."
        )

    rules: list[dict[str, Any]] = []
    for raw in raw_rules:
        get = raw.get if isinstance(raw, dict) else lambda k, _r=raw: getattr(_r, k, None)
        claim_id = get("claim_id") or ""
        claim = state.claims.get(claim_id)
        readable = claim is not None and readable_by(claim, AUDIENCE)
        rules.append(
            {
                "text": get("text") or get("rule") or "",
                "claim_id": claim_id,
                "anchor": claim.anchor.key() if claim is not None else (get("anchor") or ""),
                # The boundary decision: quotes come from the fold through the
                # predicate, never from the compiler's payload.
                "quote": claim.quote_for(AUDIENCE) if readable else None,
            }
        )
    return rules, ""


def _resolve_doctrine_diff(state: GraphState) -> dict[str, Any] | None:
    """The diff between the last two doctrine epochs, if the diff lane exists.

    An epoch boundary is the most recent ``session.opened`` event: the old
    doctrine is compiled from everything before it, the new from the full log,
    and the two are handed to the doctrine lane's ``diff``. ``None`` means "no
    diff available" — module absent, no epoch boundary yet, or a failure — and
    the view says so rather than inventing an empty diff.
    """
    diff_fn = resolve_symbol(
        "baraza.doctrine.diff", "diff_last_epochs", "latest_diff", "doctrine_diff", "diff"
    )
    compile_fn = resolve_symbol(
        "baraza.doctrine.compiler", "compile_doctrine", "compile_policy", "compile"
    )
    if diff_fn is None or compile_fn is None:
        return None
    try:
        events = _runtime.store.read_all()
        boundaries = [
            e.order_key
            for e in events
            if e.event_type.value == "session.opened"
        ]
        if not boundaries:
            return None
        boundary = max(boundaries)
        old_state = fold(e for e in events if e.order_key < boundary)
        old_doc = call_tolerant(compile_fn, state=old_state, audience=AUDIENCE)
        new_doc = call_tolerant(compile_fn, state=state, audience=AUDIENCE)
        result = diff_fn(old_doc, new_doc)
    except Exception:  # noqa: BLE001 — degrade to "no diff", never to a made-up one
        return None
    if result is None:
        return None

    def _entry(item: Any) -> dict[str, Any]:
        """Project one diff entry: its own cited rendering plus the causal claim."""
        render = getattr(item, "render", None)
        rule = getattr(item, "rule", None) or getattr(item, "new", None)
        return {
            "text": render() if callable(render) else str(item),
            "claim_id": getattr(item, "causal_claim_id", "")
            or getattr(rule, "claim_id", ""),
        }

    return {
        "added": [_entry(i) for i in (getattr(result, "added", None) or [])],
        "removed": [_entry(i) for i in (getattr(result, "removed", None) or [])],
        "changed": [_entry(i) for i in (getattr(result, "changed", None) or [])],
    }


# ------------------------------------------------------------------------ app


@asynccontextmanager
async def _lifespan(_: FastAPI):
    telemetry.configure(SERVICE_NAME)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Baraza — successor service",
        version="0.1.0",
        lifespan=_lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @application.get("/healthz")
    def healthz() -> dict[str, Any]:
        """Liveness. No I/O — see the interview service for why."""
        return {
            "status": "ok",
            "service": SERVICE_NAME,
            "audience": AUDIENCE.value,
            "tracing": telemetry.exporter_status(),
        }

    @application.get("/readyz")
    def readyz() -> dict[str, Any]:
        try:
            state = _runtime.state()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"store unreachable: {exc}") from exc
        return {"status": "ok", **_record_summary(state)}

    @application.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        with telemetry.span("successor.page") as active:
            state = _runtime.state()
            summary = _record_summary(state)
            telemetry.record_audience(active, AUDIENCE, withheld=summary["withheld"])
            active.set_attribute("baraza.published_count", summary["published"])
            body = _render_page(state)
        return HTMLResponse(body)

    @application.get("/dossier", response_class=HTMLResponse)
    def dossier() -> HTMLResponse:
        """Every belief the agent holds that this audience may read.

        The public-demo surface. Readable logged out; every row passed the
        ``readable_by(Audience.PUBLIC)`` predicate, the withheld count is a live
        query, and the empty state names the boundary as the reason — an empty
        dossier is the private-by-default default working, not a broken page.
        """
        with telemetry.span("dossier.page") as active:
            state = _runtime.state()
            summary = _record_summary(state)
            telemetry.record_audience(active, AUDIENCE, withheld=summary["withheld"])
            body = views.render_dossier_view(
                beliefs=_belief_rows(state),
                withheld=summary["withheld"],
                can_reject=True,
            )
        return HTMLResponse(body)

    @application.get("/api/dossier")
    def dossier_json() -> dict[str, Any]:
        """The dossier as JSON, for polling. Same rows, same predicate."""
        state = _runtime.state()
        summary = _record_summary(state)
        return {
            "audience": AUDIENCE.value,
            "beliefs": _belief_rows(state),
            "withheld": summary["withheld"],
        }

    @application.post("/api/dossier/reject")
    def dossier_reject(body: RejectRequest) -> dict[str, Any]:
        """Retract one belief. Appends ``claim.rejected`` via the approval flow.

        Two boundaries hold here. Target: only a claim this audience already
        reads can be rejected from this surface — a logged-out request must not
        be able to probe or retract records it cannot see, so an unreadable
        claim answers exactly like a nonexistent one. Mechanism: the retraction
        is an ``ApprovalFlow`` rejection, so this module still constructs no
        promotion event of any kind.
        """
        state = _runtime.state(force=True)
        claim = state.claims.get(body.claim_id)
        if claim is None or claim.tier is not Tier.COMMITTED or not readable_by(claim, AUDIENCE):
            raise HTTPException(status_code=404, detail="no such belief on this surface")

        occurred_at = to_epoch_millis(time.time(), field="dossier.reject")
        try:
            result = ApprovalFlow(_runtime.store).submit(
                [
                    ApprovalRequest(
                        claim=claim,
                        decision=Decision.REJECT,
                        approver_id="dossier-owner",
                        note="rejected from the dossier view",
                    )
                ],
                occurred_at=occurred_at,
            )
        except Exception as exc:  # noqa: BLE001 — a refused append is reported, not masked
            raise HTTPException(
                status_code=503,
                detail=(
                    "the event store refused the append, so the retraction did "
                    "NOT happen. Deployed, this surface holds read-only "
                    "credentials; retract from the owner console instead."
                ),
            ) from exc
        _runtime.invalidate()
        return {
            "rejected": result.rejected,
            "events_appended": result.events_appended,
        }

    @application.get("/doctrine", response_class=HTMLResponse)
    def doctrine() -> HTMLResponse:
        """The compiled operating policy — same doctrine, every rule cited.

        Rule text and provenance IDs come from the doctrine lane's compiler,
        resolved defensively; every rendered quote is re-read from the fold
        through ``quote_for(AUDIENCE)``. When the compiler or diff module is
        absent, the page says so instead of substituting a policy.
        """
        state = _runtime.state()
        rules, reason = _resolve_doctrine(state)
        diff = _resolve_doctrine_diff(state)
        return HTMLResponse(
            views.render_doctrine_view(
                rules=rules, diff=diff, unavailable_reason=reason
            )
        )

    @application.get("/ledger", response_class=HTMLResponse)
    def ledger() -> HTMLResponse:
        """Read-only, audience-redacted ledger for the hosted judge surface."""
        state = _runtime.state()
        return HTMLResponse(_render_ledger_page(state))

    @application.get("/agenda", response_class=HTMLResponse)
    def agenda() -> HTMLResponse:
        """Read-only public agenda preview; no public request invokes Vertex."""
        state = _runtime.state()
        return HTMLResponse(_render_agenda_page(state))

    @application.get("/api/record")
    def record() -> dict[str, Any]:
        """The published record as JSON. Same set as the page, same predicate."""
        with telemetry.span("successor.record") as active:
            state = _runtime.state()
            claims = _public_claims(state)
            telemetry.record_claims(active, claims)
            summary = _record_summary(state)
            telemetry.record_audience(active, AUDIENCE, withheld=summary["withheld"])
        return {
            "audience": AUDIENCE.value,
            "summary": summary,
            "claims": [
                payload
                for payload in (_claim_payload(c) for c in claims)
                if payload["quote"]
            ],
        }

    @application.post("/api/ask")
    def ask(body: AskRequest) -> dict[str, Any]:
        """Successor-mode question answering, bounded to the published record."""
        with telemetry.span(
            "successor.ask", **{"baraza.question_length": len(body.question)}
        ) as active:
            state = _runtime.state()
            librarian = Librarian(_runtime.client, state, audience=AUDIENCE)
            answer = librarian.ask(body.question)

            active.set_attribute("baraza.refused", answer.refused)
            active.set_attribute("baraza.refusal_reason", answer.refusal_reason)
            active.set_attribute("baraza.considered", answer.considered)
            active.set_attribute("baraza.readable", answer.readable)
            # Citation identity travels as digests; the quoted text does not
            # enter the trace even though it is public on this surface. The rule
            # is per-mechanism, not per-audience — a trace that carries quotes
            # for public claims is a trace that will carry them for private ones
            # the day somebody reuses the helper.
            active.set_attribute(
                "baraza.citation_ids", [c.claim_id for c in answer.citations]
            )
            telemetry.record_audience(active, AUDIENCE, withheld=answer.withheld)

        return {
            "answer": answer.text,
            "refused": answer.refused,
            "refusal_reason": answer.refusal_reason,
            "withheld": answer.withheld,
            "citations": [
                {"claim_id": c.claim_id, "anchor": c.anchor, "quote": c.quote}
                for c in answer.citations
            ],
        }

    return application


app = create_app()
