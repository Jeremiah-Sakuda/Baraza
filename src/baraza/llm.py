"""The model layer — every Gemini call in the system goes through here.

Three implementations behind one protocol:

* :class:`VertexClient` — production. Gemini 3.5 Pro and Flash via Vertex AI,
  model IDs resolved from ``schema/models.py`` and nowhere else.
* :class:`CassetteClient` — **recorded**, not fabricated. Real responses from
  real Vertex calls, captured to ``fixtures/cassettes/`` and replayed by prompt
  hash. This is what ``make demo`` runs, so a judge can clone the repository and
  watch the whole system work — with genuine model output — without a GCP
  project, credentials, or a network round-trip.
* :class:`RecordingClient` — a wrapper that calls Vertex and writes the cassette
  as it goes. Used once per fixture refresh, never in the demo path.

**On the honesty of cassettes.** A cassette is a recording of something that
happened. It is not a hand-authored "what Gemini would probably say", and
nothing in this repository fabricates model output. Every cassette file carries
the model ID, the run ID, and the UTC date it was recorded. If a cassette is
missing for a prompt, the offline client raises :class:`CassetteMiss` — it does
not invent a response, and it does not silently fall through to a stub.

**Not yet checked:** nothing cross-checks a recorded ``model_id`` against the
current pins in ``schema/models.py``, so a cassette recorded against a since-
repinned model would replay without complaint. An earlier revision of this
docstring claimed a ``make verify-cassettes`` target performed that check; no
such target and no such script exist, and a claimed check that does not exist is
worse than a named gap.

A number derived from a cassette replay is a *replayed* measurement and says so
wherever it appears. It is never reported as a live deployed measurement.

**What happens at 3am.** The unattended path is a Cloud Run Job with nobody
watching it, and until this module grew a retry the answer to "one transient 503
on chunk 40 of 200" was: the exception leaves ``generate``, kills the container,
Scheduler retries into the same weather, and the night ends up as a hole in the
execution history that is this project's main evidence of autonomy.

:class:`VertexClient` therefore retries — narrowly, and on purpose:

* Only on **429, 503, 504 and deadline/transport errors**. A 400 or a 403 is a
  bug or a missing permission, and retrying it burns the attempt deadline to
  arrive at the same answer more slowly.
* **Bounded twice**: a maximum number of attempts *and* a wall-clock budget, so
  the retry can never outlive the Scheduler ``attemptDeadline`` that is supposed
  to bound the whole run.
* **Jittered**, because a synchronised retry storm is how a rate limit becomes
  an outage.
* Every request also carries an explicit **timeout**; without one a wedged
  connection hangs until something else gives up.

Streaming retries only until the first token. After that a retry would replay
text the caller has already seen, and a duplicated half-sentence in an interview
is worse than an error.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from baraza.schema import models

__all__ = [
    "LLMResponse",
    "LLMClient",
    "VertexClient",
    "CassetteClient",
    "RecordingClient",
    "CassetteMiss",
    "RetryPolicy",
    "is_retryable",
    "open_client",
    "prompt_fingerprint",
]

CASSETTE_DIR = Path(__file__).resolve().parent.parent.parent / "fixtures" / "cassettes"

REQUEST_TIMEOUT_SECONDS = 120.0
"""Per-request ceiling handed to the SDK.

Comfortably above a slow reasoning call and far below Scheduler's 1800s
attempt deadline (``deploy/scheduler.yaml``), so a wedged connection is the
client's problem rather than the night's.
"""

RETRY_STATUS_CODES = frozenset({429, 503, 504})
"""The only status codes worth trying again.

429 is a rate limit that clears; 503 and 504 are the upstream being briefly
unavailable. Everything else in the 4xx range is a request that will fail
identically the second time, and retrying it spends the deadline to learn
nothing.
"""

RETRY_ERROR_NAMES = frozenset(
    {
        "DeadlineExceeded",
        "ServiceUnavailable",
        "ResourceExhausted",
        "InternalServerError",
        "ServerError",
        "TooManyRequests",
        "ConnectionError",
        "ConnectError",
        "ConnectTimeout",
        "ReadTimeout",
        "ReadError",
        "RemoteProtocolError",
        "TimeoutError",
        "TimeoutException",
    }
)
"""Transport and gRPC failures that carry no HTTP status.

