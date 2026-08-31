"""Initiation — the nightly job's end hook proposes the next session.

The property under test is honesty, in three shapes:

* the agenda cites the ledger entry that spawned each item, so a reader can
  check every sentence against the log;
* the ``session.proposed`` event carries the ``scheduled`` flag the trigger
  actually resolved to — a hand-run job proposes a ``manual`` session;
* notification failure degrades to stdout and never fails the run, because a
  night of reconcile evidence cannot be re-run to fix a mail relay.

Everything runs against the JSONL store and fakes. Nothing here touches GCP,
Vertex, or a real SMTP server.
"""

from __future__ import annotations

import json

import pytest

from baraza.fold.graph import fold
from baraza.fold.store import JsonlEventStore
from baraza.reconcile.initiate import (
    build_agenda,
    propose_session,
    render_invitation,
    stale_beliefs,
)
from baraza.reconcile.job import run_real, run_stub
from baraza.schema.claim import Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.event import EventType
from baraza.schema.visibility import Audience, Visibility
from baraza_testkit import (
    FakeLLMClient,
    asserted,
    claim,
    committed,
    detected,
    ms,
    rejected,
)

_DAY = 86_400_000
NOW = ms("2026-08-31T03:17:00Z")
RUN_ID = f"nightly-{NOW}"

NO_CONTRADICTIONS = json.dumps({"contradictions": []})


def _store(tmp_path) -> JsonlEventStore:
    return JsonlEventStore(tmp_path / "events.jsonl")


def _contradiction(*claim_ids: str, cid: str = "con-1") -> Contradiction:
    return Contradiction(
        contradiction_id=cid,
        subject_id="ent:treasurer",
        predicate_hint="signing authority",
        claim_ids=list(claim_ids),
        detected_at=NOW - _DAY,
        confidence=0.9,
        rationale="the two records give different thresholds",
    )


def _propose(store, *, scheduled: bool = False, **kwargs):
    events = store.read_all()
    return propose_session(
        store,
        fold(events),
        events,
        run_id=RUN_ID,
        proposed_at=NOW,
        scheduled=scheduled,
        **kwargs,
    )


class TestStaleBeliefs:
    def test_a_committed_belief_untouched_past_the_cutoff_is_stale(self, tmp_path):
        store = _store(tmp_path)
        old = claim(subject="ent:the-user", predicate="estimates")
        store.append(asserted(old, NOW - 40 * _DAY))
        store.append(committed(old.claim_id, NOW - 30 * _DAY))
        events = store.read_all()

        stale = stale_beliefs(fold(events), events, now=NOW)
        assert [c.claim_id for c in stale] == [old.claim_id]

    def test_a_recent_commit_confirms_an_old_belief(self, tmp_path):
        # observed_at is the instant the source was authored, which is exactly
        # the wrong staleness clock: a belief ratified yesterday about a 2016
        # document is fresh. The log's touch instants are the clock.
        store = _store(tmp_path)
        old = claim(observed_at="2016-04-01T00:00:00Z")
        store.append(asserted(old))
        store.append(committed(old.claim_id, NOW - _DAY))
        events = store.read_all()

        assert stale_beliefs(fold(events), events, now=NOW) == []

    def test_a_pending_claim_is_never_a_stale_candidate(self, tmp_path):
        store = _store(tmp_path)
        pending = claim()
        store.append(asserted(pending, NOW - 40 * _DAY))
        events = store.read_all()

        assert stale_beliefs(fold(events), events, now=NOW) == []

    def test_a_retracted_belief_never_returns_as_an_agenda_item(self, tmp_path):
        # Retraction removes a claim from every future agenda. A staleness
        # prompt about it would resurrect what the user struck from the record.
        store = _store(tmp_path)
        struck = claim()
        store.append(asserted(struck, NOW - 40 * _DAY))
        store.append(committed(struck.claim_id, NOW - 30 * _DAY))
        store.append(rejected(struck.claim_id, NOW - 20 * _DAY))
        events = store.read_all()

        assert stale_beliefs(fold(events), events, now=NOW) == []

    def test_oldest_unconfirmed_belief_ranks_first(self, tmp_path):
        store = _store(tmp_path)
        older = claim(predicate="a", locator="p.1 ¶1")
        newer = claim(predicate="b", locator="p.2 ¶1")
        # The commit follows the assertion by a millisecond: fold order between
        # same-instant events is an ID tiebreak, and a commit folded before its
        # assertion would retier nothing.
        store.append(asserted(older, NOW - 60 * _DAY))
        store.append(committed(older.claim_id, NOW - 60 * _DAY + 1))
        store.append(asserted(newer, NOW - 20 * _DAY))
        store.append(committed(newer.claim_id, NOW - 20 * _DAY + 1))
        events = store.read_all()

        stale = stale_beliefs(fold(events), events, now=NOW)
        assert [c.claim_id for c in stale] == [older.claim_id, newer.claim_id]


