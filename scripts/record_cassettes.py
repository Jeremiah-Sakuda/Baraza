#!/usr/bin/env python3
"""Record ``fixtures/cassettes/`` from live Vertex AI.

A cassette is a **recording of something that happened**. Nothing in this
repository hand-authors model output, and the offline client raises rather than
inventing a response when a recording is missing. That guarantee is only worth
anything if the recordings come from somewhere real, which is what this script
is.

**It records by running the demo, not by replaying a prompt list.** A curated
list of prompts drifts from the prompts the code actually issues, and the first
symptom is a cassette miss in front of a judge. So this script drives the same
stages ``make demo`` drives — ingest with on-write detection, agenda generation,
a replay partner session per script, approval, and the dossier query — with a
:class:`RecordingClient` wrapped around a live :class:`VertexClient`. Every
prompt the demo will issue is therefore issued once, for real, and captured with
its response.

**It costs money and it says so.** Live calls against a real project are not a
side effect to discover afterwards, so the run refuses to start without an
explicit ``--yes`` or an interactive confirmation naming the project.

**It never runs in the demo path.** ``make demo`` uses the recordings; only a
supervised refresh uses this.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
import uuid
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

REPO = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CANNOT_RUN = 2


def main(argv: Sequence[str]) -> int:
    from baraza import cli
    from baraza.llm import CASSETTE_DIR, RecordingClient, VertexClient
    from baraza.schema import models
    from baraza.schema.visibility import Audience, Visibility

    parser = argparse.ArgumentParser(
        description="Record fixtures/cassettes/ by driving the demo against live Vertex."
    )
    parser.add_argument("--corpus", type=Path, default=cli.DEFAULT_CORPUS_MANIFEST)
    parser.add_argument(
        "--store",
        type=Path,
        default=REPO / "out" / "record-events.jsonl",
        help="event log for the recording run; kept separate from the demo's log "
        "so a recording pass never mixes into the demo's history",
    )
    parser.add_argument("--out", type=Path, default=CASSETTE_DIR)
    parser.add_argument("--name", default="demo", help="cassette file stem")
    parser.add_argument(
        "--script",
        action="append",
        default=None,
        help="script to replay; repeatable. Defaults to every fixture present, "
        "because a script whose prompts were never recorded is a cassette miss "
        "waiting to happen.",
    )
    parser.add_argument("--items", type=int, default=4)
    parser.add_argument("--agenda-size", type=int, default=12)
    parser.add_argument(
        "--yes", action="store_true", help="skip the confirmation prompt"
    )
    args = parser.parse_args(argv)

    console = cli.Console()

    try:
        project = models.project_id()
    except RuntimeError as exc:
        console.fail(f"cannot run: {exc}")
        return EXIT_CANNOT_RUN

    location = models.location()
    scripts = args.script or [
        p.stem for p in sorted((REPO / "fixtures" / "interviews").glob("*.json"))
    ]
    if not scripts:
        console.fail("cannot run: no script fixtures in fixtures/interviews/")
        return EXIT_CANNOT_RUN

    console.title(
        "BARAZA — cassette recording",
        f"live Vertex calls against {project} ({location})",
    )
    console.detail(f"corpus     {args.corpus}")
    console.detail(f"scripts    {', '.join(scripts)}")
    console.detail(f"output     {args.out}")
    console.warn(
        "This makes real, billable model calls. It is a supervised refresh, not "
        "part of make demo."
    )

    if not args.yes:
        try:
            reply = input(f"   record against project {project}? [y/N] ").strip().lower()
        except EOFError:
            reply = ""
        if reply not in ("y", "yes"):
            console.fail("aborted; nothing recorded")
            return EXIT_CANNOT_RUN

    run_id = f"rec-{_dt.datetime.now(_dt.UTC):%Y%m%dT%H%M%SZ}-{uuid.uuid4().hex[:6]}"
    recorded_at = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")

    recorder = RecordingClient(
        VertexClient(),
        directory=args.out,
        run_id=run_id,
        recorded_at=recorded_at,
    )
    store = cli.build_store(offline=True, path=args.store)
    audience = Audience.OWNER

    try:
        cli.stage_ingest(
            console,
            client=recorder,
            store=store,
            manifest=args.corpus,
            offline=False,
            # Explicit, and load-bearing. A live run defaults to the ADK agent
            # path, whose calls go through the framework's own model layer and
            # therefore past the RecordingClient wrapped around VertexClient —
            # nothing would be captured and `make demo` would miss on every
            # extraction prompt. The recorder records the direct path because
            # the direct path is what the offline demo replays.
            agent_extraction=False,
        )
        state, agenda = cli.stage_agenda(
            console,
            client=recorder,
            store=store,
            audience=audience,
            size=args.agenda_size,
        )
        if not agenda.items:
            console.fail(
                "the agenda came back empty, so the interview prompts cannot be "
                "recorded. Nothing was flushed."
            )
            return EXIT_FAILED

        last_session = None
        for script in scripts:
            _result, last_session = cli.stage_replay_interview(
                console,
                client=recorder,
                store=store,
                agenda=agenda,
                script_name=script,
                audience=audience,
                speed=0.0,
                paced=False,
                max_items=args.items,
                # A recording run must not overwrite the committed transcripts:
                # those are the evidence for the published metric and they are
                # generated by the demo path, not by this one.
                transcript_dir=REPO / "out" / "recording-transcripts",
            )

        if last_session is not None:
            cli.stage_approval(
                console,
                client=recorder,
                state=state,
                store=store,
                agenda=agenda,
                session=last_session,
                audience=audience,
                visibility=Visibility.SUCCESSOR,
            )
        cli.stage_dossier_query(
            console,
            client=recorder,
            store=store,
            question=cli.DEFAULT_SUCCESSOR_QUESTION,
            refusal_probe=cli.DEFAULT_REFUSAL_PROBE,
        )
    except Exception as exc:  # noqa: BLE001
        # Flush whatever was captured before the failure. A partial cassette is
        # useful — it shortens the next attempt — and it cannot be mistaken for
        # a complete one, because the demo will raise CassetteMiss on the first
        # prompt that is absent.
        path = recorder.flush(args.name)
        console.fail(f"recording stopped: {exc}")
        console.warn(f"partial cassette flushed to {path}")
        return EXIT_FAILED

    path = recorder.flush(args.name)
    console.line()
    console.ok(f"cassette written    {path}")
    console.detail(f"run_id              {run_id}")
    console.detail(f"recorded_at         {recorded_at}")
    console.note(
        "      Recorded from live calls. Verify the offline path now replays "
        "clean: make demo"
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
