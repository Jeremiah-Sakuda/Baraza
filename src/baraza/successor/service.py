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
row, including the rows IAM cannot express.
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
from baraza.fold.graph import GraphState, fold
from baraza.fold.store import EventStore, open_store
from baraza.llm import LLMClient, open_client
from baraza.schema.claim import Claim
from baraza.schema.temporal import to_iso
from baraza.schema.visibility import Audience
from baraza.successor.librarian import Librarian

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

    def state(self) -> GraphState:
        if self._state is None or (time.monotonic() - self._state_at) > STATE_TTL_SECONDS:
            self._state = fold(self.store.read_all())
            self._state_at = time.monotonic()
        return self._state


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
            "visible here only when a departing officer approved it "
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

    return _PAGE.format(
        published=summary["published"],
        withheld_note=withheld_note,
        events=summary["events_folded"],
        scheduled=summary["scheduled_reconcile_runs"],
        cards=cards,
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


# Self-contained: no external stylesheet, script, or font. A public page that
# fetches from a CDN is a public page whose contents depend on a third party
# being up and honest.
_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Baraza — the published record</title>
<style>
  :root {{ color-scheme: light dark; --fg:#11150f; --bg:#fbfaf6; --mut:#5d6355;
           --line:#dcd9cd; --card:#ffffff; --accent:#3f6212; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg:#e9ece3; --bg:#12140f; --mut:#9aa290; --line:#2a2e24;
             --card:#191c15; --accent:#a3c25c; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; padding:2rem 1.25rem 4rem; background:var(--bg); color:var(--fg);
         font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  main {{ max-width:52rem; margin:0 auto; }}
  h1 {{ font-size:1.6rem; margin:0 0 .25rem; letter-spacing:-.01em; }}
  .lede {{ color:var(--mut); margin:0 0 2rem; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:1.5rem; padding:1rem 0;
           border-top:1px solid var(--line); border-bottom:1px solid var(--line);
           margin-bottom:2rem; }}
  .stat b {{ display:block; font-size:1.5rem; font-weight:600; }}
  .stat span {{ color:var(--mut); font-size:.8rem; text-transform:uppercase;
               letter-spacing:.06em; }}
  .claim {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
           padding:1rem 1.15rem; margin-bottom:1rem; }}
  .claim h3 {{ margin:0 0 .5rem; font-size:1rem; font-weight:600; }}
  .pred {{ color:var(--mut); font-weight:400; margin-left:.5rem; }}
  blockquote {{ margin:0 0 .75rem; padding-left:.9rem; border-left:3px solid var(--accent); }}
  footer {{ color:var(--mut); font-size:.78rem; font-family:ui-monospace,SFMono-Regular,monospace; }}
  .dot {{ margin:0 .4rem; }}
  .empty {{ border:1px dashed var(--line); border-radius:10px; padding:1.5rem; }}
  .empty h2 {{ margin-top:0; font-size:1.05rem; }}
  .withheld {{ color:var(--mut); font-size:.9rem; }}
  form {{ display:flex; gap:.5rem; margin:2.5rem 0 1rem; }}
  input {{ flex:1; padding:.7rem .85rem; border-radius:8px; border:1px solid var(--line);
          background:var(--card); color:var(--fg); font:inherit; }}
  button {{ padding:.7rem 1.1rem; border-radius:8px; border:1px solid var(--accent);
           background:var(--accent); color:var(--bg); font:inherit; cursor:pointer; }}
  #answer {{ white-space:pre-wrap; }}
  .note {{ color:var(--mut); font-size:.85rem; border-top:1px solid var(--line);
          margin-top:3rem; padding-top:1rem; }}
</style></head><body><main>

<h1>The published record</h1>
<p class="lede">Everything below was approved by a departing officer and
explicitly published by them. Nothing here was published by default.</p>

<div class="stats">
  <div class="stat"><b>{published}</b><span>published records</span></div>
  <div class="stat"><b>{events}</b><span>events folded</span></div>
  <div class="stat"><b>{scheduled}</b><span>scheduled reconcile runs</span></div>
</div>

{cards}
{withheld_note}

<form id="ask" autocomplete="off">
  <input id="q" name="q" placeholder="Ask the record a question" aria-label="Ask the record a question">
  <button type="submit">Ask</button>
</form>
<div id="answer"></div>

<p class="note">Counts are live queries over the append-only event log, not
values typed into this page. &ldquo;Scheduled reconcile runs&rdquo; counts Cloud
Scheduler runs and only those; a scheduled job is never counted as organic
activity. Answers are drawn only from the published records above, with a
citation for every sentence &mdash; when the record cannot support an answer,
this surface says so and stops rather than guessing.</p>

<script>
document.getElementById('ask').addEventListener('submit', async function (e) {{
  e.preventDefault();
  var out = document.getElementById('answer');
  var q = document.getElementById('q').value.trim();
  if (!q) return;
  out.textContent = 'Reading the record\\u2026';
  try {{
    var r = await fetch('/api/ask', {{
      method: 'POST',
      headers: {{ 'Content-Type': 'application/json' }},
      body: JSON.stringify({{ question: q }})
    }});
    var d = await r.json();
    var lines = [d.answer];
    if (d.citations && d.citations.length) {{
      lines.push('');
      lines.push('Sources:');
      d.citations.forEach(function (c) {{ lines.push('  [' + c.anchor + '] "' + c.quote + '"'); }});
    }}
    if (d.withheld) {{
      lines.push('');
      lines.push('(' + d.withheld + ' further record(s) match but are not published.)');
    }}
    out.textContent = lines.join('\\n');
  }} catch (err) {{
    out.textContent = 'The record could not be reached.';
  }}
}});
</script>
</main></body></html>"""


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