class TestBuildAgenda:
    def test_every_item_cites_the_ledger_entry_that_spawned_it(self, tmp_path):
        store = _store(tmp_path)
        a = claim(predicate="threshold", object_literal="500", locator="p.1 ¶1")
        b = claim(predicate="threshold", object_literal="1000", locator="p.9 ¶2")
        store.append(asserted(a, NOW - 5 * _DAY))
        store.append(asserted(b, NOW - 5 * _DAY))
        store.append(detected(_contradiction(a.claim_id, b.claim_id), NOW - _DAY))

        stale = claim(subject="ent:the-user", predicate="padding", locator="p.3 ¶1")
        store.append(asserted(stale, NOW - 40 * _DAY))
        store.append(committed(stale.claim_id, NOW - 30 * _DAY))

        events = store.read_all()
        agenda = build_agenda(fold(events), events, now=NOW)

        kinds = {entry.kind: entry for entry in agenda}
        assert kinds["contradiction"].reference == "con-1"
        assert set(kinds["contradiction"].cited_claim_ids) == {
            a.claim_id,
            b.claim_id,
        }
        assert kinds["stale-belief"].reference == stale.claim_id
        assert kinds["stale-belief"].cited_claim_ids == [stale.claim_id]

    def test_contradictions_outrank_stale_beliefs(self, tmp_path):
        store = _store(tmp_path)
        a = claim(predicate="threshold", object_literal="500", locator="p.1 ¶1")
        b = claim(predicate="threshold", object_literal="1000", locator="p.9 ¶2")
        store.append(asserted(a, NOW - 5 * _DAY))
        store.append(asserted(b, NOW - 5 * _DAY))
        store.append(detected(_contradiction(a.claim_id, b.claim_id), NOW - _DAY))
        stale = claim(subject="ent:the-user", predicate="padding", locator="p.3 ¶1")
        store.append(asserted(stale, NOW - 40 * _DAY))
        store.append(committed(stale.claim_id, NOW - 30 * _DAY))

        events = store.read_all()
        agenda = build_agenda(fold(events), events, now=NOW)
        assert [e.kind for e in agenda] == ["contradiction", "stale-belief"]

    def test_an_unreadable_side_is_prompted_about_but_never_quoted(self, tmp_path):
        # The visibility boundary: the reconciler may count what it cannot
        # quote. An agenda item built from a partially unreadable contradiction
        # survives — the count is honest — but carries no quotes and no claim
        # citations that would leak the withheld side's existence in detail.
        store = _store(tmp_path)
        secret_quote = "The advisor holds a second signing credential."
        a = claim(quote=secret_quote, object_literal="500", locator="p.1 ¶1",
                  visibility=Visibility.PRIVATE, tier=Tier.COMMITTED)
        b = claim(object_literal="1000", locator="p.9 ¶2",
                  visibility=Visibility.PUBLIC, tier=Tier.COMMITTED)
        store.append(asserted(a, NOW - 5 * _DAY))
        store.append(asserted(b, NOW - 5 * _DAY))
        store.append(detected(_contradiction(a.claim_id, b.claim_id), NOW - _DAY))

        events = store.read_all()
        agenda = build_agenda(
            fold(events), events, now=NOW, audience=Audience.SUCCESSOR
        )

        assert len(agenda) == 1
        assert secret_quote not in agenda[0].prompt
        assert agenda[0].cited_claim_ids == []
        # The reference still names the ledger entry: counted, not quoted.
        assert agenda[0].reference == "con-1"


