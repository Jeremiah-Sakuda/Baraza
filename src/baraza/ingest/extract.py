"""Claim extraction — turning a chunk into citation-bearing claims.

The extractor is given a chunk whose every line is prefixed with its locator,
and is instructed to return, for each claim, an ``anchor`` chosen from **that
closed set**. It cannot invent a citation because it is not asked to produce one
— it is asked to select one.

Three validation gates run on every returned claim, in this order, and a claim
that fails any of them is dropped with a named reason rather than repaired:

1. **Anchor membership.** The anchor must be one of the chunk's locators. A
   model that returns ``p.9 ¶1`` for a chunk containing only page 4 has
   hallucinated, and the claim is discarded.
2. **Quote grounding.** The quote must actually appear in the cited unit, after
   whitespace normalization. This catches the subtler failure where the anchor
   is real but the quote is a paraphrase.
3. **Schema validity.** Mandatory quote, resolvable interval, an object of some
   kind. Enforced by ``Claim.create`` itself, so it cannot be skipped.

Rejected extractions are counted and reported. A silent drop rate is
indistinguishable from a working extractor, so the pipeline prints both.

**Two execution paths, one set of gates.**

:class:`ClaimExtractor` issues one direct ``llm.py`` call per chunk and parses
the JSON it returns. :class:`AgentClaimExtractor` runs the ADK extractor agent
from ``baraza.agents`` over the same chunk, with ``read_chunk`` and
``propose_claim`` bound to the real chunk and the real gates. Both funnel every
candidate through :func:`build_claim`, so there is exactly one implementation of
"is this claim citable" and the two paths cannot drift into disagreeing about
what a valid claim is.

The paths differ in *who decides when to stop*. The direct path asks once and
takes what comes back. The agent path lets the model call ``propose_claim``
until it says it is done, bounded by a turn ceiling and a wall-clock timeout,
with each rejection returned to the model as a structured refusal it can react
to rather than as an exception. Which path runs is chosen by
``IngestionPipeline``; see its ``agent_extraction`` argument.

**A third extraction path mines the user, not the corpus.**

:func:`extract_beliefs` reads one user turn from a working session and returns
belief claims — the operating rules the user states about how their work should
be done. It targets *judgment shape*: conditions, thresholds, exceptions,
scope. A bare style preference ("keep it concise") is instructed away and,
when the model returns one anyway as an unconditional tone rule, gated away
mechanically. The same three-gate discipline applies — the quote must appear
verbatim in the turn (whitespace-normalized), the ``predicate_hint`` must come
from the closed :data:`BELIEF_TAXONOMY`, and ``Claim.create`` enforces schema
validity — and a candidate failing any gate is dropped with a named reason,
never repaired.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from baraza.agents import (
    AGENT_TIMEOUT_SECONDS,
    MAX_AGENT_TURNS,
    BarazaAgents,
    ToolResult,
    TurnCeilingExceeded,
    agent_run_config,
    build_extractor,
    open_runner,
)
from baraza.ingest.chunking import Chunk
from baraza.ingest.sources import Source, SourceRegistry
from baraza.llm import LLMClient
from baraza.schema.claim import Anchor, CitationError, Claim, Provenance, Tier
from baraza.schema.temporal import TemporalError
from baraza.schema.visibility import Visibility

__all__ = [
    "ExtractionResult",
    "ClaimExtractor",
    "AgentClaimExtractor",
    "build_claim",
    "EXTRACTION_SCHEMA_NAME",
    "BELIEF_SCHEMA_NAME",
    "BELIEF_TAXONOMY",
    "USER_ENTITY_ID",
    "BeliefExtractionResult",
    "BeliefExtractor",
    "extract_beliefs",
]

EXTRACTION_SCHEMA_NAME = "claims.v1"

_SYSTEM = """\
You extract durable institutional facts from a student organization's records \
and return them as structured claims. You are a careful archivist, not a \
summarizer: you record what a document says, including where it contradicts \
another document, and you never smooth over a discrepancy.

Rules you never break:

* Every claim cites exactly one anchor, and that anchor MUST be copied verbatim \
from the bracketed locators in the excerpt. Never construct a locator.
* Every claim carries a quote that appears VERBATIM in the cited line. Copy it; \
do not paraphrase, do not correct spelling, do not expand abbreviations.
* If a line states a period of validity ("for the 2024-25 year", "until the \
spring election"), record it. If it does not, leave the interval null. Never \
infer a period from context.
* Record what the document asserts, not what is true. Two documents disagreeing \
is the most valuable thing you can find; extract BOTH sides faithfully.
* If a line contains no durable fact, return no claim for it. An empty result is \
a valid and common answer.
"""

_PROMPT = """\
Extract every durable institutional fact from the excerpt below.

Return JSON only, matching this shape exactly:

{{
  "claims": [
    {{
      "subject": "a short noun phrase naming who or what the fact is about",
      "predicate": "a short verb phrase naming the relation",
      "predicate_hint": "2-4 lowercase words categorising the relation, used for \
grouping related claims across documents (e.g. 'signing authority', 'dues \
amount', 'officer term')",
      "object": "the value, entity, or amount asserted",
      "quote": "verbatim text from the cited line",
      "anchor": "one of the bracketed locators, copied exactly",
      "valid_from": "ISO-8601 with offset, or null",
      "valid_until": "ISO-8601 with offset, or null"
    }}
  ]
}}

Valid anchors for this excerpt — you must choose from these and no others:
{locators}

