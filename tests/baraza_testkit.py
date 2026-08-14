"""Test doubles and log builders shared across the suite.

Two things live here and nothing else.

**A fake ``LLMClient``**, so that no test in this repository requires Vertex
credentials, a GCP project, or a network round-trip. The fake is deliberately
dumb: it returns exactly what a test scripted, records every call, and raises on
an unscripted one. A fake that guessed a plausible response would let a test
pass against model output nobody wrote, which is the same defect class as a
hand-authored cassette pretending to be a recording.

**Small constructors for claims and events**, so a test's setup reads as the
scenario under test rather than as twelve lines of keyword arguments. Every
entity here is a role or a document type — ``ent:treasurer``,
``src:constitution-scan``. No real person, member, or organization is named
anywhere in this repository, including in test fixtures.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from baraza.llm import LLMClient, LLMResponse
from baraza.schema.claim import Anchor, Claim, Provenance, Tier
from baraza.schema.contradiction import Contradiction
from baraza.schema.event import Event, EventType
from baraza.schema.temporal import EpochMillis, to_epoch_millis
from baraza.schema.visibility import Visibility

__all__ = [
    "FakeLLMClient",
    "LLMCall",
    "UnscriptedCall",
    "ms",
    "anchor",
    "claim",
    "asserted",
    "committed",
    "rejected",
    "visibility_set",
    "detected",
    "resolved",
    "alias_linked",
    "heartbeat",
]

# Not a model ID. The compliance lint pins real model literals to
# schema/models.py; a test double must not look like one even by accident.
_FAKE_MODEL = "fake:no-vertex-call"

Scripted = str | Callable[[str], str]


class UnscriptedCall(AssertionError):
    """The code under test made a model call the test did not script.

    An assertion failure rather than a stub response: a silently defaulted
    answer would make the test pass for a reason the test does not state.
    """


@dataclass(frozen=True, slots=True)
class LLMCall:
    """One recorded request. Tests assert on counts and on prompt content."""

    role: str
    prompt: str
    system: str
    schema_name: str
    temperature: float


class FakeLLMClient(LLMClient):
    """Scripted responses keyed by ``schema_name``.

    Keying on the schema name rather than on the prompt text means a test does
    not have to reproduce prompt wording it does not care about, while still
    failing loudly when a call site starts asking a question the test never
    anticipated.
    """

    def __init__(
        self,
        responses: Mapping[str, Scripted] | None = None,
        *,
        default: str | None = None,
        chunks: Sequence[str] | None = None,
    ):
        self.responses: dict[str, Scripted] = dict(responses or {})
        self.default = default
        self.chunks = list(chunks or [])
        self.calls: list[LLMCall] = []

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
        self.calls.append(
            LLMCall(
                role=role,
                prompt=prompt,
                system=system,
                schema_name=schema_name,
                temperature=temperature,
            )
        )
        body = self.responses.get(schema_name, self.default)
        if body is None:
            raise UnscriptedCall(
                f"unscripted model call: role={role!r} schema={schema_name!r}\n"
                f"  prompt begins: {prompt.strip()[:200]!r}\n"
                "  Script it in FakeLLMClient(responses={...}) or pass default=."
            )
        if callable(body):
            body = body(prompt)
        return LLMResponse(
            text=body,
            model_id=_FAKE_MODEL,
            role=role,
            source="fake",
            latency_ms=0,
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
        self.calls.append(
            LLMCall(
                role=role,
                prompt=prompt,
                system=system,
                schema_name="",
                temperature=temperature,
            )
        )
        yield from self.chunks

    # ------------------------------------------------------------- assertions

    def calls_for(self, schema_name: str) -> list[LLMCall]:
        return [c for c in self.calls if c.schema_name == schema_name]


# ------------------------------------------------------------------- builders


def ms(value: Any) -> EpochMillis:
    """Normalize a test's instant. Epoch millis is the only comparison key."""
    return to_epoch_millis(value, field="test-fixture")


def anchor(
    source_id: str = "src:constitution-scan", locator: str = "p.1 ¶1"
) -> Anchor:
    return Anchor(source_id=source_id, locator=locator)


def claim(
    *,
    subject: str = "ent:treasurer",
    predicate: str = "signing_threshold",
    hint: str = "signing authority",
    quote: str = "The treasurer may sign for amounts up to five hundred.",
    object_id: str | None = None,
    object_literal: str | None = "500",
    observed_at: Any = "2026-04-01T00:00:00Z",
    valid_from: Any = None,
    valid_until: Any = None,
    tier: Tier = Tier.PENDING,
    visibility: Visibility | None = None,
    provenance: Provenance = Provenance.CORPUS,
    source_id: str = "src:constitution-scan",
    locator: str = "p.1 ¶1",
    extra: dict[str, Any] | None = None,
) -> Claim:
    """A claim with defaults that make the interesting field the only one set."""
    return Claim.create(
        subject_id=subject,
        predicate=predicate,
        predicate_hint=hint,
        quote=quote,
        anchor=anchor(source_id, locator),
        observed_at=observed_at,
        object_id=object_id,
        object_literal=object_literal,
        valid_from=valid_from,
        valid_until=valid_until,
        tier=tier,
        visibility=visibility,
        provenance=provenance,
        extra=extra,
    )


def asserted(c: Claim, at: Any = None, *, actor: str = "extractor") -> Event:
    return Event.create(
        event_type=EventType.CLAIM_ASSERTED,
        occurred_at=at if at is not None else c.observed_at,
        payload={"claim": c.to_dict()},
        actor=actor,
    )


def committed(claim_id: str, at: Any, *, actor: str = "approval") -> Event:
    return Event.create(
        event_type=EventType.CLAIM_COMMITTED,
        occurred_at=at,
        payload={"claim_id": claim_id},
        actor=actor,
    )


def rejected(claim_id: str, at: Any, *, actor: str = "approval") -> Event:
    return Event.create(
        event_type=EventType.CLAIM_REJECTED,
        occurred_at=at,
        payload={"claim_id": claim_id},
        actor=actor,
    )


def visibility_set(claim_id: str, value: Any, at: Any) -> Event:
    """``value`` is passed through unchanged so a test can plant garbage."""
    raw = value.value if isinstance(value, Visibility) else value
    return Event.create(
        event_type=EventType.CLAIM_VISIBILITY_SET,
        occurred_at=at,
        payload={"claim_id": claim_id, "visibility": raw},
        actor="approval",
    )


def detected(contradiction: Contradiction, at: Any) -> Event:
    return Event.create(
        event_type=EventType.CONTRADICTION_DETECTED,
        occurred_at=at,
        payload={"contradiction": contradiction.to_dict()},
        actor="reconcile",
    )


def resolved(
    contradiction_id: str, at: Any, *, session_id: str | None = None
) -> Event:
    return Event.create(
        event_type=EventType.CONTRADICTION_RESOLVED,
        occurred_at=at,
        payload={"contradiction_id": contradiction_id, "session_id": session_id},
        actor="approval",
    )


def alias_linked(alias_id: str, canonical_id: str, at: Any) -> Event:
    return Event.create(
        event_type=EventType.ENTITY_ALIAS_LINKED,
        occurred_at=at,
        payload={"alias_id": alias_id, "canonical_id": canonical_id},
        actor="entities",
    )


def heartbeat(at: Any, *, scheduled: bool = True) -> Event:
    """Scheduled by default — a heartbeat that is not a scheduled run is a bug."""
    return Event.create(
        event_type=EventType.HEARTBEAT,
        occurred_at=at,
        payload={"mode": "stub"},
        actor="reconcile-job",
        scheduled=scheduled,
    )