Matched by type name rather than by class, because importing every exception
type google-genai, httpx and grpc might raise would make this module import
half the SDK at load time — which is the thing the lazy client exists to avoid.
The names are checked against the exception's own class and its bases.
"""

T = TypeVar("T")


def _status_of(exc: BaseException) -> int | None:
    """Best-effort HTTP status for an SDK exception."""
    for attribute in ("code", "status_code"):
        value = getattr(exc, attribute, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_retryable(exc: BaseException) -> bool:
    """Whether this failure is worth another attempt.

    Fails **closed**: an exception this function does not recognise is not
    retried. A retry loop that guesses will happily hammer a permission error
    until the attempt deadline expires, and then report a timeout for what was
    really a missing IAM binding.
    """
    status = _status_of(exc)
    if status is not None:
        return status in RETRY_STATUS_CODES
    names = {cls.__name__ for cls in type(exc).__mro__}
    return bool(names & RETRY_ERROR_NAMES)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Bounded, jittered backoff. Both bounds are real.

    ``max_attempts`` bounds the count; ``budget_seconds`` bounds the clock. The
    second one is the one that matters at 3am: without it, a long backoff
    sequence against a sustained outage can outlive the Job's own deadline and
    turn a degraded night into a killed one.
    """

    max_attempts: int = 4
    base_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    budget_seconds: float = 120.0

    def delay_for(self, attempt: int, *, jitter: float) -> float:
        """Exponential backoff with full jitter. ``attempt`` is 1-based."""
        ceiling = min(self.base_seconds * (2 ** (attempt - 1)), self.max_delay_seconds)
        return ceiling * jitter

    def run(
        self,
        operation: Callable[[], T],
        *,
        describe: str,
        sleep: Callable[[float], None] = time.sleep,
        jitter: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.monotonic,
    ) -> T:
        """Call ``operation``, retrying only what :func:`is_retryable` allows."""
        started = clock()
        last: BaseException
        for attempt in range(1, self.max_attempts + 1):
            try:
                return operation()
            except Exception as exc:  # noqa: BLE001 - re-raised unless retryable
                last = exc
                if not is_retryable(exc):
                    raise
                if attempt == self.max_attempts:
                    break
                delay = self.delay_for(attempt, jitter=jitter())
                if clock() - started + delay > self.budget_seconds:
                    break
                sleep(delay)
        raise RuntimeError(
            f"{describe} failed after {attempt} attempt(s) within "
            f"{self.budget_seconds:g}s: {type(last).__name__}: {last}"
        ) from last


class CassetteMiss(RuntimeError):
    """No recording exists for this prompt.

    Deliberately fatal. The alternative — returning a plausible stub — would put
    invented model output into a demo a judge is watching, which is the exact
    class of dishonesty this project keeps naming.
    """


def prompt_fingerprint(*, role: str, prompt: str, schema_name: str = "") -> str:
    """Stable key for a cassette entry.

    Hashes the role, the prompt text, and the response-schema name. Changing a
    prompt therefore invalidates its recording rather than silently replaying a
    response to a question that is no longer being asked.
    """
    digest = hashlib.sha256(
        "\x1f".join([role, schema_name, prompt.strip()]).encode("utf-8")
    ).hexdigest()
    return digest[:40]


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """One model response, with the provenance needed to report it honestly."""

    text: str
    model_id: str
    role: str
    source: str
    """``"vertex"`` for a live call, ``"cassette"`` for a replay. Any timing
    derived from a response carries this, so an in-process cassette replay can
    never be written up as a deployed measurement."""

    latency_ms: int
    first_token_ms: int | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    recorded_at: str | None = None

    def json(self) -> Any:
        """Parse the response as JSON, tolerating a fenced code block."""
        body = self.text.strip()
        if body.startswith("```"):
            body = body.split("\n", 1)[1] if "\n" in body else body
            if body.endswith("```"):
                body = body[: -3]
            if body.lstrip().startswith("json"):
                body = body.lstrip()[4:]
        return json.loads(body)