Excerpt:
{text}
"""


@dataclass(slots=True)
class ExtractionResult:
    """Claims and, just as importantly, what was thrown away and why."""

    claims: list[Claim] = field(default_factory=list)
    rejected: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    chunks_processed: int = 0
    raw_returned: int = 0

    @property
    def call_failures(self) -> int:
        """Chunks whose extraction call never returned a claim to judge.

        Counted apart from claim-level rejections because they are a different
        event: a rejected claim is the gates working, a failed call is a chunk
        nobody got to look at.
        """
        return sum(
            1 for reason, _ in self.rejected if reason.startswith("extraction-call-failed")
        )

    @property
    def rejection_rate(self) -> float | None:
        """Claim-level rejections over claims returned.

        Call failures are excluded from the numerator on purpose: they produce
        no returned claim, so counting them here would let the rate exceed 100%
        and stop being a rate.
        """
        if self.raw_returned == 0:
            return None
        return round((len(self.rejected) - self.call_failures) / self.raw_returned, 4)

    def describe(self) -> str:
        rate = self.rejection_rate
        rate_text = "n/a" if rate is None else f"{rate:.1%}"
        failures = self.call_failures
        line = (
            f"extraction: {len(self.claims)} claims kept from {self.raw_returned} "
            f"returned across {self.chunks_processed} chunks "
            f"({len(self.rejected) - failures} rejected, {rate_text})"
        )
        if failures:
            line += f"; {failures} chunk(s) lost to a failed extraction call"
        return line

    def rejection_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reason, _ in self.rejected:
            key = reason.split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


class ClaimExtractor:
    """One extraction call per chunk, with every result verified against source.

    The extractor writes claims at tier ``pending`` and visibility ``private``,
    and it has no code path that writes ``committed``. That is enforced twice:
    here, by never constructing a committed claim, and in production by the
    extractor's service account lacking permission to write the promotion event
    at all. The IAM binding is the real control; this is the readable one.
    """

    def __init__(self, client: LLMClient, registry: SourceRegistry):
        self.client = client
        self.registry = registry

    def extract_chunk(self, chunk: Chunk) -> ExtractionResult:
        result = ExtractionResult(chunks_processed=1)

        locator_list = "\n".join(f"  [{loc}]" for loc in chunk.locators)
        prompt = _PROMPT.format(locators=locator_list, text=chunk.text)

        response = self.client.generate(
            role="fast",
            prompt=prompt,
            system=_SYSTEM,
            schema_name=EXTRACTION_SCHEMA_NAME,
            temperature=0.0,
        )

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            result.rejected.append(
                ("unparseable-response", {"error": str(exc), "chunk": chunk.chunk_id})
            )
            return result

        raw_claims = payload.get("claims") or []
        result.raw_returned = len(raw_claims)

        allowed = set(chunk.locators)
        for raw in raw_claims:
            claim, reason = self._build(raw, chunk, allowed)
            if claim is None:
                result.rejected.append((reason, raw))
            else:
                result.claims.append(claim)
        return result

    def _build(
        self, raw: dict[str, Any], chunk: Chunk, allowed: set[str]
    ) -> tuple[Claim | None, str]:
        return build_claim(raw, chunk, allowed, self.registry)


def build_claim(
    raw: dict[str, Any],
    chunk: Chunk,
    allowed: set[str],
    registry: SourceRegistry,
) -> tuple[Claim | None, str]:
    """The three gates, in order. The only place a claim is built.

    Module-level rather than a method because both execution paths need it and
    a second copy — one for the direct call, one for the agent's tool — is how
    the two paths would come to disagree about what a valid claim is.

    Returns ``(claim, "")`` on acceptance and ``(None, reason)`` on rejection.
    It never raises for a bad claim: the agent path turns the reason into a
    structured refusal the model can act on, and a raised exception there would
    be an opaque failure whose usual sequel is the model retrying the same call.
    """
    anchor_locator = (raw.get("anchor") or "").strip().strip("[]")

    # Gate 1 — anchor membership.
    if anchor_locator not in allowed:
        return None, (
            f"anchor-not-in-chunk: {anchor_locator!r} is not one of this "
            f"chunk's {len(allowed)} locators"
        )

    unit = chunk.unit(anchor_locator)
    if unit is None:  # unreachable given the membership check, kept explicit
        return None, f"anchor-unresolvable: {anchor_locator!r}"

    quote = (raw.get("quote") or "").strip()
    source: Source = registry.get(chunk.source_id)
    anchor = Anchor(
        source_id=chunk.source_id,
        locator=anchor_locator,
        checksum=source.checksum,
    )

    # Gate 2 — quote grounding.
    ok, detail = registry.verify_quote(anchor, quote)
    if not ok:
        return None, f"quote-not-grounded: {detail}"

    # Gate 3 — schema validity, enforced by the constructor.
    try:
        claim = Claim.create(
            subject_id=_entity_key(raw.get("subject", "")),
            predicate=(raw.get("predicate") or "").strip(),
            predicate_hint=(raw.get("predicate_hint") or "").strip().lower(),
            quote=quote,
            anchor=anchor,
            observed_at=(
                unit.observed_at
                if unit.observed_at is not None
                else source.observed_at
            ),
            object_literal=str(raw.get("object", "")).strip() or None,
            valid_from=raw.get("valid_from") or None,
            valid_until=raw.get("valid_until") or None,
            # Extractors produce pending, private claims. Only the approval
            # path promotes, and only an approver chooses visibility.
            tier=Tier.PENDING,
            visibility=Visibility.PRIVATE,
            provenance=Provenance.CORPUS,
            extra={
                "chunk_id": chunk.chunk_id,
                "unit_confidence": unit.confidence,
                "source_format": chunk.format_hint,
            },
        )
    except CitationError as exc:
        return None, f"citation-invalid: {exc}"
    except TemporalError as exc:
        return None, f"temporal-invalid: {exc}"
    except ValueError as exc:
        return None, f"schema-invalid: {exc}"

    return claim, ""


# --------------------------------------------------------------- agent path

_AGENT_TASK = """\
Excerpt {chunk_id} is ready.

Call read_chunk to see it, then call propose_claim once for each durable \
institutional fact it asserts.

