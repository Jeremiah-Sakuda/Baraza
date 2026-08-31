"""HTML rendering for every web surface. Pure functions, plain data in.

Each ``render_*`` function takes primitives (strings, ints, dicts already
projected by the service layer) and returns a complete page. No function here
touches the event store, an LLM client, or a ``Claim`` object, the service
layer decides *what* may be shown (that is where ``readable_by`` runs), this
module only decides *how*. Keeping the boundary decision out of the templates
means a template change can never widen what an audience reads.

Every user-supplied string is escaped at the render site. A quote is testimony
from a person's own mouth and must never become markup.
"""

from __future__ import annotations

import html
import json
from typing import Any

__all__ = [
    "render_session_index",
    "render_session_view",
    "render_divergence_card",
    "render_dossier_view",
    "render_doctrine_view",
    "render_approval_queue",
    "render_judge_tour",
    "WITHHELD_PLACEHOLDER",
]

WITHHELD_PLACEHOLDER = "[a record exists here that this audience may not read]"
"""Rendered wherever a rule or belief exists but its quote is not readable by
the requesting audience. Existence is honest to disclose; contents are not."""


def _e(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


# -------------------------------------------------------------------- the shell

_STYLE = """
  * { box-sizing: border-box; }
  :root {
    --fg:#191817; --bg:#faf9f6; --mut:#67655e; --line:#e4e1d8;
    --card:#ffffff; --accent:#166534; --accent-ink:#0c4a26;
    --accent-soft:#e8f3ea; --hero-grad:linear-gradient(160deg,#f2f7f0,#faf9f6 55%);
    --warn:#92400e; --warn-soft:#fef3e2; --warn-line:#f0d5a8;
    --danger:#9f1239; --mono:ui-monospace,SFMono-Regular,Menlo,monospace;
    --serif:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --fg:#eceae4; --bg:#141311; --mut:#9d9a90; --line:#2b2a25;
      --card:#1c1b18; --accent:#5fb87a; --accent-ink:#8ed2a2;
      --accent-soft:#1d2b20; --hero-grad:linear-gradient(160deg,#181d17,#141311 55%);
      --warn:#f0b467; --warn-soft:#2b2116; --warn-line:#4a3a22;
      --danger:#f27698;
    }
  }
  body { margin:0; background:var(--bg); color:var(--fg);
         font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif;
         -webkit-font-smoothing:antialiased; }
  header.site { border-bottom:1px solid var(--line); background:var(--card);
                position:sticky; top:0; z-index:5; }
  header.site .inner { max-width:70rem; margin:0 auto; padding:.85rem 1.5rem;
                       display:flex; align-items:baseline; gap:1.5rem; flex-wrap:wrap; }
  header.site .wordmark { font-weight:800; font-size:1.05rem; letter-spacing:-.02em; }
  header.site .wordmark small { color:var(--mut); font-weight:400; margin-left:.55rem;
                                font-size:.8rem; }
  nav a { color:var(--mut); text-decoration:none; margin-right:1.1rem; font-size:.92rem; }
  nav a:hover { color:var(--fg); }
  nav a.active { color:var(--fg); font-weight:600; border-bottom:2px solid var(--accent); }
  main { max-width:70rem; margin:0 auto; padding:1.5rem 1.5rem 4.5rem; }
  h1 { font-size:1.5rem; margin:.25rem 0; letter-spacing:-.015em; }
  .lede { color:var(--mut); margin:0 0 1.5rem; max-width:46rem; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:1rem 1.15rem; margin-bottom:1rem; }
  .empty { border:1px dashed var(--line); border-radius:10px; padding:1.5rem;
           background:transparent; }
  .empty h2 { margin-top:0; font-size:1.05rem; }
  .prov { color:var(--mut); font-size:.78rem; font-family:var(--mono); }
  .prov .dot { margin:0 .4rem; }
  blockquote { margin:.4rem 0 .6rem; padding-left:.9rem;
               border-left:3px solid var(--accent); }
  .tag { display:inline-block; font-size:.72rem; text-transform:uppercase;
         letter-spacing:.06em; padding:.1rem .5rem; border-radius:99px;
         border:1px solid var(--line); color:var(--mut); }
  .tag.committed { border-color:var(--accent); color:var(--accent);
                   background:var(--accent-soft); }
  .tag.pending { border-color:var(--warn-line); color:var(--warn);
                 background:var(--warn-soft); }
  button, .btn { font:inherit; font-size:.9rem; padding:.45rem .9rem;
                 border-radius:8px; border:1px solid var(--line);
                 background:var(--card); color:var(--fg); cursor:pointer; }
  button.primary { background:var(--accent); border-color:var(--accent); color:#fff; }
  button.quiet { color:var(--mut); }
  button.danger { color:var(--danger); border-color:var(--danger); background:#fff; }
  input[type=text], textarea, select {
    font:inherit; padding:.55rem .7rem; border:1px solid var(--line);
    border-radius:8px; background:var(--card); color:var(--fg); }
  .withheld-line { color:var(--mut); font-size:.9rem; border-top:1px solid var(--line);
                   margin-top:1.5rem; padding-top:1rem; }
  .honest { color:var(--mut); font-size:.85rem; }

  /* session layout */
  .session-grid { display:grid; grid-template-columns:minmax(0,1fr) 17rem; gap:1.25rem; }
  @media (max-width:52rem){ .session-grid { grid-template-columns:1fr; } }
  .chat { display:flex; flex-direction:column; gap:.6rem; }
  .turn { max-width:88%; padding:.6rem .85rem; border-radius:12px;
          border:1px solid var(--line); background:var(--card); }
  .turn.partner { align-self:flex-end; background:var(--accent-soft);
                  border-color:var(--accent); }
  .turn .meta { color:var(--mut); font-size:.72rem; font-family:var(--mono);
                margin-top:.3rem; }
  .composer { display:flex; gap:.5rem; margin-top:1rem; }
  .composer textarea { flex:1; min-height:3.2rem; resize:vertical; }
  aside.agenda { font-size:.92rem; }
  aside.agenda h2 { font-size:.8rem; text-transform:uppercase; letter-spacing:.06em;
                    color:var(--mut); margin:0 0 .6rem; }
  .agenda-item { border:1px solid var(--line); border-radius:8px; background:var(--card);
                 padding:.55rem .7rem; margin-bottom:.5rem; display:flex; gap:.55rem; }
  .agenda-item.retired { opacity:.62; }
  .agenda-item .tick { color:var(--accent); font-weight:700; }
  .agenda-item .open-mark { color:var(--mut); }
  .agenda-item .why { color:var(--mut); font-size:.8rem; display:block; margin-top:.2rem; }

  /* the divergence card */
  .divergence { border:2px solid var(--warn-line); background:var(--warn-soft);
                border-radius:12px; padding:1.1rem 1.25rem; margin:1rem 0; }
  .divergence h2 { margin:0 0 .3rem; font-size:1.05rem; color:var(--warn); }
  .divergence .sides { display:grid; grid-template-columns:1fr 1fr; gap:1rem;
                       margin:.8rem 0; }
  @media (max-width:44rem){ .divergence .sides { grid-template-columns:1fr; } }
  .divergence .side { background:var(--card); border:1px solid var(--warn-line);
                      border-radius:8px; padding:.7rem .85rem; }
  .divergence .side h3 { margin:0 0 .35rem; font-size:.8rem; text-transform:uppercase;
                         letter-spacing:.06em; color:var(--mut); }
  .divergence .actions { display:flex; gap:.6rem; flex-wrap:wrap; margin-top:.6rem; }
  .divergence .conditional { display:none; margin-top:.6rem; }
  .divergence .conditional.open { display:block; }
  .divergence .conditional textarea { width:100%; min-height:3rem; }

  /* doctrine */
  .rule { border-left:3px solid var(--accent); }
  .rule .rule-text { font-weight:600; }
  .diff-panel h2 { font-size:1rem; }
  .diff-added { color:var(--accent); }
  .diff-removed { color:var(--danger); text-decoration:line-through; }

  /* landing */
  .hero { background:var(--hero-grad); border-bottom:1px solid var(--line);
          margin:-1.5rem -1.5rem 0; padding:4.25rem 1.5rem 3.5rem; }
  .hero .wrap { max-width:70rem; margin:0 auto; }
  .hero h1 { font-family:var(--serif); font-weight:600; letter-spacing:-.02em;
             font-size:clamp(2rem,4.6vw,3.15rem); line-height:1.12;
             margin:0 0 1rem; max-width:44rem; }
  .hero p.sub { font-size:1.12rem; color:var(--mut); max-width:40rem;
                margin:0 0 1.75rem; }
  .cta-row { display:flex; gap:.8rem; flex-wrap:wrap; }
  a.btn { display:inline-block; text-decoration:none; border-radius:10px;
          padding:.7rem 1.2rem; font-weight:600; font-size:.95rem; }
  a.btn.solid { background:var(--accent); color:#fff; }
  a.btn.solid:hover { background:var(--accent-ink); }
  @media (prefers-color-scheme: dark) { a.btn.solid { color:#0c130e; } }
  a.btn.ghost { border:1px solid var(--line); color:var(--fg); background:var(--card); }
  a.btn.ghost:hover { border-color:var(--accent); }
  .trust { color:var(--mut); font-size:.85rem; margin-top:1.4rem; }
  section.land { padding:3rem 0 0; }
  section.land h2 { font-family:var(--serif); font-weight:600; font-size:1.65rem;
                    letter-spacing:-.015em; margin:0 0 .4rem; }
  section.land > p.section-sub { color:var(--mut); max-width:44rem; margin:0 0 1.5rem; }
  .steps { display:grid; grid-template-columns:repeat(auto-fit,minmax(15rem,1fr));
           gap:1rem; }
  .step { background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:1.2rem 1.25rem; }
  .step .num { display:inline-flex; width:1.7rem; height:1.7rem; border-radius:50%;
               background:var(--accent-soft); color:var(--accent-ink);
               align-items:center; justify-content:center; font-weight:700;
               font-size:.9rem; margin-bottom:.6rem; }
  .step h3 { margin:.1rem 0 .4rem; font-size:1.02rem; }
  .step p { margin:0; color:var(--mut); font-size:.94rem; }
  .step .eg { margin-top:.7rem; border-left:3px solid var(--accent);
              background:var(--accent-soft); border-radius:0 8px 8px 0;
              padding:.5rem .7rem; font-size:.86rem; color:var(--fg); }
  .surfaces { display:grid; grid-template-columns:repeat(auto-fit,minmax(14rem,1fr));
              gap:1rem; }
  a.surface { display:block; text-decoration:none; color:inherit;
              background:var(--card); border:1px solid var(--line);
              border-radius:14px; padding:1.1rem 1.2rem; }
  a.surface:hover { border-color:var(--accent); }
  a.surface h3 { margin:0 0 .35rem; font-size:1rem; color:var(--accent-ink); }
  a.surface p { margin:0; color:var(--mut); font-size:.92rem; }
  .live-strip { display:flex; gap:2.25rem; flex-wrap:wrap; align-items:baseline;
                border-top:1px solid var(--line); border-bottom:1px solid var(--line);
                margin-top:3rem; padding:1.1rem 0; }
  .live-strip .stat b { font-size:1.35rem; letter-spacing:-.02em; margin-right:.4rem; }
  .live-strip .stat span { color:var(--mut); font-size:.88rem; }
  .live-strip .note { color:var(--mut); font-size:.8rem; flex-basis:100%; }
  footer.land { margin-top:3.5rem; color:var(--mut); font-size:.88rem; }
  footer.land a { color:var(--accent-ink); }

  /* judge tour */
  .stop { display:grid; grid-template-columns:2.4rem 1fr; gap:1rem;
          background:var(--card); border:1px solid var(--line); border-radius:14px;
          padding:1.2rem 1.25rem; margin:0 0 1rem; }
  .stop .num { width:2rem; height:2rem; border-radius:50%; background:var(--accent-soft);
               color:var(--accent-ink); display:flex; align-items:center;
               justify-content:center; font-weight:700; }
  .stop h3 { margin:.15rem 0 .4rem; }
  .stop h3 a { color:var(--accent-ink); }
  .stop p { margin:.2rem 0; color:var(--mut); }
  .stop .look { margin-top:.5rem; font-size:.9rem; color:var(--fg); }
  .stop .look b { color:var(--accent-ink); }

  /* record home */

  .stats { display:flex; gap:1rem; flex-wrap:wrap; margin:1rem 0 .25rem; }
  .stat { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:.8rem 1.1rem; min-width:9rem; }
  .stat b { display:block; font-size:1.5rem; letter-spacing:-.02em; }
  .stat span { color:var(--mut); font-size:.85rem; }
  .walkthrough { background:var(--card); border:1px solid var(--line);
                 border-radius:12px; padding:1rem 1.25rem; margin:1.25rem 0; }
  .walkthrough h2 { margin:.1rem 0 .5rem; font-size:1.05rem; }
  .tour { margin:.5rem 0; padding-left:1.2rem; }
  .tour li { margin:.35rem 0; }
  .tour a { font-weight:600; }
  h2.section { margin-top:1.75rem; font-size:1.1rem; }

  /* approval queue */
  .queue-item { display:grid; gap:.5rem; }
  .queue-controls { display:flex; gap:1rem; flex-wrap:wrap; align-items:center;
                    font-size:.9rem; }
"""


def _page(
    *,
    title: str,
    heading: str,
    lede: str,
    body: str,
    nav: list[tuple[str, str, bool]],
    wordmark_note: str,
    script: str = "",
) -> str:
    active_attr = ' class="active"'
    nav_html = "".join(
        f'<a href="{_e(href)}"{active_attr if active else ""}>{_e(label)}</a>'
        for href, label, active in nav
    )
    return (
        "<!doctype html>\n"
        '<html lang="en"><head><meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_e(title)}</title>\n<style>{_STYLE}</style></head><body>\n"
        '<header class="site"><div class="inner">'
        f'<span class="wordmark">Baraza<small>{_e(wordmark_note)}</small></span>'
        f"<nav>{nav_html}</nav></div></header>\n<main>\n"
        f"<h1>{_e(heading)}</h1>\n<p class=\"lede\">{_e(lede)}</p>\n"
        f"{body}\n</main>\n{script}\n</body></html>"
    )


PUBLIC_BASE_ENV = "BARAZA_PUBLIC_BASE_URL"


def _owner_nav(active: str) -> list[tuple[str, str, bool]]:
    """Owner console tabs, plus outbound links to the public product.

    The two surfaces are separate deployments, so without these links the
    operator has to remember a second URL mid-session. The public base comes
    from the environment because localhost must not hardcode a .run.app host.
    """
    import os

    tabs = [
        ("/", "Sessions", active == "sessions"),
        ("/approvals", "Approval queue", active == "approvals"),
    ]
    base = os.environ.get(PUBLIC_BASE_ENV, "").rstrip("/")
    if base:
        tabs.extend(
            [
                (f"{base}/dossier", "Dossier ↗", False),
                (f"{base}/doctrine", "Doctrine ↗", False),
            ]
        )
    return tabs


def _public_nav(active: str) -> list[tuple[str, str, bool]]:
    return [
        ("/", "Home", active == "record"),
        ("/tour", "Tour", active == "tour"),
        ("/dossier", "Dossier", active == "dossier"),
        ("/doctrine", "Doctrine", active == "doctrine"),
        ("/ledger", "Ledger", active == "ledger"),
        ("/agenda", "Agenda", active == "agenda"),
    ]




def render_public_shell(
    *,
    title: str,
    heading: str,
    lede: str,
    body: str,
    active: str,
) -> str:
    """Wrap a public page body in the one shared shell.

    Exists because the site briefly shipped with two rendering systems: the
    dossier and doctrine views used this module's header and tabs while the
    record, ledger, and agenda pages carried their own inline HTML with no
    navigation at all. A judge clicking through saw two different products.
    Every public page now goes through here, so a missing tab is a code review
    comment rather than a discovery.
    """
    return _page(
        title=title,
        heading=heading,
        lede=lede,
        body=body,
        nav=_public_nav(active),
        wordmark_note="the published record",
    )


def render_record_home(
    *,
    summary: dict[str, Any],
    cards: str,
    withheld_note: str,
) -> str:
    """The landing page. Written for a visitor with zero context.

    The test this page is built against: someone who has never heard of the
    project reads the hero and the four steps and can say what the product
    does. Product vocabulary (claim, doctrine, fold) is introduced only after
    the plain-language version of the same idea, never instead of it.

    Every number in the live strip remains a query over the folded log. The
    published record itself moves to the bottom: a stranger needs the story
    before the data.
    """
    hero = (
        '<div class="hero"><div class="wrap">'
        "<h1>Your AI assistant is learning about you. "
        "Baraza shows you the file.</h1>"
        '<p class="sub">Baraza is an AI working partner that keeps an open, '
        "auditable record of everything it believes about you: your exact "
        "words, the moment you said them, and the rule it derived. It asks "
        "before any belief takes effect, and it tells you when you contradict "
        "yourself.</p>"
        '<div class="cta-row">'
        '<a class="btn solid" href="/tour">Take the two-minute tour</a>'
        '<a class="btn ghost" href="/dossier">See the live file</a>'
        "</div>"
        '<p class="trust">Live deployment. Every count on this page is a real '
        "query against the production database, and this page works without "
        "an account.</p>"
        "</div></div>"
    )

    steps = (
        '<section class="land"><h2>How it works</h2>'
        '<p class="section-sub">Four ideas, in the order they happen.</p>'
        '<div class="steps">'
        '<div class="step"><span class="num">1</span>'
        "<h3>It takes notes in your own words</h3>"
        "<p>When you tell it how you want things done, it stores your exact "
        "sentence with a timestamp, not a paraphrase. Each note is called a "
        "claim.</p>"
        '<div class="eg">"Never state a dollar figure without citing the '
        'document it came from." Saved verbatim, anchored to the moment.</div>'
        "</div>"
        '<div class="step"><span class="num">2</span>'
        "<h3>It catches you contradicting yourself</h3>"
        "<p>Tell it two things that cannot both be true and it stops, shows "
        "you both of your own quotes, and asks which one governs. It never "
        "silently keeps the newer one.</p>"
        "</div>"
        '<div class="step"><span class="num">3</span>'
        "<h3>Nothing acts until you approve it</h3>"
        "<p>Beliefs sit in a queue until you ratify them. Approved beliefs "
        "compile into the working policy it follows, called the doctrine, "
        "where every rule cites the sentence that created it.</p>"
        "</div>"
        '<div class="step"><span class="num">4</span>'
        "<h3>The record cannot be quietly rewritten</h3>"
        "<p>Everything lives in an append-only log whose database rules "
        "reject edits and deletes. Corrections are new entries. Rejecting a "
        "belief is itself recorded, and the next session provably runs "
        "without it.</p>"
        "</div></div></section>"
    )

    surfaces = (
        '<section class="land"><h2>Explore the live product</h2>'
        '<p class="section-sub">Four views over one append-only record. What '
        "you can read here is what the owner chose to publish; everything "
        "else shows up as an honest count, never as content.</p>"
        '<div class="surfaces">'
        '<a class="surface" href="/dossier"><h3>The dossier</h3>'
        "<p>The file it keeps on its user. Each published belief with its "
        "verbatim quote and anchor.</p></a>"
        '<a class="surface" href="/doctrine"><h3>The doctrine</h3>'
        "<p>Beliefs compiled into working policy. Every rule cites its "
        "source sentence.</p></a>"
        '<a class="surface" href="/ledger"><h3>The ledger</h3>'
        "<p>What the record disagrees with itself about, ranked by stakes.</p></a>"
        '<a class="surface" href="/agenda"><h3>The agenda</h3>'
        "<p>The questions those disagreements raise. The agent opens its "
        "sessions with these; no human writes them.</p></a>"
        "</div></section>"
    )

    live = (
        '<div class="live-strip">'
        f'<span class="stat"><b>{summary["published"]}</b>'
        "<span>published beliefs</span></span>"
        f'<span class="stat"><b>{summary["events_folded"]}</b>'
        "<span>events in the log</span></span>"
        f'<span class="stat"><b>{summary["scheduled_reconcile_runs"]}</b>'
        "<span>scheduled nightly runs</span></span>"
        '<span class="note">Live queries over the append-only event log, not '
        "numbers typed into this page. Scheduled runs counts Cloud Scheduler "
        "runs and only those; automation is never passed off as activity."
        "</span></div>"
    )

    record = (
        '<section class="land"><h2>The published record</h2>'
        '<p class="section-sub">Everything below was ratified by its owner '
        "and explicitly published, two separate decisions recorded as two "
        "separate events. Private is the default.</p>"
        + withheld_note
        + cards
        + "</section>"
    )

    footer = (
        '<footer class="land"><p>Baraza means council: the place where '
        "disputes are heard and settled on the record. The dispute this one "
        "hears is you versus you.</p>"
        '<p>Built for the All Things Agentic hackathon. '
        '<a href="https://github.com/Jeremiah-Sakuda/Baraza">Source and '
        "architecture on GitHub</a>. Runs on Google Cloud: Cloud Run, "
        "Firestore, Cloud Scheduler, and Gemini through Vertex AI.</p></footer>"
    )

    return _page(
        title="Baraza: an AI partner you can audit",
        heading="",
        lede="",
        body=hero + steps + surfaces + live + record + footer,
        nav=_public_nav("record"),
        wordmark_note="memory with due process",
    )


def render_judge_tour() -> str:
    """A guided path for a first-time visitor, judges especially.

    Static by design: the tour must cost nothing, work logged out, and never
    invoke a model on a public GET. Each stop says what to open and exactly
    what to look for, so the product's properties are checkable rather than
    asserted.
    """
    stops = [
        (
            "/dossier",
            "Open the dossier",
            "This is the file the agent keeps on its user. Each entry is a "
            "belief with the user's verbatim sentence and an anchor to the "
            "turn where it was said.",
            "Every quote has an anchor like turn:t-4 and a timestamp. Note "
            "the withheld count near the top: beliefs that exist but were "
            "not published are counted honestly, never shown.",
        ),
        (
            "/doctrine",
            "Read the doctrine",
            "Approved beliefs compile into the working policy the agent "
            "actually runs under.",
            "Each rule carries the claim it came from. There is no rule "
            "without a source sentence, and conflicting approved rules are "
            "excluded with a notice rather than silently resolved.",
        ),
        (
            "/ledger",
            "Check the ledger",
            "Before the agent asks its user anything, it finds what the "
            "record disagrees with itself about.",
            "Rows are ranked by stakes. Where the evidence is unpublished, "
            "the disagreement is still counted, and the page says so instead "
            "of leaking it.",
        ),
        (
            "/agenda",
            "See the agenda",
            "The disagreements become the questions the agent leads its next "
            "session with. No human writes these.",
            "Each question names its sources. When a question is answered "
            "and approved, it retires itself and never comes back.",
        ),
        (
            "/",
            "Verify the live counts",
            "Back on the home page, the strip above the published record "
            "shows the system's own accounting.",
            "The scheduled-runs figure counts Cloud Scheduler executions and "
            "nothing else. This product treats honest counting as a feature; "
            "the address bar you are looking at is the production Cloud Run "
            "URL.",
        ),
    ]
    body = "".join(
        '<div class="stop">'
        f'<span class="num">{index}</span><div>'
        f'<h3><a href="{_e(href)}">{_e(title)}</a></h3>'
        f"<p>{_e(what)}</p>"
        f'<p class="look"><b>Look for:</b> {_e(look)}</p>'
        "</div></div>"
        for index, (href, title, what, look) in enumerate(stops, start=1)
    )
    intro = (
        '<p class="section-sub">Five stops, about two minutes. Everything '
        "is live and logged out; nothing on this path costs anything or "
        "requires an account. The owner's session console, where beliefs are "
        "created and ratified, is deliberately private; the demo video shows "
        "it end to end.</p>"
    )
    return _page(
        title="Baraza: the two-minute tour",
        heading="The two-minute tour",
        lede="What to open, in order, and what to look for at each stop.",
        body=intro + body,
        nav=_public_nav("tour"),
        wordmark_note="memory with due process",
    )


# ---------------------------------------------------------------- session index


def render_session_index(sessions: list[dict[str, Any]]) -> str:
    """The owner's front door: open a working session, or resume one."""
    if sessions:
        rows = "".join(
            '<div class="card">'
            f'<a href="/sessions/{_e(s["session_id"])}/view">'
            f'{_e(s["session_id"])}</a>'
            f'<div class="prov">{_e(s.get("persona_id", ""))}'
            f'<span class="dot">·</span>{_e(s.get("opened_at_iso", ""))}</div>'
            "</div>"
            for s in sessions
        )
    else:
        rows = (
            '<div class="empty"><h2>No sessions yet.</h2>'
            "<p>A session exists only after the reconciler has produced an "
            "agenda from the ledger, the agent leads with what the record "
            "disputes, so an empty ledger means there is honestly nothing to "
            "open a session about yet.</p></div>"
        )
    form = (
        '<form class="composer" method="post" action="/sessions/open">'
        '<input type="text" name="persona_id" value="builder" '
        'aria-label="Persona id">'
        '<button class="primary" type="submit">Open a session</button></form>'
    )
    return _page(
        title="Baraza: sessions",
        heading="Working sessions",
        lede="Every turn is externalized to the append-only log before the next is solicited.",
        body=form + rows,
        nav=_owner_nav("sessions"),
        wordmark_note="session console",
    )


# ----------------------------------------------------------------- session view


def render_divergence_card(divergence: dict[str, Any], *, session_id: str) -> str:
    """The contradiction, both quotes on screen, adjudication buttons wired.

    ``divergence`` fields: ``new_quote``/``new_anchor``/``new_claim_id`` for the
    statement just made, ``old_quote``/``old_anchor``/``old_claim_id`` for the
    committed record it collides with, plus ``contradiction_id`` and
    ``rationale``. A missing old quote renders the withheld placeholder, the
    card can announce that a conflict exists without quoting what the audience
    may not read.
    """
    old_quote = divergence.get("old_quote") or WITHHELD_PLACEHOLDER
    new_quote = divergence.get("new_quote") or ""
    payload = {
        "session_id": session_id,
        "contradiction_id": divergence.get("contradiction_id"),
        "new_claim_id": divergence.get("new_claim_id"),
        "old_claim_id": divergence.get("old_claim_id"),
    }
    return (
        '<section class="divergence" id="divergence-card" '
        f"data-adjudication='{_e(json.dumps(payload))}'>"
        "<h2>These cannot both govern.</h2>"
        f'<p>{_e(divergence.get("rationale", ""))}</p>'
        '<div class="sides">'
        '<div class="side"><h3>On the record</h3>'
        f"<blockquote>{_e(old_quote)}</blockquote>"
        f'<div class="prov">{_e(divergence.get("old_anchor", ""))}'
        f'<span class="dot">·</span>{_e(divergence.get("old_claim_id", ""))}</div></div>'
        '<div class="side"><h3>Just now</h3>'
        f"<blockquote>{_e(new_quote)}</blockquote>"
        f'<div class="prov">{_e(divergence.get("new_anchor", ""))}'
        f'<span class="dot">·</span>{_e(divergence.get("new_claim_id", ""))}</div></div>'
        "</div>"
        '<div class="actions">'
        '<button class="primary" data-choice="this_governs">This governs</button>'
        '<button data-choice="that_governs">That governs</button>'
        '<button class="quiet" data-choice="both_conditional">'
        "Both, split into a conditional</button>"
        "</div>"
        '<div class="conditional" id="conditional-box">'
        '<textarea id="conditional-text" '
        'placeholder="State the conditional rule that honors both statements"></textarea>'
        '<button class="primary" id="conditional-submit">Commit the conditional</button>'
        "</div>"
        "</section>"
    )


def render_session_view(
    *,
    session_id: str,
    persona_id: str,
    turns: list[dict[str, Any]],
    agenda_items: list[dict[str, Any]],
    retired_count: int,
    divergence: dict[str, Any] | None,
    pending_count: int,
) -> str:
    """The partner session: chat panel, agenda rail with retirement ticks."""
    bubbles = "".join(
        '<div class="turn'
        + (" partner" if t.get("is_partner") else "")
        + '">'
        + f"<div>{_e(t.get('text', ''))}</div>"
        + '<div class="meta">'
        + _e(t.get("role", ""))
        + '<span class="dot">·</span>'
        + _e(t.get("kind", ""))
        + '<span class="dot">·</span>'
        + _e(t.get("occurred_at_iso", ""))
        + "</div></div>"
        for t in turns
    )
    if not bubbles:
        bubbles = (
            '<div class="empty"><h2>No turns yet.</h2>'
            "<p>The agent speaks first, from the agenda the ledger produced.</p></div>"
        )

    rail_items = "".join(
        '<div class="agenda-item'
        + (" retired" if item.get("retired") else "")
        + '">'
        + (
            '<span class="tick" title="Resolved and retired, this item will not '
            'appear on the next agenda">✓</span>'
            if item.get("retired")
            else '<span class="open-mark" title="Open">○</span>'
        )
        + "<div>"
        + _e(item.get("question", ""))
        + (
            f'<span class="why">{_e(item["why_it_matters"])}</span>'
            if item.get("why_it_matters")
            else ""
        )
        + "</div></div>"
        for item in agenda_items
    )
    if not rail_items:
        rail_items = '<p class="honest">The agenda is empty.</p>'
    retired_note = (
        f'<p class="honest">{retired_count} item(s) retired by resolved '
        "disagreements, the loop closes on screen.</p>"
        if retired_count
        else ""
    )

    divergence_html = (
        render_divergence_card(divergence, session_id=session_id) if divergence else ""
    )

    queue_link = (
        f'<p class="honest">{pending_count} belief(s) await ratification in the '
        f'<a href="/approvals?session_id={_e(session_id)}">approval queue</a>. '
        "Nothing acts on a belief you have not ratified.</p>"
        if pending_count
        else ""
    )

    body = (
        '<div class="session-grid"><div>'
        f'<div class="chat" id="chat">{bubbles}</div>'
        f"{divergence_html}"
        '<form class="composer" id="composer">'
        '<textarea id="turn-text" placeholder="Say something to the agent" '
        'aria-label="Your turn"></textarea>'
        '<button class="primary" type="submit">Send</button></form>'
        '<div class="honest" id="turn-status"></div>'
        f"{queue_link}"
        "</div>"
        '<aside class="agenda"><h2>Agenda</h2>'
        f"{rail_items}{retired_note}</aside></div>"
    )

    script = _SESSION_SCRIPT.replace("__SESSION_ID__", json.dumps(session_id))
    return _page(
        title=f"Baraza: session {session_id}",
        heading=f"Session with {persona_id}",
        lede="Every turn lands in the append-only log; the agenda shrinks as disagreements resolve.",
        body=body,
        nav=_owner_nav("sessions"),
        wordmark_note="session console",
        script=script,
    )


_SESSION_SCRIPT = """<script>
(function () {
  var sessionId = __SESSION_ID__;

  function wireDivergence(card) {
    if (!card) return;
    var payload = JSON.parse(card.getAttribute('data-adjudication'));
    card.querySelectorAll('button[data-choice]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var choice = btn.getAttribute('data-choice');
        if (choice === 'both_conditional') {
          document.getElementById('conditional-box').classList.add('open');
          return;
        }
        adjudicate(payload, choice, null);
      });
    });
    var submit = document.getElementById('conditional-submit');
    if (submit) submit.addEventListener('click', function () {
      var text = document.getElementById('conditional-text').value.trim();
      if (text) adjudicate(payload, 'both_conditional', text);
    });
  }

  function adjudicate(payload, choice, conditionalText) {
    fetch('/sessions/' + sessionId + '/divergence', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        choice: choice,
        contradiction_id: payload.contradiction_id,
        new_claim_id: payload.new_claim_id,
        old_claim_id: payload.old_claim_id,
        conditional_text: conditionalText
      })
    }).then(function (r) {
      if (r.ok) { window.location.reload(); }
      else { r.json().then(function (d) { setStatus(d.detail || 'adjudication failed'); }); }
    }).catch(function () { setStatus('The service could not be reached.'); });
  }

  function setStatus(text) {
    document.getElementById('turn-status').textContent = text;
  }

  document.getElementById('composer').addEventListener('submit', function (e) {
    e.preventDefault();
    var box = document.getElementById('turn-text');
    var text = box.value.trim();
    if (!text) return;
    setStatus('Recording your turn\\u2026');
    fetch('/sessions/' + sessionId + '/turns', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text: text})
    }).then(function (r) {
      if (r.ok) { window.location.reload(); }
      else {
        r.json().then(function (d) {
          setStatus(d.detail || 'The turn was not processed.');
        }).catch(function () { setStatus('The turn was not processed.'); });
      }
    }).catch(function () { setStatus('The service could not be reached.'); });
  });

  wireDivergence(document.getElementById('divergence-card'));

  // Poll for turns appended elsewhere (a resumed instance, a second window).
  var lastCount = document.querySelectorAll('.turn').length;
  setInterval(function () {
    fetch('/sessions/' + sessionId + '/state').then(function (r) {
      if (!r.ok) return;
      r.json().then(function (d) {
        if (d.turn_count !== lastCount) { window.location.reload(); }
      });
    }).catch(function () {});
  }, 4000);
})();
</script>"""


# ------------------------------------------------------------------ the dossier


def render_dossier_view(
    *,
    beliefs: list[dict[str, Any]],
    withheld: int,
    can_reject: bool,
) -> str:
    """Every belief the agent holds that this audience may read.

    ``beliefs`` entries carry ``claim_id``, ``rule``, ``quote``, ``anchor``,
    ``learned_at_iso``, ``tier``, ``visibility``, the quote already read
    through the audience predicate by the service layer.
    """
    if beliefs:
        cards = "".join(
            '<article class="card">'
            f'<div><strong>{_e(b.get("rule", ""))}</strong> '
            f'<span class="tag {_e(b.get("tier", ""))}">{_e(b.get("tier", ""))}</span> '
            f'<span class="tag">{_e(b.get("visibility", ""))}</span></div>'
            f"<blockquote>{_e(b.get('quote') or WITHHELD_PLACEHOLDER)}</blockquote>"
            '<div class="prov">'
            f'{_e(b.get("anchor", ""))}<span class="dot">·</span>'
            f'learned {_e(b.get("learned_at_iso", ""))}<span class="dot">·</span>'
            f'{_e(b.get("claim_id", ""))}</div>'
            + (
                f'<p><button class="danger" data-reject="{_e(b.get("claim_id", ""))}">'
                "Reject this belief</button></p>"
                if can_reject
                else ""
            )
            + "</article>"
            for b in beliefs
        )
    else:
        cards = (
            '<div class="empty"><h2>This dossier shows nothing, and that is the '
            "boundary working, not a broken page.</h2>"
            "<p>Every belief in this system is created <strong>private</strong>. "
            "It appears here only after its owner ratified it <em>and</em> chose "
            "to publish it, two separate decisions, two separate events in an "
            "append-only log. Until both happen, a logged-out reader sees "
            "exactly this.</p></div>"
        )

    withheld_line = (
        f'<p class="withheld-line">{withheld} further belief(s) are committed '
        "but not published to this audience. They exist; their contents are not "
        "disclosed here, and no logged-out request can reach them.</p>"
        if withheld
        else '<p class="withheld-line">No committed beliefs are being withheld '
        "from this audience.</p>"
    )

    script = ""
    if can_reject:
        script = """<script>
document.querySelectorAll('button[data-reject]').forEach(function (btn) {
  btn.addEventListener('click', function () {
    fetch('/api/dossier/reject', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({claim_id: btn.getAttribute('data-reject')})
    }).then(function (r) {
      if (r.ok) { window.location.reload(); }
      else { r.json().then(function (d) { alert(d.detail || 'reject failed'); }); }
    });
  });
});
</script>"""

    return _page(
        title="Baraza: the dossier",
        heading="The dossier",
        lede=(
            "Every belief the agent holds about its user, each with the verbatim "
            "quote and turn anchor that put it there. Rejecting one appends a "
            "retraction event; nothing is ever edited in place."
        ),
        body=cards + withheld_line,
        nav=_public_nav("dossier"),
        wordmark_note="the file it keeps on you",
        script=script,
    )


# ----------------------------------------------------------------- the doctrine


def render_doctrine_view(
    *,
    rules: list[dict[str, Any]] | None,
    diff: dict[str, Any] | None,
    unavailable_reason: str,
) -> str:
    """The compiled operating policy, every rule with its provenance.

    ``rules`` entries carry ``text``, ``claim_id``, ``anchor``, ``quote``
    (``None`` when the cited claim is not readable by this audience, the rule's
    existence renders, its evidence does not). ``rules=None`` means the compiler
    was not available and ``unavailable_reason`` says so honestly.
    """
    if rules is None:
        body = (
            '<div class="empty"><h2>The compiled doctrine is not available on '
            "this surface yet.</h2>"
            f"<p>{_e(unavailable_reason)}</p>"
            "<p>Nothing is substituted in its place: a placeholder policy would "
            "be a fabricated one.</p></div>"
        )
    elif not rules:
        body = (
            '<div class="empty"><h2>The doctrine compiles to no rules readable '
            "by this audience.</h2>"
            "<p>Rules exist only where a ratified belief put them, and each "
            "rule's evidence obeys the same visibility boundary as the dossier "
            "itself.</p></div>"
        )
    else:
        body = "".join(
            '<article class="card rule">'
            f'<div class="rule-text">{_e(r.get("text", ""))}</div>'
            f"<blockquote>{_e(r.get('quote') or WITHHELD_PLACEHOLDER)}</blockquote>"
            '<div class="prov">['
            f'{_e(r.get("claim_id", ""))}<span class="dot">|</span>'
            f'{_e(r.get("anchor", ""))}<span class="dot">|</span>'
            + ("quote above" if r.get("quote") else "quote withheld")
            + "]</div></article>"
            for r in rules
        )

    body += _render_doctrine_diff(diff)

    return _page(
        title="Baraza: the doctrine",
        heading="The operating doctrine",
        lede=(
            "The session policy compiled from ratified beliefs, same doctrine, "
            "every rule cited. Each rule names the claim, anchor, and quote "
            "that put it there."
        ),
        body=body,
        nav=_public_nav("doctrine"),
        wordmark_note="the file it keeps on you",
    )


def _render_doctrine_diff(diff: dict[str, Any] | None) -> str:
    if diff is None:
        return (
            '<section class="card diff-panel"><h2>Doctrine diff</h2>'
            '<p class="honest">No diff between epochs is available yet, either '
            "fewer than two doctrine epochs exist, or the diff module is not "
            "present on this surface. Nothing is shown in its place.</p></section>"
        )
    added = diff.get("added") or []
    removed = diff.get("removed") or []
    changed = diff.get("changed") or []
    if not (added or removed or changed):
        return (
            '<section class="card diff-panel"><h2>Doctrine diff</h2>'
            '<p class="honest">The last two epochs compiled to the same '
            "doctrine.</p></section>"
        )

    def _entries(entries: list[dict[str, Any]], css: str, label: str) -> str:
        return "".join(
            f'<li class="{css}">{_e(label)}: {_e(e.get("text", ""))} '
            f'<span class="prov">[{_e(e.get("claim_id", ""))}]</span></li>'
            for e in entries
        )

    return (
        '<section class="card diff-panel"><h2>Doctrine diff, last two epochs</h2>'
        "<ul>"
        + _entries(added, "diff-added", "added")
        + _entries(removed, "diff-removed", "removed")
        + _entries(changed, "", "changed")
        + "</ul>"
        '<p class="honest">Each changed rule names the claim that changed it, '
        "the compiler's provenance map, not an inference.</p></section>"
    )


# ------------------------------------------------------------- approval queue


def render_approval_queue(
    *,
    session_id: str | None,
    pending: list[dict[str, Any]],
) -> str:
    """Pending beliefs batched for session-end ratification.

    Each row offers approve / reject / defer and a visibility choice that
    defaults to private, declining to choose publishes nothing.
    """
    if pending:
        rows = "".join(
            '<article class="card queue-item" data-claim="' + _e(p["claim_id"]) + '">'
            f'<div><strong>{_e(p.get("rule", ""))}</strong> '
            '<span class="tag pending">pending</span></div>'
            f"<blockquote>{_e(p.get('quote') or WITHHELD_PLACEHOLDER)}</blockquote>"
            '<div class="prov">'
            f'{_e(p.get("anchor", ""))}<span class="dot">·</span>'
            f'{_e(p.get("learned_at_iso", ""))}<span class="dot">·</span>'
            f'{_e(p.get("claim_id", ""))}</div>'
            '<div class="queue-controls">'
            "<label><input type=\"radio\" name=\"d-" + _e(p["claim_id"]) + '" '
            'value="approve"> approve</label>'
            "<label><input type=\"radio\" name=\"d-" + _e(p["claim_id"]) + '" '
            'value="reject"> reject</label>'
            "<label><input type=\"radio\" name=\"d-" + _e(p["claim_id"]) + '" '
            'value="defer" checked> defer</label>'
            "<label>visibility "
            '<select name="v-' + _e(p["claim_id"]) + '">'
            '<option value="private" selected>private (default)</option>'
            '<option value="public">public</option>'
            "</select></label></div></article>"
            for p in pending
        )
        submit = (
            '<button class="primary" id="submit-batch">Submit ratifications</button>'
            '<span class="honest" id="batch-status"></span>'
        )
    else:
        rows = (
            '<div class="empty"><h2>Nothing awaits ratification.</h2>'
            "<p>Beliefs reach this queue as <em>pending</em> claims minted from "
            "session turns. None exist right now, so there is nothing to decide "
            ",  and nothing was decided for you.</p></div>"
        )
        submit = ""

    script = ""
    if pending:
        script = (
            "<script>\n(function () {\n"
            f"  var sessionId = {json.dumps(session_id or 'batch')};\n"
            + """  document.getElementById('submit-batch').addEventListener('click', function () {
    var items = [];
    document.querySelectorAll('article[data-claim]').forEach(function (row) {
      var id = row.getAttribute('data-claim');
      var decision = row.querySelector('input[name="d-' + id + '"]:checked').value;
      var visibility = row.querySelector('select[name="v-' + id + '"]').value;
      items.push({claim_id: id, decision: decision, visibility: visibility});
    });
    fetch('/sessions/' + sessionId + '/approvals', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({approver_id: 'builder', items: items})
    }).then(function (r) {
      if (r.ok) { window.location.reload(); }
      else { r.json().then(function (d) {
        document.getElementById('batch-status').textContent = d.detail || 'submit failed';
      }); }
    }).catch(function () {
      document.getElementById('batch-status').textContent = 'The service could not be reached.';
    });
  });
})();
</script>"""
        )

    return _page(
        title="Baraza: approval queue",
        heading="Approval queue",
        lede=(
            "No belief reaches committed, and therefore behavior, without "
            "ratification here. Deferring keeps it pending; visibility defaults "
            "to private."
        ),
        body=rows + submit,
        nav=_owner_nav("approvals"),
        wordmark_note="session console",
        script=script,
    )