class TestProposeSession:
    def test_appends_a_session_proposed_event_with_the_agenda(self, tmp_path):
        store = _store(tmp_path)
        stale = claim(subject="ent:the-user")
        store.append(asserted(stale, NOW - 40 * _DAY))
        store.append(committed(stale.claim_id, NOW - 30 * _DAY))

        result = _propose(store)

        proposals = store.read_by_type(EventType.SESSION_PROPOSED)
        assert len(proposals) == 1
        payload = proposals[0].payload
        assert payload["run_id"] == RUN_ID
        assert payload["agenda"][0]["reference"] == stale.claim_id
        assert payload["invitation"] == result.invitation

    def test_the_scheduled_flag_is_the_callers_resolution_not_a_default(
        self, tmp_path
    ):
        manual = _propose(_store(tmp_path), scheduled=False)
        assert manual.proposed

        store = JsonlEventStore(tmp_path / "scheduled.jsonl")
        _propose(store, scheduled=True)

        [event] = store.read_by_type(EventType.SESSION_PROPOSED)
        assert event.scheduled is True
        assert event.payload["trigger"] == "cloud-scheduler"

    def test_a_manual_proposal_is_labelled_manual(self, tmp_path):
        store = _store(tmp_path)
        _propose(store, scheduled=False)
        [event] = store.read_by_type(EventType.SESSION_PROPOSED)
        assert event.scheduled is False
        assert event.payload["trigger"] == "manual"

    def test_a_retry_appends_no_second_proposal(self, tmp_path):
        # Event IDs are content hashes over the fold-derived payload and the
        # run instant, so a retried job collides with its own proposal: one
        # session per night, not one per attempt.
        store = _store(tmp_path)
        first = _propose(store)
        second = _propose(store)

        assert first.proposed
        assert not second.proposed
        assert len(store.read_by_type(EventType.SESSION_PROPOSED)) == 1

    def test_unconfigured_email_falls_back_to_stdout(
        self, tmp_path, monkeypatch, capsys
    ):
        for name in ("BARAZA_SMTP_HOST", "BARAZA_INVITE_TO"):
            monkeypatch.delenv(name, raising=False)

        result = _propose(_store(tmp_path))

        assert result.channel == "stdout"
        assert result.invitation in capsys.readouterr().out

    def test_configured_email_sends_one_message(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BARAZA_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("BARAZA_INVITE_TO", "owner@example.test")

        sent = []

        class FakeSMTP:
            def __init__(self, host, port, timeout=None):
                self.host = host

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def ehlo(self):
                pass

            def has_extn(self, name):
                return False

            def login(self, user, password):  # pragma: no cover - unused here
                pass

            def send_message(self, message):
                sent.append(message)

        import smtplib

        monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)

        result = _propose(_store(tmp_path))

        assert result.channel == "email"
        assert len(sent) == 1
        assert RUN_ID in sent[0]["Subject"]

    def test_a_failing_smtp_send_degrades_and_never_raises(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.setenv("BARAZA_SMTP_HOST", "smtp.example.test")
        monkeypatch.setenv("BARAZA_INVITE_TO", "owner@example.test")

        import smtplib

        def explode(*args, **kwargs):
            raise OSError("relay unreachable")

        monkeypatch.setattr(smtplib, "SMTP", explode)

        result = _propose(_store(tmp_path))

        assert result.channel == "email-failed;stdout"
        captured = capsys.readouterr()
        assert result.invitation in captured.out
        assert "relay unreachable" in captured.err
        # And the invitation is in the log regardless of the channel.
        [event] = _store(tmp_path).read_by_type(EventType.SESSION_PROPOSED)
        assert event.payload["invitation"] == result.invitation


class TestInvitationBody:
    def test_numbered_items_cite_their_ledger_entries(self, tmp_path):
        store = _store(tmp_path)
        stale = claim(subject="ent:the-user")
        store.append(asserted(stale, NOW - 40 * _DAY))
        store.append(committed(stale.claim_id, NOW - 30 * _DAY))
        events = store.read_all()
        agenda = build_agenda(fold(events), events, now=NOW)

        body = render_invitation(agenda, run_id=RUN_ID, session_url=None)

        assert "1. " in body
        assert f"[stale-belief: {stale.claim_id}]" in body

    def test_the_session_url_appears_when_configured(self):
        body = render_invitation(
            [], run_id=RUN_ID, session_url="https://sessions.example.test/next"
        )
        assert "https://sessions.example.test/next" in body

    def test_an_unset_url_is_stated_rather_than_invented(self):
        body = render_invitation([], run_id=RUN_ID, session_url=None)
        assert "BARAZA_SESSION_URL" in body

    def test_an_empty_agenda_says_so(self):
        body = render_invitation([], run_id=RUN_ID, session_url=None)
        assert "no open contradictions" in body.lower()


class TestJobEndHook:
    def test_run_stub_ends_with_an_agenda_only_proposal(self, tmp_path, monkeypatch):
        monkeypatch.delenv("BARAZA_RUN_TRIGGER", raising=False)
        store = _store(tmp_path)
        stale = claim(subject="ent:the-user")
        store.append(asserted(stale, NOW - 40 * _DAY))
        store.append(committed(stale.claim_id, NOW - 30 * _DAY))

        result = run_stub(store, run_id=RUN_ID)

        assert result.initiation is not None
        assert result.initiation.proposed
        [event] = store.read_by_type(EventType.SESSION_PROPOSED)
        assert event.payload["agenda"][0]["reference"] == stale.claim_id
        # Agenda-only means no claims work: the stub adjudicated nothing.
        assert store.read_by_type(EventType.CLAIM_ADJUDICATED) == []

    def test_run_real_ends_with_a_proposal_that_sees_tonights_findings(
        self, tmp_path, monkeypatch
    ):
        # The agenda must be derived from the post-run fold: a contradiction
        # the run itself detects tonight is on tomorrow's proposed agenda.
        monkeypatch.delenv("BARAZA_RUN_TRIGGER", raising=False)
        store = _store(tmp_path)
        a = claim(predicate="threshold", object_literal="500", locator="p.1 ¶1")
        b = claim(predicate="threshold", object_literal="1000", locator="p.9 ¶2")
        store.append(asserted(a, NOW - 5 * _DAY))
        store.append(asserted(b, NOW - 5 * _DAY))

        # The detector's response names the colliding candidate by claim ID
        # and builds the Contradiction itself. When b is the claim under
        # examination it names itself and is discarded, so one results.
        client = FakeLLMClient(
            {
                "contradictions.v1": json.dumps(
                    {
                        "contradictions": [
                            {
                                "claim_id": b.claim_id,
                                "confidence": 0.9,
                                "rationale": "the thresholds disagree",
                            }
                        ]
                    }
                )
            }
        )
        result = run_real(store, run_id=RUN_ID, client=client)
        assert result.contradictions_found == 1

        assert result.initiation is not None
        [event] = store.read_by_type(EventType.SESSION_PROPOSED)
        assert any(
            item["kind"] == "contradiction"
            and set(item["cited_claim_ids"]) == {a.claim_id, b.claim_id}
            for item in event.payload["agenda"]
        )

    def test_the_scheduled_flag_flows_from_the_trigger_env(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("BARAZA_RUN_TRIGGER", "cloud-scheduler")
        store = _store(tmp_path)
        run_stub(store, run_id=RUN_ID)
        [event] = store.read_by_type(EventType.SESSION_PROPOSED)
        assert event.scheduled is True

    def test_initiation_failure_does_not_fail_the_night(
        self, tmp_path, monkeypatch, capsys
    ):
        monkeypatch.delenv("BARAZA_RUN_TRIGGER", raising=False)
        import baraza.reconcile.job as job_module

        def explode(*args, **kwargs):
            raise RuntimeError("initiation broke")

        monkeypatch.setattr(job_module, "propose_session", explode)

        store = _store(tmp_path)
        result = run_stub(store, run_id=RUN_ID)

        # The heartbeat — the night's evidence — still landed.
        assert store.read_by_type(EventType.HEARTBEAT)
        assert result.initiation is None
        assert "initiation broke" in capsys.readouterr().err

    def test_a_retried_run_reports_the_existing_proposal(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("BARAZA_RUN_TRIGGER", raising=False)
        store = _store(tmp_path)
        run_stub(store, run_id=RUN_ID)
        retry = run_stub(store, run_id=RUN_ID)

        assert retry.initiation is not None
        assert not retry.initiation.proposed
        assert len(store.read_by_type(EventType.SESSION_PROPOSED)) == 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