Valid anchors for this excerpt — propose_claim rejects anything else:
{locators}
"""

_AGENT_USER_ID = "baraza-ingest"


@dataclass(slots=True)
class _ChunkContext:
    """What the bound tools are allowed to see: exactly one chunk."""

    chunk: Chunk
    allowed: set
    result: ExtractionResult


def _tools_for(extractor: AgentClaimExtractor) -> Sequence[Any]:
    """The extractor agent's two tools, bound to the chunk under extraction.

    Closures rather than methods so the tool names the model sees are the names
    the compliance matrix and ``docs/architecture.md`` publish — ``read_chunk``
    and ``propose_claim`` — and so ``BarazaAgents.assert_promotion_isolated``
    resolves them to this module, which cannot write a promotion event.
    """

    def read_chunk() -> ToolResult:
        """Return the excerpt under extraction.

        Every line is prefixed with the locator it came from. Those bracketed
        locators are the only anchors propose_claim will accept.
        """
        return extractor.read_chunk()

    def propose_claim(
        subject: str,
        predicate: str,
        predicate_hint: str,
        # Shadows the builtin inside this closure, deliberately: the parameter
        # name is what ADK publishes to the model, and it has to match the
        # `object` field the direct path's JSON schema already uses. Two names
        # for the same field across the two paths is how they drift.
        object: str,
        quote: str,
        anchor: str,
        valid_from: str = "",
        valid_until: str = "",
    ) -> ToolResult:
        """Record one durable institutional fact from the excerpt.

        anchor must be copied exactly from the bracketed locators in the
        excerpt, and quote must appear verbatim in that line. Both are checked
        against the real source text; a claim that fails comes back as
        ok=false with the reason, and the correct response is to drop it and
        move on rather than to retry it with a different anchor.

        predicate_hint is 2-4 lowercase words categorising the relation
        ('signing authority', 'dues amount', 'officer term'); it is what groups
        related claims across documents. valid_from and valid_until are
        ISO-8601 with offset, and are left empty unless the line itself states
        a period.
        """
        return extractor.propose_claim(
            {
                "subject": subject,
                "predicate": predicate,
                "predicate_hint": predicate_hint,
                "object": object,
                "quote": quote,
                "anchor": anchor,
                "valid_from": valid_from or None,
                "valid_until": valid_until or None,
            }
        )

    return [read_chunk, propose_claim]


class AgentClaimExtractor:
    """Extraction as an ADK agent — the BAR-020 execution path.

    Same three gates as :class:`ClaimExtractor`, reached through a tool the
    model calls rather than through a JSON blob it returns in one shot. What
    that buys is a rejection the model can *see*: ``propose_claim`` answers
    ``ok=false`` with the reason the claim failed, in the turn after the attempt,
    so a bad anchor is corrected or abandoned inside the loop instead of being
    counted in a rejection summary nobody reads until the run is over.

    What it costs is a bounded loop instead of a single call, which is why both
    bounds are enforced here:

    * ``MAX_AGENT_TURNS`` becomes ``RunConfig(max_llm_calls=...)``. ADK raises
      on the call that would exceed it.
    * ``AGENT_TIMEOUT_SECONDS`` becomes an ``asyncio.wait_for`` around the whole
      invocation.

    Neither cutoff is swallowed: both are appended to the result's rejection
    list under a named reason, so a chunk lost to a looping model shows up in
    ``rejection_summary()`` next to the ordinary anchor failures.

    The agent is built **once**, at construction, and the promotion-isolation
    check runs there — before the pipeline has read a document, on a deployed
    run and not only under pytest.
    """

    def __init__(
        self,
        registry: SourceRegistry,
        *,
        model: Any = None,
        max_turns: int = MAX_AGENT_TURNS,
        timeout_seconds: float = AGENT_TIMEOUT_SECONDS,
        app_name: str = "baraza-ingest",
    ):
        self.registry = registry
        self.max_turns = max_turns
        self.timeout_seconds = timeout_seconds
        self.app_name = app_name
        self._context: _ChunkContext | None = None

        self.agent = build_extractor(_tools_for(self), model=model)
        self.fleet = BarazaAgents(extractor=self.agent)
        # Startup, not test-time. See BarazaAgents.assert_promotion_isolated.
        self.fleet.assert_promotion_isolated()
        self.runner = open_runner(self.agent, app_name=app_name)

    # ------------------------------------------------------------- the tools

    def read_chunk(self) -> ToolResult:
        if self._context is None:
            return ToolResult(ok=False, reason="no excerpt is under extraction")
        chunk = self._context.chunk
        return ToolResult(
            ok=True,
            data={
                "chunk_id": chunk.chunk_id,
                "locators": list(chunk.locators),
                "text": chunk.text,
            },
        )

    def propose_claim(self, raw: dict[str, Any]) -> ToolResult:
        if self._context is None:
            return ToolResult(ok=False, reason="no excerpt is under extraction")
        context = self._context
        context.result.raw_returned += 1

        claim, reason = build_claim(
            raw, context.chunk, context.allowed, self.registry
        )
        if claim is None:
            context.result.rejected.append((reason, raw))
            return ToolResult(ok=False, reason=reason)

        context.result.claims.append(claim)
        return ToolResult(ok=True, data={"claim_id": claim.claim_id})

    # --------------------------------------------------------------- driving

    def extract_chunk(self, chunk: Chunk) -> ExtractionResult:
        """Synchronous entry point, matching :class:`ClaimExtractor`."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.extract_chunk_async(chunk))
        raise RuntimeError(
            "extract_chunk was called from inside a running event loop. Await "
            "extract_chunk_async instead; nesting asyncio.run would deadlock."
        )

    async def extract_chunk_async(self, chunk: Chunk) -> ExtractionResult:
        result = ExtractionResult(chunks_processed=1)
        self._context = _ChunkContext(
            chunk=chunk, allowed=set(chunk.locators), result=result
        )
        try:
            await asyncio.wait_for(self._drive(chunk), self.timeout_seconds)
        except TimeoutError:
            # Named, counted, and not fatal. One chunk's extraction is worth
            # less than the run, and a cutoff nobody can see in the report is
            # indistinguishable from an excerpt that held no facts.
            result.rejected.append(
                (
                    f"agent-timeout: no result within {self.timeout_seconds:g}s",
                    {"chunk_id": chunk.chunk_id},
                )
            )
        except TurnCeilingExceeded as exc:
            result.rejected.append(
                (
                    f"agent-turn-ceiling: {exc}",
                    {"chunk_id": chunk.chunk_id, "max_turns": self.max_turns},
                )
            )
        finally:
            self._context = None
        return result

    async def _drive(self, chunk: Chunk) -> None:
        from google.genai import types

        session_id = f"extract-{chunk.chunk_id}"
        await self.runner.session_service.create_session(
            app_name=self.app_name, user_id=_AGENT_USER_ID, session_id=session_id
        )
        task = _AGENT_TASK.format(
            chunk_id=chunk.chunk_id,
            locators="\n".join(f"  [{loc}]" for loc in chunk.locators),
        )
        stream = self.runner.run_async(
            user_id=_AGENT_USER_ID,
            session_id=session_id,
            new_message=types.Content(role="user", parts=[types.Part(text=task)]),
            run_config=agent_run_config(max_turns=self.max_turns),
        )
        async for _event in stream:
            # Events are the agent's own narration. The record of what happened
            # is the claim list the tools built and the event log the pipeline
            # appends; nothing here is authoritative.
            pass


