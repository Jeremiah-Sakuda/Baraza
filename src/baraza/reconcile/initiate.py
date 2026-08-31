"""Initiation — the agent proposes the next session instead of waiting for one.

Runs as the final step of the nightly reconcile job (both modes). It reads the
fold, derives an agenda from what the ledger already knows — open
contradictions and beliefs that have gone unconfirmed too long — appends a
``session.proposed`` event, and sends exactly one outbound notification.

Three properties this module is written around:

* **Honesty of the ``scheduled`` flag.** The flag on ``session.proposed`` comes
  from the caller, who resolved it via ``job.resolve_scheduled()``. Only the
  Cloud Scheduler → trigger-service path sets ``BARAZA_RUN_TRIGGER=
  cloud-scheduler``, so a hand-run job proposes a session labelled ``manual``
  and the initiation evidence stays a count of nights, not of demos.

* **No model calls.** The agenda here is templated from ledger rows, not
  generated. Initiation must never be the reason a nightly run fails, and a
  generation call at 03:17 with nobody watching is exactly the kind of
  dependency that would make it one. The interviewer rephrases items when the
  session actually opens; this module's job is to cite, not to write prose.

* **Notification failure is degraded, not fatal.** Email is attempted only when
  SMTP is configured by environment; otherwise — or when the send fails — the
  invitation goes to stdout, and it is in the log either way because the
  ``session.proposed`` payload carries it. A job that exits nonzero because a
  mail relay was down would erase a night of reconcile evidence to report a
  notification problem, which is the wrong trade in both directions.

Retry safety: the event's payload is derived from the fold and the run instant,
both of which are identical on a retried execution, so the content-addressed
event ID collides and the second append is a no-op. One proposal per night, not
one per attempt.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field

from baraza.fold.graph import GraphState
from baraza.fold.store import EventStore
from baraza.reconcile.ledger import DisputedLedger
from baraza.schema.claim import Claim, Tier
from baraza.schema.event import Event, EventType
from baraza.schema.temporal import EpochMillis
from baraza.schema.visibility import Audience

__all__ = [
    "AgendaEntry",
    "InitiationResult",
    "STALE_AFTER_DAYS",
    "stale_beliefs",
    "build_agenda",
    "render_invitation",
    "propose_session",
]

STALE_AFTER_DAYS = 14
"""How long a committed belief may go unconfirmed before it earns an agenda slot.

