"""The append-only event store.

Two backends behind one interface:

* :class:`JsonlEventStore` — a local append-only file. This is what ``make demo``
  runs against, so a judge can clone the repo and see the whole system work
  without a GCP project, credentials, or a network round-trip.
* :class:`FirestoreEventStore` — production. Writes go through ``create()``
  only, and ``deploy/firestore.rules`` rejects update and delete at the database
  level so a bug in application code cannot mutate history even if it tries.

Neither backend exposes update or delete. That is not an oversight to be fixed
later; it is the interface. Fixing bad data means appending a superseding event.

Both backends are idempotent on append, because event IDs are content hashes: a
retried Cloud Run Job re-derives the same IDs and the second write is a no-op
rather than a duplicate. That property is what makes the ingestion Job safe to
retry, which is what makes the nightly schedule safe to run unattended.
"""

from __future__ import annotations

import json
import os
import threading
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator
from pathlib import Path

from baraza.schema.event import Event, EventType

__all__ = [
    "EventStore",
    "JsonlEventStore",
    "FirestoreEventStore",
    "open_store",
]


class EventStore(ABC):
    """Append and read. There is deliberately no update and no delete."""

    @abstractmethod
    def append(self, event: Event) -> bool:
        """Append one event. Returns True if written, False if already present.

        Never raises on a duplicate — a duplicate is the expected outcome of a
        retry, not an error.
        """

    @abstractmethod
    def read_all(self) -> list[Event]:
        """Every event, unordered. The fold sorts; callers must not assume."""

    def append_many(self, events: Iterable[Event]) -> int:
        """Append a batch, returning the number actually written."""
        return sum(1 for event in events if self.append(event))

    def read_by_type(self, *types: EventType) -> list[Event]:
        wanted = set(types)
        return [e for e in self.read_all() if e.event_type in wanted]

    def count_scheduled(self) -> int:
        """Nightly Scheduler runs — a count of nights, not of events.

        Counts scheduled **heartbeats** only. A single scheduled run appends
        several ``scheduled=True`` events (adjudications, tonight's findings,
        the session proposal), but exactly one heartbeat; counting every
        scheduled event would report one night as five runs, which is the same
        inflation defect the flag itself exists to prevent, one level up.

        Kept as its own accessor so that any figure derived from it is
        obviously a count of *scheduled* runs. A scheduled job is never counted
        as organic activity.
        """
        return sum(
            1
            for e in self.read_all()
            if e.scheduled and e.event_type is EventType.HEARTBEAT
        )

    # Explicitly absent: update(), delete(), overwrite(). If you find yourself
    # wanting one, the answer is a superseding event.


class JsonlEventStore(EventStore):
    """Append-only JSONL on the local filesystem.

    One JSON object per line, written with ``O_APPEND`` under a process lock.
    Line-oriented on purpose: a partially written final line from a killed
    process is detectable and skipped on read, which is what lets the
    kill-survival test resume from a real interruption rather than a simulated
    one.
    """

    def __init__(self, path: Path | str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._lock = threading.Lock()
        self._seen: set[str] | None = None

    def _ensure_index(self) -> set[str]:
        if self._seen is None:
            self._seen = {e.event_id for e in self.read_all()}
        return self._seen

    def append(self, event: Event) -> bool:
        with self._lock:
            seen = self._ensure_index()
            if event.event_id in seen:
                return False
            line = json.dumps(event.to_dict(), sort_keys=True, separators=(",", ":"))
            # O_APPEND makes the write atomic up to PIPE_BUF for concurrent
            # writers, and fsync makes it durable across a SIGKILL.
            with open(self.path, "a", encoding="utf-8") as handle:
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            seen.add(event.event_id)
            return True

    def read_all(self) -> list[Event]:
        events: list[Event] = []
        with open(self.path, encoding="utf-8") as handle:
            for lineno, raw in enumerate(handle, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    events.append(Event.from_dict(json.loads(raw)))
                except (json.JSONDecodeError, KeyError):
                    # A torn final line is the signature of a process killed
                    # mid-write. Skipping it is correct: the event was never
                    # durably committed, so the turn it recorded is re-solicited
                    # on resume. Failing in the other direction — accepting a
                    # partial event — would corrupt the fold.
                    if lineno == self._line_count():
                        continue
                    raise
        return events

    def _line_count(self) -> int:
        with open(self.path, encoding="utf-8") as handle:
            return sum(1 for _ in handle)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.read_all())


class FirestoreEventStore(EventStore):
    """Production store. ``create()``-only writes against a rules-locked collection.

    The client is constructed lazily so that importing this module — which the
    offline demo does, transitively — never requires credentials.
    """

    def __init__(self, collection: str = "events", *, project: str | None = None):
        self.collection_name = collection
        self._project = project
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from google.cloud import firestore  # imported lazily, see above

            from baraza.schema.models import project_id

            self._client = firestore.Client(project=self._project or project_id())
        return self._client

    def append(self, event: Event) -> bool:
        from google.api_core import exceptions as gexc

        doc = self.client.collection(self.collection_name).document(event.event_id)
        try:
            # create() fails if the document exists. That is the whole point:
            # the append-only guarantee is enforced by the API call we choose,
            # not by a check-then-write race.
            doc.create(event.to_dict())
            return True
        except gexc.AlreadyExists:
            return False

    def read_all(self) -> list[Event]:
        return [
            Event.from_dict(snapshot.to_dict())
            for snapshot in self.client.collection(self.collection_name).stream()
        ]

    def read_since(self, instant_millis: int) -> list[Event]:
        """Events at or after an instant.

        Queries on the integer field, never on a serialized string — the stored
        form is the comparison form (BAR-309), so a range query on the database
        and a sort in the fold agree by construction.
        """
        query = (
            self.client.collection(self.collection_name)
            .where("occurred_at", ">=", int(instant_millis))
            .order_by("occurred_at")
        )
        return [Event.from_dict(s.to_dict()) for s in query.stream()]


def open_store(
    *, offline: bool = False, path: Path | str | None = None
) -> EventStore:
    """Pick a backend.

    ``offline=True``, or ``BARAZA_OFFLINE=1`` in the environment, selects the
    JSONL store. Everything the offline demo does is the same code path the
    deployed system runs; only the store differs.
    """
    if offline or os.environ.get("BARAZA_OFFLINE") == "1":
        return JsonlEventStore(path or Path("out") / "events.jsonl")
    return FirestoreEventStore()