def _entity_key(name: str) -> str:
    """Provisional entity id from a surface form.

    Deliberately naive — normalization is the entity pass's job, and doing it
    here would hide the aliasing problem the scorecard is supposed to measure.
    """
    slug = "-".join(name.strip().lower().split())
    return f"ent:{slug}" if slug else "ent:unknown"


# --------------------------------------------------------------- belief path

USER_ENTITY_ID = "ent:user"
"""The single subject every belief claim is written about.

Defined once, here, because contradiction detection blocks on subject ∪
``predicate_hint``: two belief claims written under two spellings of the user
entity would never land in the same block, and the divergence moment — the
product — would silently stop firing. Everything that mints or pools belief
claims imports this constant instead of restating it.
"""

BELIEF_SCHEMA_NAME = "beliefs.v1"

BELIEF_TAXONOMY = frozenset(
    {
        "citation policy",
        "estimation policy",
        "visibility policy",
        "tone policy",
        "routing policy",
        "refusal policy",
    }
)
"""The closed set of ``predicate_hint`` values a belief may carry.

Closed for the same reason anchors are a closed set: the hint is the blocking
key for contradiction detection, and a model free to invent hints would scatter
related beliefs across blocks that never meet. A hint outside this set is a
gate failure, not a new category.
"""

_BELIEF_SYSTEM = """\
You extract the operating rules a person states about how their own work \
should be done. You read one turn they wrote during a working session and \
return the durable, judgment-shaped rules it asserts — about themselves, \
addressed to whoever works for them next.

A rule worth extracting has JUDGMENT SHAPE: it says what to do, and it carries \
at least one of a condition, a threshold, an exception, or a scope. "Cite the \
source before the number, unless the recipient is internal" is a rule. \
"I like it concise" is a taste, and you SKIP it.

Rules you never break:

* Extract only what the turn actually states or unambiguously directs. Never \
infer a rule the person did not assert.
* SKIP pure style observations — tone, brevity, formality, phrasing taste — \
unless the turn attaches a condition, threshold, scope, or exception to them. \
A conditional style rule ("formal register when the recipient is external") \
qualifies; a bare preference never does.
* Every rule carries a quote copied VERBATIM from the turn. Do not paraphrase, \
do not trim mid-word, do not fix spelling.
* "rule" is one imperative sentence. "condition" is the stated condition or \
scope, or null when the rule is unconditional — never invent one.
* predicate_hint MUST be one of the categories you are given. If no category \
fits, the statement is not a belief this system records; skip it.
* An empty list is a valid and common answer. Most turns contain work, not \
rules about work.
"""