Two weeks, chosen against the cadence this system actually runs at: sessions are
roughly daily, so fourteen days of silence about a belief means roughly fourteen
sessions in which nothing re-touched it. Shorter would fill every agenda with
re-confirmations and make initiation feel like nagging; the agenda is capped
anyway, so the cost of being wrong here is ordering, not omission.
"""

_DAY_MS = 86_400_000

MAX_AGENDA_ITEMS = 8
"""Fewer than an interview agenda (12): an invitation is read in an inbox, and
an agenda that scrolls is an agenda that gets skimmed. The ledger keeps
everything; the invitation takes what fits."""


@dataclass(frozen=True, slots=True)
class AgendaEntry:
    """One proposed item, traceable to the ledger entry that spawned it."""

    kind: str
    """``"contradiction"`` or ``"stale-belief"``."""

    reference: str
    """The contradiction ID or claim ID this item cites. Every item exists
    because of exactly one ledger entry, and this field is how a reader checks
    that in the log rather than trusting the sentence next to it."""

    prompt: str
    cited_claim_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "reference": self.reference,
            "prompt": self.prompt,
            "cited_claim_ids": list(self.cited_claim_ids),
        }


@dataclass(slots=True)
class InitiationResult:
    """What initiation did, reported rather than implied."""

    proposed: bool
    """False when the append collided — a retry found its own proposal."""

    event_id: str
    agenda: list[AgendaEntry]
    invitation: str
    channel: str
    """Which outbound path was taken: ``email``, ``stdout``, or
    ``email-failed;stdout`` when SMTP was configured but the send raised. The
    job prints this so a missing invitation is diagnosable from the run output
    instead of from an inbox."""

    def describe(self) -> list[str]:
        lines = [
            f"  session proposed       {self.event_id}"
            + ("" if self.proposed else " (already in the log; retry)"),
            f"  agenda items           {len(self.agenda)}",
            f"  invitation via         {self.channel}",
        ]
        return lines


def stale_beliefs(
    state: GraphState,
    events: list[Event],
    *,
    now: EpochMillis,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> list[Claim]:
    """Committed beliefs nothing has touched in ``stale_after_days`` days.

    "Touched" is read out of the log, not inferred: the last instant at which
    *any* event named the claim — assertion, ratification, adjudication,
    whatever comes later. ``observed_at`` alone would be wrong here for the
    same reason it was wrong in the reconciler's work pool — it records when
    the source was authored, so every belief from an old document would read
    as permanently stale no matter how recently it was ratified.

    The lookup is deliberately generic over payload shape rather than a switch
    on event type. The approval path is the only module permitted to name the
    promotion event (a guard test enforces the ban across this package), and
    this module has no business distinguishing *how* a claim was touched —
    only when the log last mentioned it.

    Rejected claims never appear: retraction removes a claim from every future
    agenda, and a "please re-confirm" prompt about a retracted belief would be
    the agenda resurrecting exactly what the user struck from the record.
    """
    last_touched: dict[str, EpochMillis] = {}
    for event in events:
        payload = event.payload
        claim_id = str(
            payload.get("claim_id") or payload.get("claim", {}).get("claim_id") or ""
        )
        if not claim_id:
            continue
        previous = last_touched.get(claim_id)
        if previous is None or event.occurred_at > previous:
            last_touched[claim_id] = event.occurred_at

    cutoff = now - stale_after_days * _DAY_MS
    stale = [
        claim
        for claim in state.claims.values()
        if claim.tier is Tier.COMMITTED
        and last_touched.get(claim.claim_id, claim.observed_at) <= cutoff
    ]
    # Oldest-first: the belief that has gone longest unconfirmed is the one
    # most likely to have quietly stopped being true. Claim ID tiebreak keeps
    # the ordering — and therefore the event payload and its ID — deterministic.
    stale.sort(
        key=lambda c: (last_touched.get(c.claim_id, c.observed_at), c.claim_id)
    )
    return stale


def build_agenda(
    state: GraphState,
    events: list[Event],
    *,
    now: EpochMillis,
    audience: Audience = Audience.OWNER,
    stale_after_days: int = STALE_AFTER_DAYS,
    size: int = MAX_AGENDA_ITEMS,
) -> list[AgendaEntry]:
    """Derive the proposed agenda: contradictions first, then stale beliefs.

    Contradictions outrank staleness because a contradiction is the ledger
    saying the record is *wrong somewhere right now*, while staleness only says
    it might be. Quotes are taken from the audience-rendered ledger row, never
    from the claim directly, so an unreadable side is counted and prompted
    about but never quoted — the same downgrade rule the interview agenda uses.
    """
    entries: list[AgendaEntry] = []

    for row in DisputedLedger(state).rows(audience, limit=size):
        if row.rendered.fully_readable:
            sides = "; ".join(row.rendered.sides)
            prompt = (
                f"The record disagrees with itself about "
                f"{row.contradiction.predicate_hint}: {sides} "
                f"Which governs?"
            )
            cited = list(row.contradiction.claim_ids)
        else:
            prompt = (
                f"The record disagrees with itself about "
                f"{row.contradiction.predicate_hint}, but part of that record "
                f"is not readable by this audience. What do you remember?"
            )
            cited = []
        entries.append(
            AgendaEntry(
                kind="contradiction",
                reference=row.contradiction_id,
                prompt=prompt,
                cited_claim_ids=cited,
            )
        )

    remaining = size - len(entries)
    if remaining > 0:
        for claim in stale_beliefs(
            state, events, now=now, stale_after_days=stale_after_days
        )[:remaining]:
            quote = claim.quote_for(audience)
            cited_quote = f' — "{quote}"' if quote else ""
            entries.append(
                AgendaEntry(
                    kind="stale-belief",
                    reference=claim.claim_id,
                    prompt=(
                        f"Committed belief unconfirmed for over "
                        f"{stale_after_days} days: {claim.predicate_hint}"
                        f"{cited_quote}. Still true, or retract it?"
                    ),
                    cited_claim_ids=[claim.claim_id],
                )
            )

    return entries


def render_invitation(
    agenda: list[AgendaEntry], *, run_id: str, session_url: str | None
) -> str:
    """The invitation body: a numbered agenda, each item citing its ledger entry.

    Plain text on purpose — it must read identically in an email client, a
    terminal, and the ``session.proposed`` payload a judge inspects later.
    """
    lines = [
        f"Baraza proposes a session. (nightly run {run_id})",
        "",
    ]
    if agenda:
        lines.append(f"Agenda — {len(agenda)} item(s), each citing the ledger "
                     "entry that spawned it:")
        lines.append("")
        for index, entry in enumerate(agenda, start=1):
            lines.append(f"{index}. {entry.prompt}")
            lines.append(f"   [{entry.kind}: {entry.reference}]")
    else:
        lines.append(
            "The ledger holds no open contradictions and no stale beliefs "
            "tonight. No agenda items; the session is proposed so the record "
            "shows the check happened."
        )
    lines.append("")
    if session_url:
        lines.append(f"Open the session: {session_url}")
    else:
        lines.append(
            "Session URL: not configured (set BARAZA_SESSION_URL). "
            "Open the interview service directly."
        )
    return "\n".join(lines)


def _send_email(invitation: str, *, run_id: str) -> str | None:
    """Attempt SMTP delivery. Returns None on success, the failure reason otherwise.

    Configuration is entirely environmental — ``BARAZA_SMTP_HOST`` and
    ``BARAZA_INVITE_TO`` are the gate; port, credentials, and sender are
    optional refinements. An unset gate is not an error: it is the local and
    demo default, and the caller falls back to stdout without complaint.
    """
    host = os.environ.get("BARAZA_SMTP_HOST", "").strip()
    to_addr = os.environ.get("BARAZA_INVITE_TO", "").strip()
    if not host or not to_addr:
        return "unconfigured"

    import smtplib
    from email.message import EmailMessage

    port = int(os.environ.get("BARAZA_SMTP_PORT", "587"))
    user = os.environ.get("BARAZA_SMTP_USER", "").strip()
    password = os.environ.get("BARAZA_SMTP_PASSWORD", "")
    from_addr = os.environ.get("BARAZA_INVITE_FROM", "").strip() or (user or to_addr)

    message = EmailMessage()
    message["Subject"] = f"Baraza: session proposed ({run_id})"
    message["From"] = from_addr
    message["To"] = to_addr
    message.set_content(invitation)

    try:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.ehlo()
            if smtp.has_extn("starttls"):
                smtp.starttls()
                smtp.ehlo()
            if user:
                smtp.login(user, password)
            smtp.send_message(message)
    except Exception as exc:  # noqa: BLE001 - the boundary this module exists for
        # Named, printed, and swallowed. The invitation is already in the log;
        # a mail failure must never cost the night's reconcile evidence.
        return f"{type(exc).__name__}: {exc}"
    return None


def propose_session(
    store: EventStore,
    state: GraphState,
    events: list[Event],
    *,
    run_id: str,
    proposed_at: EpochMillis,
    scheduled: bool,
    audience: Audience = Audience.OWNER,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> InitiationResult:
    """Generate the agenda, append ``session.proposed``, notify once.

    ``scheduled`` is the caller's resolution of the trigger, passed through
    unaltered. This function labels; it never decides — the decision lives in
    ``job.resolve_scheduled()`` where its failure modes are documented.
    """
    agenda = build_agenda(
        state,
        events,
        now=proposed_at,
        audience=audience,
        stale_after_days=stale_after_days,
    )
    session_url = os.environ.get("BARAZA_SESSION_URL", "").strip() or None
    invitation = render_invitation(agenda, run_id=run_id, session_url=session_url)

    event = Event.create(
        event_type=EventType.SESSION_PROPOSED,
        occurred_at=proposed_at,
        payload={
            "run_id": run_id,
            "agenda": [entry.to_dict() for entry in agenda],
            "invitation": invitation,
            "trigger": "cloud-scheduler" if scheduled else "manual",
        },
        actor="reconcile-job",
        scheduled=scheduled,
    )
    proposed = store.append(event)

    failure = _send_email(invitation, run_id=run_id)
    if failure is None:
        channel = "email"
    else:
        if failure == "unconfigured":
            channel = "stdout"
        else:
            channel = "email-failed;stdout"
            print(f"invitation email failed ({failure}); falling back to stdout",
                  file=sys.stderr)
        print(invitation)

    return InitiationResult(
        proposed=proposed,
        event_id=event.event_id,
        agenda=agenda,
        invitation=invitation,
        channel=channel,
    )
