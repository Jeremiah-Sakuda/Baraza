"""BAR-334 — a real SIGKILL, mid-turn, and a resume that re-asks.

The acceptance criterion is a property about a process, so the test kills one.
``interview_runner.py`` runs a four-exchange interview and parks inside the
window where a question is durably recorded and its answer has not arrived. The
test waits for it to get there, sends ``SIGKILL`` — uncatchable, no cleanup, no
flush, no atexit hook — restarts the runner against the same log, and requires:

* exchanges 1..n-1 replay from the log rather than being re-asked;
* exchange n's question is identified as the pending one and re-solicited;
* the re-append of that question is a no-op, so the resumed session has one copy
  of it and not two;
* the interview finishes.

A mocked kill would prove that a mock was called. Only ``kill -9`` on a real PID
proves that nothing between the fsync and the signal was needed.

Both backends are exercised where available. The JSONL store is the offline demo
path and always runs; the Firestore store runs when ``FIRESTORE_EMULATOR_HOST``
is exported, which ``scripts/with_emulator.sh`` does. The property is the same
on both — externalize before soliciting — and running it on the file store as
well is what keeps it testable on a clean clone with no cloud SDK.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from baraza.fold.store import JsonlEventStore
from baraza.interview.session_store import SessionStore
from baraza.schema.event import EventType
from baraza.schema.session import Session, TurnRole

pytestmark = pytest.mark.emulator

REPO = Path(__file__).resolve().parents[2]
RUNNER = Path(__file__).resolve().parent / "interview_runner.py"

PERSONA = "persona-a"
OPENED_AT = 1_777_000_000_000  # fixed, so the session ID is derivable by the test
EXCHANGES = 4
STALL_AT = 3
STALL_QUESTION = f"t-{2 * STALL_AT - 1}"  # t-5

SESSION_ID = Session.deterministic_id(persona_id=PERSONA, opened_at=OPENED_AT)


def _env() -> dict:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(REPO / "src"), *([existing] if existing else [])]
    )
    return env


def _spawn(tmp_path: Path, backend: str, collection: str, *extra: str, tag: str):
    """Start the runner with stdout and stderr on disk.

    On disk rather than in a pipe: the process is about to be SIGKILLed, and
    output already written to a file is readable afterwards without any
    cooperation from the corpse.
    """
    out = tmp_path / f"{tag}.out"
    err = tmp_path / f"{tag}.err"
    handle_out = out.open("w", encoding="utf-8")
    handle_err = err.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [
            sys.executable,
            str(RUNNER),
            "--backend", backend,
            "--log", str(tmp_path / "events.jsonl"),
            "--collection", collection,
            "--persona", PERSONA,
            "--opened-at", str(OPENED_AT),
            "--exchanges", str(EXCHANGES),
            *extra,
        ],
        stdout=handle_out,
        stderr=handle_err,
        env=_env(),
        cwd=str(REPO),
    )
    return process, out, err


def _wait_for(path: Path, *, timeout: float = 60.0, process=None) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process is not None and process.poll() is not None:
            raise AssertionError(
                f"runner exited early with code {process.returncode} before "
                f"reaching the stall point"
            )
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _read_store(backend: str, tmp_path: Path, collection: str):
    if backend == "firestore":
        from baraza.fold.store import FirestoreEventStore

        return FirestoreEventStore(collection=collection)
    return JsonlEventStore(tmp_path / "events.jsonl")


def _backends():
    params = [pytest.param("jsonl", id="jsonl")]
    reason = None
    if not os.environ.get("FIRESTORE_EMULATOR_HOST"):
        reason = "FIRESTORE_EMULATOR_HOST unset; run under scripts/with_emulator.sh"
    else:
        try:
            import google.cloud.firestore  # noqa: F401
        except ImportError:
            reason = "google-cloud-firestore is not installed"
    params.append(
        pytest.param(
            "firestore",
            id="firestore",
            marks=pytest.mark.skipif(reason is not None, reason=reason or ""),
        )
    )
    return params


@pytest.mark.parametrize("backend", _backends())
def test_session_survives_a_real_sigkill_mid_turn(backend, tmp_path):
    collection = f"events_{uuid.uuid4().hex[:12]}"
    marker = tmp_path / "stalled"

    # ---- run 1: interview until the process is parked awaiting an answer ----
    first, first_out, first_err = _spawn(
        tmp_path,
        backend,
        collection,
        "--stall-at", str(STALL_AT),
        "--stall-marker", str(marker),
        tag="first",
    )
    try:
        _wait_for(marker, process=first)
        assert first.poll() is None, "runner should still be waiting for an answer"

        # The kill. SIGKILL cannot be caught, blocked, or handled: nothing in
        # the runner gets to tidy up on the way out.
        os.kill(first.pid, signal.SIGKILL)
        first.wait(timeout=30)
    finally:
        if first.poll() is None:  # pragma: no cover - only on an assertion above
            first.kill()
            first.wait(timeout=10)

    assert first.returncode == -signal.SIGKILL, (
        f"expected death by SIGKILL, got {first.returncode}; "
        f"stderr: {first_err.read_text(encoding='utf-8')[:2000]}"
    )

    before = first_out.read_text(encoding="utf-8").splitlines()
    assert f"OPENED {SESSION_ID}" in before
    assert "ASK t-1" in before and "ANSWER t-2" in before
    assert "ASK t-3" in before and "ANSWER t-4" in before
    assert f"ASK {STALL_QUESTION}" in before
    assert f"SOLICIT {STALL_QUESTION}" in before
    # The answer to the stalled question never happened, in the log or anywhere.
    assert "ANSWER t-6" not in before
    assert "CLOSED" not in before

    # ---- what a cold reader sees of the killed session ----
    store = _read_store(backend, tmp_path, collection)
    killed = SessionStore(store).load(SESSION_ID)
    assert killed is not None
    assert [t.turn_id for t in killed.turns] == ["t-1", "t-2", "t-3", "t-4", "t-5"]
    pending = SessionStore(store).next_unanswered(killed)
    assert pending is not None
    assert pending.turn_id == STALL_QUESTION
    assert pending.role is TurnRole.AGENT

    # ---- run 2: resume ----
    second, second_out, second_err = _spawn(
        tmp_path, backend, collection, "--resume", tag="second"
    )
    second.wait(timeout=120)
    assert second.returncode == 0, second_err.read_text(encoding="utf-8")[:2000]

    after = second_out.read_text(encoding="utf-8").splitlines()

    # Turns 1..n-1 replay: they are read back from the log, not asked again.
    assert "REPLAY t-1 t-2" in after
    assert "REPLAY t-3 t-4" in after
    assert "ASK t-1" not in after
    assert "ASK t-3" not in after

    # Turn n is identified as pending and re-solicited.
    assert f"PENDING {STALL_QUESTION}" in after
    assert f"RE-ASK {STALL_QUESTION}" in after
    # RE-ASK rather than ASK: the append returned False because the question was
    # already durable. Content-addressed IDs are what make that a no-op.
    assert f"ASK {STALL_QUESTION}" not in after

    assert "ANSWER t-6" in after
    assert "CLOSED" in after

    # ---- the log after both runs ----
    store = _read_store(backend, tmp_path, collection)
    finished = SessionStore(store).load(SESSION_ID)
    assert finished is not None
    assert [t.turn_id for t in finished.turns] == [f"t-{i}" for i in range(1, 9)]
    assert SessionStore(store).next_unanswered(finished) is None

    # The re-asked question exists exactly once in the log.
    turn_events = [
        event
        for event in store.read_all()
        if event.event_type is EventType.SESSION_TURN
        and (event.payload.get("turn") or {}).get("turn_id") == STALL_QUESTION
    ]
    assert len(turn_events) == 1

    # And exactly one session was opened, not two.
    opened = [
        event
        for event in store.read_all()
        if event.event_type is EventType.SESSION_OPENED
    ]
    assert len(opened) == 1


def test_the_runner_is_the_real_session_store():
    """Guard against the rig drifting into a simulation of itself.

    If the runner ever stops using ``SessionStore``, this test would keep
    passing while proving nothing about the code that ships.
    """
    source = RUNNER.read_text(encoding="utf-8")
    assert "from baraza.interview.session_store import SessionStore" in source
    assert "sessions.append_turn(" in source
    assert "sessions.next_unanswered(" in source