_BELIEF_PROMPT = """\
Extract every judgment-shaped operating rule the person asserts in the turn \
below.

Return JSON only, matching this shape exactly:

{{
  "beliefs": [
    {{
      "rule": "one imperative sentence stating what to do",
      "condition": "the stated condition, scope, or exception — or null",
      "predicate_hint": "exactly one of: {taxonomy}",
      "quote": "verbatim text from the turn that asserts this rule"
    }}
  ]
}}

The turn:
{text}
"""


@dataclass(slots=True)
class BeliefExtractionResult:
    """Belief claims from one turn, plus what was dropped and why.

    The rejected list is not diagnostics garnish: a partner session that
    surfaced only accepted beliefs would make a silently failing extractor look
    like a turn that contained no rules, which is the same defect a silent drop
    rate is in the corpus path.
    """

    claims: list[Claim] = field(default_factory=list)
    rejected: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    raw_returned: int = 0

    def rejection_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for reason, _ in self.rejected:
            key = reason.split(":", 1)[0]
            counts[key] = counts.get(key, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


def _normalize_ws(text: str) -> str:
    """The comparison form for quote grounding.

    Mirrors ``SourceRegistry.verify_quote``: collapse whitespace, strip, and
    lowercase. Extraction reflows text; nothing else about the quote is
    forgiven.
    """
    return re.sub(r"\s+", " ", text).strip().lower()


class BeliefExtractor:
    """One extraction call per user turn, every result verified against it.

    Belief claims come out at tier ``PENDING`` and visibility ``PRIVATE``, with
    provenance ``INTERVIEW`` — the session-partner loop only surfaces them, and
    nothing here can promote. Only the approval path writes ``committed``.
    """

    def __init__(self, client: LLMClient):
        self.client = client

    def extract_turn(
        self,
        turn_text: str,
        *,
        session_id: str,
        turn_id: str,
        observed_at: Any = None,
    ) -> BeliefExtractionResult:
        result = BeliefExtractionResult()
        text = turn_text.strip()
        if not text:
            return result

        prompt = _BELIEF_PROMPT.format(
            taxonomy=", ".join(f"'{h}'" for h in sorted(BELIEF_TAXONOMY)),
            text=text,
        )
        try:
            response = self.client.generate(
                # The reasoning model, not the fast one: judgment shape is a
                # reading-comprehension problem, and a cheap extraction that
                # returns preference fluff is worse than a slow one — the
                # DECISION doc names a preference-list dossier as fatal.
                role="reasoning",
                prompt=prompt,
                system=_BELIEF_SYSTEM,
                schema_name=BELIEF_SCHEMA_NAME,
                temperature=0.0,
            )
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            result.rejected.append(
                ("unparseable-response", {"error": str(exc), "turn_id": turn_id})
            )
            return result

        raw_beliefs = payload.get("beliefs") or []
        result.raw_returned = len(raw_beliefs)

        instant = (
            observed_at if observed_at is not None else int(time.time() * 1000)
        )
        for raw in raw_beliefs:
            claim, reason = build_belief_claim(
                raw,
                turn_text=text,
                session_id=session_id,
                turn_id=turn_id,
                observed_at=instant,
            )
            if claim is None:
                result.rejected.append((reason, raw if isinstance(raw, dict) else {}))
            else:
                result.claims.append(claim)
        return result


def build_belief_claim(
    raw: dict[str, Any],
    *,
    turn_text: str,
    session_id: str,
    turn_id: str,
    observed_at: Any,
) -> tuple[Claim | None, str]:
    """The belief gates, in order. The only place a belief claim is built.

    Returns ``(claim, "")`` on acceptance and ``(None, reason)`` on rejection,
    matching :func:`build_claim`'s contract so the partner session can surface
    both kinds of drop through one shape.
    """
    if not isinstance(raw, dict):
        return None, "belief-not-an-object: the model returned a non-object entry"

    quote = str(raw.get("quote") or "").strip()
    rule = str(raw.get("rule") or "").strip()
    condition_raw = raw.get("condition")
    condition = (
        str(condition_raw).strip()
        if condition_raw not in (None, "", "null")
        else None
    )
    hint = str(raw.get("predicate_hint") or "").strip().lower()

    # Gate 1 — quote grounding, against the turn itself. The turn is the source;
    # a quote that is not in it is a fabricated citation, which is a stop
    # condition for this claim, not a repair opportunity.
    if not quote:
        return None, "quote-not-in-turn: empty quote"
    if _normalize_ws(quote) not in _normalize_ws(turn_text):
        return None, (
            f"quote-not-in-turn: {quote[:80]!r} does not appear in the turn "
            "after whitespace normalization"
        )

    # Gate 2 — taxonomy membership. The hint is the blocking key for
    # contradiction detection; an invented category would place this belief in
    # a block no other belief can reach.
    if hint not in BELIEF_TAXONOMY:
        return None, (
            f"hint-not-in-taxonomy: {hint!r} is not one of "
            f"{sorted(BELIEF_TAXONOMY)}"
        )

    if not rule:
        return None, "rule-missing: a belief with no imperative is not a rule"

    # Gate 3 — judgment shape for style. An unconditional tone rule is a
    # preference wearing rule clothing ("prefers concise"), and committing it
    # is the exact failure that turns the dossier into a settings page. Tone
    # survives only when the turn bound it to a condition or scope.
    if hint == "tone policy" and condition is None:
        return None, (
            "style-without-condition: an unconditional tone rule is a style "
            "preference, and the dossier records judgment, not taste"
        )

    # Gate 4 — schema validity, enforced by the constructor.
    try:
        claim = Claim.create(
            subject_id=USER_ENTITY_ID,
            predicate=rule,
            predicate_hint=hint,
            quote=quote,
            anchor=Anchor(
                source_id=f"interview:{session_id}",
                locator=f"turn:{turn_id}",
            ),
            observed_at=observed_at,
            # The object carries the full judgment — rule plus condition — so
            # the contradiction adjudicator sees the scope, not just the verb.
            object_literal=(rule if condition is None else f"{rule} — {condition}"),
            # Belief claims are pending and private until the user ratifies
            # them; nothing on this path can promote or widen visibility.
            tier=Tier.PENDING,
            visibility=Visibility.PRIVATE,
            provenance=Provenance.INTERVIEW,
            session_id=session_id,
            extra={
                "belief": True,
                "turn_id": turn_id,
                "condition": condition,
                # The imperative wording the doctrine compiler renders. Authored
                # here, at extraction, because the compiler never phrases
                # anything — a claim arriving without this falls back to a
                # mechanical "predicate: object" rendering, which is true but
                # reads like a database row instead of a rule.
                "rule_text": (
                    rule if condition is None else f"{rule} ({condition})"
                ),
            },
        )
    except CitationError as exc:
        return None, f"citation-invalid: {exc}"
    except TemporalError as exc:
        return None, f"temporal-invalid: {exc}"
    except ValueError as exc:
        return None, f"schema-invalid: {exc}"

    return claim, ""


def extract_beliefs(
    turn_text: str,
    session_id: str,
    turn_id: str,
    client: LLMClient,
    *,
    observed_at: Any = None,
) -> list[Claim]:
    """Mine one user turn for judgment-shaped belief claims.

    Convenience wrapper over :class:`BeliefExtractor` for callers that only
    want the accepted claims. Anything that needs to *report* — the partner
    session surfacing drops, a test asserting a named rejection — uses
    :meth:`BeliefExtractor.extract_turn` and reads the full result.
    """
    return (
        BeliefExtractor(client)
        .extract_turn(
            turn_text,
            session_id=session_id,
            turn_id=turn_id,
            observed_at=observed_at,
        )
        .claims
    )