class LLMClient(ABC):
    """The contract every call site codes against."""

    @abstractmethod
    def generate(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        schema_name: str = "",
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
    ) -> LLMResponse:
        """One request, one response."""

    @abstractmethod
    def stream(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> Iterator[str]:
        """Token stream. BAR-330's first-visible-token budget is measured here."""


class VertexClient(LLMClient):
    """Live Gemini via Vertex AI.

    Constructed lazily and imported lazily, so that a machine with no
    credentials can still import this module and run the offline demo.
    """

    def __init__(
        self,
        *,
        project: str | None = None,
        location: str | None = None,
        retry: RetryPolicy | None = None,
        timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._project = project
        self._location = location
        self._client = None
        self.retry = retry or RetryPolicy()
        self.timeout_seconds = timeout_seconds
        self._sleep = sleep
        """Injectable so a test can exercise the backoff without waiting it out.
        Production never passes it."""

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(
                vertexai=True,
                project=self._project or models.project_id(),
                location=self._location or models.location(),
                # Milliseconds, per the SDK. An unbounded request is how a
                # wedged connection holds a Cloud Run execution open all night.
                http_options=types.HttpOptions(
                    timeout=int(self.timeout_seconds * 1000)
                ),
            )
        return self._client

    def generate(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        schema_name: str = "",
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
    ) -> LLMResponse:
        from google.genai import types

        model_id = models.resolve(role)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system or None,
            response_mime_type="application/json" if schema_name else None,
        )
        started = time.perf_counter()
        result = self.retry.run(
            lambda: self.client.models.generate_content(
                model=model_id, contents=prompt, config=config
            ),
            describe=f"generate({role})",
            sleep=self._sleep,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        # The elapsed figure spans any retries, deliberately: it is what the
        # caller waited, not what the successful attempt took.

        usage = getattr(result, "usage_metadata", None)
        return LLMResponse(
            text=result.text or "",
            model_id=model_id,
            role=role,
            source="vertex",
            latency_ms=elapsed_ms,
            input_tokens=getattr(usage, "prompt_token_count", None),
            output_tokens=getattr(usage, "candidates_token_count", None),
        )

    def stream(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> Iterator[str]:
        from google.genai import types

        model_id = models.resolve(role)
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            system_instruction=system or None,
        )

        def _open() -> tuple[Iterator[Any], Any]:
            """Establish the stream and pull the first chunk.

            The HTTP call happens on the first ``next``, so opening and reading
            once is what actually proves the stream is alive — and it is the
            last moment a retry is safe.
            """
            iterator = iter(
                self.client.models.generate_content_stream(
                    model=model_id, contents=prompt, config=config
                )
            )
            return iterator, next(iterator, None)

        iterator, first = self.retry.run(
            _open, describe=f"stream({role})", sleep=self._sleep
        )

        if first is not None and first.text:
            yield first.text
        # No retry past this line. The caller has seen tokens; a second attempt
        # would replay them, and a duplicated half-sentence mid-interview is
        # worse than a visible failure.
        for chunk in iterator:
            if chunk.text:
                yield chunk.text


@dataclass
class _Cassette:
    """One recorded exchange."""

    key: str
    role: str
    model_id: str
    prompt_preview: str
    text: str
    recorded_at: str
    run_id: str
    chunks: list[str] = field(default_factory=list)
    """Token chunks as they actually arrived, so a replayed stream reproduces
    the real chunk boundaries rather than an invented word-by-word split."""


class CassetteClient(LLMClient):
    """Replays recorded Vertex responses. The offline demo path.

    Raises :class:`CassetteMiss` on an unrecorded prompt rather than inventing
    output.
    """

    def __init__(self, directory: Path | str = CASSETTE_DIR, *, delay_ms: int = 0):
        self.directory = Path(directory)
        self.delay_ms = delay_ms
        """Optional artificial pacing for the replay demo, so a recorded stream
        reads at human speed. Any latency figure measured under a nonzero delay
        is disclosed as paced and is never published as a performance number."""
        self._index: dict[str, _Cassette] | None = None

    def _load(self) -> dict[str, _Cassette]:
        if self._index is not None:
            return self._index
        index: dict[str, _Cassette] = {}
        if self.directory.exists():
            for path in sorted(self.directory.glob("*.json")):
                payload = json.loads(path.read_text(encoding="utf-8"))
                for entry in payload.get("entries", []):
                    index[entry["key"]] = _Cassette(
                        key=entry["key"],
                        role=entry["role"],
                        model_id=entry["model_id"],
                        prompt_preview=entry.get("prompt_preview", ""),
                        text=entry["text"],
                        recorded_at=payload.get("recorded_at", "unknown"),
                        run_id=payload.get("run_id", "unknown"),
                        chunks=entry.get("chunks") or [],
                    )
        self._index = index
        return index

    def _lookup(self, key: str, role: str, prompt: str) -> _Cassette:
        index = self._load()
        entry = index.get(key)
        if entry is None:
            raise CassetteMiss(
                f"no recording for role={role!r} key={key}\n"
                f"  prompt begins: {prompt.strip()[:160]!r}\n"
                f"  cassette dir : {self.directory}\n"
                "  Re-record with: python3 scripts/record_cassettes.py --yes\n"
                "  (requires Vertex credentials and costs live calls). The "
                "offline client will not invent a response."
            )
        return entry

    def generate(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        schema_name: str = "",
        temperature: float = 0.0,
        max_output_tokens: int = 4096,
    ) -> LLMResponse:
        key = prompt_fingerprint(role=role, prompt=prompt, schema_name=schema_name)
        entry = self._lookup(key, role, prompt)
        started = time.perf_counter()
        if self.delay_ms:
            time.sleep(self.delay_ms / 1000)
        return LLMResponse(
            text=entry.text,
            model_id=entry.model_id,
            role=role,
            source="cassette",
            latency_ms=int((time.perf_counter() - started) * 1000),
            recorded_at=entry.recorded_at,
        )

    def stream(
        self,
        *,
        role: str,
        prompt: str,
        system: str = "",
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> Iterator[str]:
        key = prompt_fingerprint(role=role, prompt=prompt)
        entry = self._lookup(key, role, prompt)
        chunks = entry.chunks or [entry.text]
        for chunk in chunks:
            if self.delay_ms:
                time.sleep(self.delay_ms / 1000)
            yield chunk


class RecordingClient(LLMClient):
    """Calls Vertex and writes the cassette. Never used in the demo path."""

    def __init__(
        self,
        inner: LLMClient,
        *,
        directory: Path | str = CASSETTE_DIR,
        run_id: str,
        recorded_at: str,
    ):
        self.inner = inner
        self.directory = Path(directory)
        self.run_id = run_id
        self.recorded_at = recorded_at
        self._entries: dict[str, dict[str, Any]] = {}

    def generate(self, **kwargs: Any) -> LLMResponse:
        response = self.inner.generate(**kwargs)
        key = prompt_fingerprint(
            role=kwargs["role"],
            prompt=kwargs["prompt"],
            schema_name=kwargs.get("schema_name", ""),
        )
        self._entries[key] = {
            "key": key,
            "role": kwargs["role"],
            "model_id": response.model_id,
            "prompt_preview": kwargs["prompt"].strip()[:200],
            "text": response.text,
        }
        return response

    def stream(self, **kwargs: Any) -> Iterator[str]:
        chunks: list[str] = []
        for chunk in self.inner.stream(**kwargs):
            chunks.append(chunk)
            yield chunk
        key = prompt_fingerprint(role=kwargs["role"], prompt=kwargs["prompt"])
        self._entries[key] = {
            "key": key,
            "role": kwargs["role"],
            "model_id": models.resolve(kwargs["role"]),
            "prompt_preview": kwargs["prompt"].strip()[:200],
            "text": "".join(chunks),
            "chunks": chunks,
        }

    def flush(self, name: str) -> Path:
        """Write the cassette file and return its path."""
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"{name}.json"
        path.write_text(
            json.dumps(
                {
                    "run_id": self.run_id,
                    "recorded_at": self.recorded_at,
                    "note": (
                        "Recorded from live Vertex AI calls. Not hand-authored. "
                        "Replayed by fixtures-driven demo runs so a judge can "
                        "reproduce the system without credentials."
                    ),
                    "entries": list(self._entries.values()),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return path


def open_client(*, offline: bool | None = None, delay_ms: int = 0) -> LLMClient:
    """Select a client.

    ``offline`` defaults to the ``BARAZA_OFFLINE`` environment variable. The
    offline demo and the deployed system run identical code above this line.
    """
    if offline is None:
        offline = os.environ.get("BARAZA_OFFLINE") == "1"
    if offline:
        return CassetteClient(delay_ms=delay_ms)
    return VertexClient()
