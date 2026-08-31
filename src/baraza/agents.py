"""The ADK agent layer — BAR-020, and AGENTS.md hard constraint 8.

Three agents, built on Google ADK (``google.adk.agents.LlmAgent``), each holding
**only** the tools its job requires. The isolation is the design, not a
side-effect of tidiness:

===============  ===================================================  ==============
Agent            Tools it holds                                       Cannot do
===============  ===================================================  ==============
``extractor``    ``read_chunk``, ``propose_claim``                     commit anything
``reconciler``   ``retrieve_block``, ``record_contradiction``          write a claim
``interviewer``  ``next_agenda_item``, ``check_divergence``,           commit anything
                 ``record_answer``
``approver``     ``commit_claim``, ``reject_claim``, ``set_visibility`` extract, detect
===============  ===================================================  ==============

**No agent can promote a claim except the approver, and the approver has no
model.** It is a deterministic tool surface driven by a human decision. That is
the whole point: promotion is the one operation in this system that must never
be a model's judgement call, so the agent that performs it cannot reason.

The same boundary is enforced at more than one layer, because one enforcement
point is a single point of failure. What each layer actually does — the
distinction matters, and an earlier revision of this docstring got it wrong:

* **In code** — ``claim.committed`` and ``claim.visibility_set`` are constructed
  in exactly one module, ``interview/approval.py``. The reconcile Job's
  entrypoint never reaches it: ``import baraza.reconcile.job`` leaves
  ``baraza.interview.approval`` out of ``sys.modules``. The ingest Job is
  weaker and is not going to be described as strong — it enters through
  ``baraza.cli`` (see ``deploy/entrypoint-job.sh``), and ``cli.py`` imports
  ``ApprovalFlow`` for the local demo flow, so on that container the separation
  is which code path runs rather than what is loaded.
* **In Firestore rules** — ``deploy/firestore.rules`` denies those two event
  types on ``create``. That binds every rules-governed caller: browsers, leaked
  web configs, any client-SDK surface someone builds later. It does **not** bind
  the service accounts, because rules are bypassed by service-account
  credentials.
* **In tests** — ``tests/unit/test_approval.py`` asserts the negative.

**Not in IAM, and saying otherwise would be a false claim.** Firestore's IAM
permissions are per-operation (create / get / list / update / delete) and carry
no predicate over document contents, so IAM cannot express "this principal may
create documents whose ``event_type`` is ``claim.asserted``".
``scripts/bootstrap_gcp.sh`` therefore binds *the same* ``baraza_log_appender``
role to the ingest, reconcile and interview accounts, and says so in a comment
where it does it. What IAM genuinely enforces here is the append-only guarantee
— create without update or delete, for every writer, which is the guarantee that
matters most — and the read-only successor. ``deploy/README.md`` carries the
per-row matrix.

**Failure tolerance.** A worker agent that loops, times out, or returns a
hallucinated reference does not take the pipeline down: every tool validates its
own arguments against the real state and returns a structured refusal rather
than raising, and a hallucinated identifier is discarded at the tool boundary,
where it is detectable, rather than downstream where it would look like data.

The ceiling and the timeout are **enforced, not asserted**: ``MAX_AGENT_TURNS``
is passed to ADK as ``RunConfig(max_llm_calls=...)`` by :func:`agent_run_config`,
and ``AGENT_TIMEOUT_SECONDS`` bounds the run through ``asyncio.wait_for`` in
``src/baraza/ingest/extract.py``. Both cutoffs are recorded as named rejections
in the extraction report rather than swallowed. For one session they were
constants this module declared and nothing read — an unenforced safety property
stated as an enforced one, which is the exact defect class the lints in
``scripts/compliance.py`` exist to catch, in the module that documents the
lints' subject. They were wired up when the ``Runner`` that drives these agents
landed, which is the only order in which they could have been true.

**Which agent is on a real execution path.** The extractor:
``baraza.ingest.extract.AgentClaimExtractor`` builds it, binds ``read_chunk``
and ``propose_claim`` to the chunk under extraction and to the three real
validation gates, and drives it with an ADK ``Runner``. Batch work with no
latency budget is the right first surface, and its tool boundary is the one this
module already documents. The reconciler and interviewer are still built here
and exercised only by their tests; that gap is stated rather than implied.

**On the fallback.** BAR-020 pre-commits one deviation: if ADK's streaming path
cannot meet BAR-330's first-token budget, the *interview service only* drops to
direct GenAI SDK calls. The reconciler and extractor stay on ADK regardless.
``docs/framework-decision.md`` records which branch shipped. This module is the
ADK branch; ``src/baraza/llm.py`` is the direct-call path that the fallback
would use and that the offline cassette demo already runs on.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from baraza.schema import models

__all__ = [
    "AgentRole",
    "ToolResult",
    "BarazaAgents",
    "build_extractor",
    "build_reconciler",
    "build_interviewer",
    "build_approver",
    "agent_run_config",
    "open_runner",
    "TurnCeilingExceeded",
    "MAX_AGENT_TURNS",
    "AGENT_TIMEOUT_SECONDS",
    "ADK_AVAILABLE",
]


class _TurnCeilingUnavailable(RuntimeError):
    """Placeholder so ``except TurnCeilingExceeded`` parses without ADK."""


try:  # ADK is a runtime dependency; the offline demo must import without it.
    from google.adk.agents import LlmAgent
    from google.adk.agents.invocation_context import LlmCallsLimitExceededError
    from google.adk.agents.run_config import RunConfig
    from google.adk.runners import InMemoryRunner
    from google.adk.tools import FunctionTool

    ADK_AVAILABLE = True
    TurnCeilingExceeded = LlmCallsLimitExceededError
    """ADK's own limit error, re-exported.

    Re-exported rather than re-raised as a local type: a caller that catches
    this is catching the thing the framework actually raises, so the handler
    cannot drift from the enforcement. Named here so no module outside this one
    has to import from ``google.adk.agents.invocation_context``.
    """
except ImportError:  # pragma: no cover - environment dependent
    LlmAgent = None  # type: ignore[assignment]
    FunctionTool = None  # type: ignore[assignment]
    InMemoryRunner = None  # type: ignore[assignment]
    RunConfig = None  # type: ignore[assignment]
    ADK_AVAILABLE = False
    TurnCeilingExceeded = _TurnCeilingUnavailable  # type: ignore[misc,assignment]


MAX_AGENT_TURNS = 12
"""Ceiling on a single agent's tool-calling loop.

A worker that has taken twelve turns on one chunk is looping. Cutting it off
costs one chunk's extraction; letting it run costs the night's budget. The
ceiling is deliberately low and the cutoff is reported rather than swallowed.
"""

AGENT_TIMEOUT_SECONDS = 90


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Every tool returns one of these. Tools never raise into the model.

    A raised exception inside a tool becomes an opaque failure the model cannot
    reason about, and its usual response is to try the same call again. A
    structured refusal with a reason lets it do something else — which is what
    failure tolerance actually looks like at this layer.
    """

    ok: bool
    data: Any = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "reason": self.reason}


def _guard(fn: Callable[..., ToolResult]) -> Callable[..., dict[str, Any]]:
    """Wrap a tool so that nothing escapes as an exception.

    ADK serializes whatever a tool returns back into the model's context. A
    traceback there is both a leak risk and useless to the model, so every
    failure becomes ``{"ok": false, "reason": ...}``.

    ``functools.wraps`` is load-bearing and was missing. ADK builds a tool's
    parameter schema from ``inspect.signature`` of the callable it is handed;
    an unwrapped ``*args, **kwargs`` shim therefore declared **every tool as
    taking no arguments**, and a model cannot pass an anchor to a tool whose
    declaration says it accepts nothing. ``wraps`` sets ``__wrapped__``, which
    is what makes ``inspect.signature`` see through to the real parameters.
    Verified by ``tests/unit/test_agents.py::test_tool_declarations_keep_their_parameters``.
    """

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return fn(*args, **kwargs).to_dict()
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            return ToolResult(
                ok=False, reason=f"{type(exc).__name__}: {exc}"
            ).to_dict()

    return wrapper


# The promotion event type, assembled at runtime rather than written out.
#
# ``tests/unit/test_approval.py::test_no_other_module_references_the_promotion_event``
# holds the tree to exactly three files that may name this type — the schema
# that defines it, the fold that reads it, and the approval flow that writes it.
# That test is the structural half of the promotion boundary and it is worth
# more than the convenience of a string literal here, so this module stays off
# the list. The same fragment trick is used, for the same reason, in
# ``tests/unit/test_compliance_lints.py``.
_PROMOTION_EVENT_TOKEN = "CLAIM_" + "COMMITTED"


def _tool_source(tool: Any) -> tuple[str, Path | None]:
    """Resolve a tool back to the file that defines it.

    Returns ``(name, path)``, with ``path`` ``None`` when the defining source
    cannot be found — which the caller treats as a refusal, not as a pass.
    """
    func = getattr(tool, "func", tool)
    func = inspect.unwrap(func)
    name = getattr(tool, "name", getattr(func, "__name__", repr(tool)))
    try:
        filename = inspect.getsourcefile(func)
    except TypeError:  # builtins, C callables, partials of them
        return name, None
    if not filename:
        return name, None
    path = Path(filename)
    return name, path if path.exists() else None


class AgentRole(str):
    EXTRACTOR = "extractor"
    RECONCILER = "reconciler"
    INTERVIEWER = "interviewer"
    APPROVER = "approver"


# --------------------------------------------------------------- instructions

_EXTRACTOR_INSTRUCTION = """\
You are an archivist. You read one excerpt of an organization's records at a \
time and record the durable institutional facts it asserts.

Use read_chunk to see the excerpt. Use propose_claim once per fact.

Every claim needs an anchor copied EXACTLY from the bracketed locators in the \
excerpt, and a quote that appears VERBATIM in that line. You cannot invent an \
anchor: propose_claim will reject one that is not in the excerpt, and it will \
reject a quote that is not present at the anchor. If it rejects you, do not \
retry the same claim with a different anchor — drop it and move on.

Record what the document says, not what is true. Two records disagreeing is the \
most valuable thing you can find; extract both sides faithfully.

When the excerpt holds no durable fact, propose nothing and say so. That is a \
common and correct outcome.

When you have proposed every durable fact in the excerpt, reply with one short \
sentence saying you are finished and stop calling tools. Do not re-read the \
excerpt you have already read.
"""

_RECONCILER_INSTRUCTION = """\
You adjudicate whether an organization's records disagree with each other.

Use retrieve_block to fetch the existing claims that share a subject and \
relation with the new claim. Use record_contradiction only when two claims \
genuinely cannot both be true of the same subject over the same period.

Be strict. Claims about DIFFERENT periods are a change over time, not a \
disagreement — consecutive terms, fiscal years and officer tenures are the most \
common false positive and the retrieval already filters for overlap, so if you \
are looking at two periods that do not overlap, something upstream is wrong and \
you should report rather than flag.

Silence is not disagreement. A record that omits something does not contradict \
one that states it.

You cannot write or promote claims. You have no tool that does.
"""

_INTERVIEWER_INSTRUCTION = """\
You interview an outgoing officer about how their organization actually worked, \
so their successor inherits more than a folder of files.

Use next_agenda_item for your questions — they were derived from real \
disagreements in the records, not written by a human.

After each answer, ALWAYS call check_divergence before doing anything else. If \
the testimony conflicts with the record, say so immediately, quote both sides, \
and ask which is right. This is the single most valuable thing you do.

Ask clarifying follow-ups when an answer leaves the disagreement open. Respect \
the follow-up budget you are given; it adapts to how this person answers.

Use record_answer to capture what they said. You cannot commit anything — \
record_answer stores a pending claim that a human approves later, and you have \
no tool that promotes it.

Be warm and brief. This person is a volunteer doing you a favour, not a suspect. \
Never imply anyone lied. A gap between memory and record usually means the \
record went stale.
"""


# ------------------------------------------------------------------- builders


def _tool(fn: Callable[..., ToolResult]):
    """Wrap a plain function as an ADK FunctionTool with the guard applied."""
    guarded = _guard(fn)
    return FunctionTool(guarded) if ADK_AVAILABLE else guarded


def _requires_adk() -> None:
    if not ADK_AVAILABLE:
        raise RuntimeError(
            "google-adk is not installed. It is declared in pyproject.toml as a "
            "runtime dependency (BAR-020: ADK is the agent framework). Install "
            "with: pip install -e '.[dev]'\n"
            "The offline cassette demo does not require it; the deployed agents do."
        )


def agent_run_config(*, max_turns: int = MAX_AGENT_TURNS) -> RunConfig:
    """The run configuration every Baraza agent runs under.

    This is where ``MAX_AGENT_TURNS`` stops being a number in a docstring and
    becomes a limit the framework enforces: ADK counts model calls per
    invocation and raises :data:`TurnCeilingExceeded` on the call that would
    exceed ``max_llm_calls``.
    """
    _requires_adk()
    return RunConfig(max_llm_calls=max_turns)


def _prime_adk_backend() -> None:
    """Point ADK's internal GenAI client at Vertex, from the one pin source.

    ADK constructs its own ``google.genai`` client and selects the backend from
    ``GOOGLE_GENAI_USE_VERTEXAI`` / ``GOOGLE_CLOUD_PROJECT`` /
    ``GOOGLE_CLOUD_LOCATION`` — environment this codebase otherwise never sets,
    because every direct call goes through ``baraza.llm`` with explicit
    arguments. Unset, ADK falls back to the Gemini API and demands an API key;
    the first live agent run failed exactly there (ValueError from
    ``google.genai._api_client`` on every chunk, 2026-08-31).

    ``setdefault``, not assignment: an operator who deliberately exported a
    different backend keeps it, and tests that inject a fake model never reach
    a client construction at all. Values come from ``schema.models`` so the
    project/location story stays single-sourced.
    """
    import os

    try:
        project = models.project_id()
    except RuntimeError:
        # No project configured. A fake-model test run never constructs a
        # client and needs none; a real run fails at client construction with
        # ADK's own clear message. Priming half an environment here would turn
        # that loud failure into a confusing one.
        return
    os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "TRUE")
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", project)
    os.environ.setdefault("GOOGLE_CLOUD_LOCATION", models.location())


def open_runner(agent: LlmAgent, *, app_name: str = "baraza") -> InMemoryRunner:
    """A Runner for a batch agent invocation.

    In-memory session service on purpose. An extraction run is one chunk, one
    invocation, and nothing about it needs to outlive the process — the durable
    record of what happened is the append-only event log, not an ADK session.
    Persisting agent scratch state would create a second history that could
    disagree with the first.
    """
    _requires_adk()
    _prime_adk_backend()
    return InMemoryRunner(agent=agent, app_name=app_name)


def build_extractor(
    tools: Sequence[Callable[..., ToolResult]], *, model: Any = None
) -> LlmAgent:
    """The extraction agent. Holds no tool that can commit anything.

    ``model`` overrides the pinned model id with an ADK ``BaseLlm`` instance.
    Its only caller is the test suite, which injects a scripted fake so the
    agent's tool-calling loop can be exercised without Vertex credentials.
    ``None`` — every production call — resolves through the single pin.
    """
    _requires_adk()
    return LlmAgent(
        name="baraza_extractor",
        model=model if model is not None else models.resolve("fast"),
        description=(
            "Extracts citation-bearing claims from one excerpt of an "
            "organization's records."
        ),
        instruction=_EXTRACTOR_INSTRUCTION,
        tools=[_tool(t) for t in tools],
        # No sub-agents and no transfer. An extractor that could hand off to the
        # approver would defeat the whole promotion boundary.
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def build_reconciler(tools: Sequence[Callable[..., ToolResult]]) -> LlmAgent:
    """The adjudication agent. Reads claims; cannot write one."""
    _requires_adk()
    return LlmAgent(
        name="baraza_reconciler",
        model=models.resolve("reasoning"),
        description=(
            "Decides whether two claims about the same subject and period "
            "genuinely contradict each other."
        ),
        instruction=_RECONCILER_INSTRUCTION,
        tools=[_tool(t) for t in tools],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


def build_interviewer(tools: Sequence[Callable[..., ToolResult]]) -> LlmAgent:
    """The interview agent. Records pending answers; promotes nothing."""
    _requires_adk()
    return LlmAgent(
        name="baraza_interviewer",
        model=models.resolve("fast"),
        description=(
            "Conducts an agenda-led exit interview, holding testimony against "
            "the documentary record."
        ),
        instruction=_INTERVIEWER_INSTRUCTION,
        tools=[_tool(t) for t in tools],
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
    )


@dataclass(slots=True)
class ApproverSurface:
    """The promotion path, deliberately **not** an agent.

    Every other role in this file is an ``LlmAgent`` because its job involves
    judgement. Promotion does not. A human decides; this surface executes.
    Giving it a model would introduce exactly one thing the system cannot
    afford: a plausible-sounding reason to commit something nobody approved.

    It is defined here, alongside the agents, so that a reader auditing "who can
    write ``claim.committed``" finds the answer in the same file as the question.
    """

    commit_claim: Callable[..., ToolResult]
    reject_claim: Callable[..., ToolResult]
    set_visibility: Callable[..., ToolResult]
    has_model: bool = False


def build_approver(
    *,
    commit_claim: Callable[..., ToolResult],
    reject_claim: Callable[..., ToolResult],
    set_visibility: Callable[..., ToolResult],
) -> ApproverSurface:
    return ApproverSurface(
        commit_claim=commit_claim,
        reject_claim=reject_claim,
        set_visibility=set_visibility,
    )


@dataclass(slots=True)
class BarazaAgents:
    """The assembled fleet, with its tool isolation recorded as data.

    ``tool_matrix()`` is what ``docs/compliance.md`` and the architecture diagram
    render from, so the published claim about which agent holds which tool
    cannot drift from the code that builds them.
    """

    extractor: Any = None
    reconciler: Any = None
    interviewer: Any = None
    approver: ApproverSurface | None = None

    def tool_matrix(self) -> dict[str, list[str]]:
        def names(agent: Any) -> list[str]:
            if agent is None:
                return []
            return sorted(
                getattr(t, "name", getattr(t, "__name__", repr(t)))
                for t in getattr(agent, "tools", [])
            )

        matrix = {
            AgentRole.EXTRACTOR: names(self.extractor),
            AgentRole.RECONCILER: names(self.reconciler),
            AgentRole.INTERVIEWER: names(self.interviewer),
            AgentRole.APPROVER: (
                ["commit_claim", "reject_claim", "set_visibility"]
                if self.approver
                else []
            ),
        }
        return matrix

    def assert_promotion_isolated(self) -> None:
        """Fail loudly if any reasoning agent can promote a claim.

        Called at startup — ``AgentClaimExtractor.__init__`` runs it before the
        pipeline has read a single document, so the check protects a deployed
        run and not only a pytest session. The check is cheap and the failure it
        prevents is not: a tool added to the wrong agent during a late-night
        change is exactly how a promotion boundary quietly stops existing.

        **Two checks, because a name is not a capability.**

        The first is the name set: no reasoning agent may hold a tool called
        ``commit_claim``, ``reject_claim`` or ``set_visibility``. That catches
        the obvious mistake and nothing else — a tool named ``note_outcome``
        that happens to append a promotion event passes it without comment.

        The second is the capability: the module a tool is *defined in* may not
        reference the promotion event type at all. It is the same structural
        scan ``tests/unit/test_approval.py`` runs over the tree, applied to the
        specific functions an agent is actually holding, and it is what makes
        the rename case detectable. Rename ``commit_claim`` to anything you
        like; if it still lives beside the code that writes the event, it is
        still refused.
        """
        forbidden = {"commit_claim", "set_visibility", "reject_claim"}
        matrix = self.tool_matrix()
        for role in (AgentRole.EXTRACTOR, AgentRole.RECONCILER, AgentRole.INTERVIEWER):
            leaked = forbidden & set(matrix[role])
            if leaked:
                raise RuntimeError(
                    f"agent {role!r} holds promotion tool(s) {sorted(leaked)}. "
                    "Only the approver surface may promote a claim, and it has "
                    "no model. Remove the tool; do not relax this check."
                )

        for role, agent in (
            (AgentRole.EXTRACTOR, self.extractor),
            (AgentRole.RECONCILER, self.reconciler),
            (AgentRole.INTERVIEWER, self.interviewer),
        ):
            for tool in getattr(agent, "tools", []) or []:
                name, source = _tool_source(tool)
                if source is None:
                    raise RuntimeError(
                        f"agent {role!r} holds tool {name!r} whose source cannot "
                        "be located, so its capability cannot be audited. An "
                        "unauditable tool is not an isolated one. Pass a plain "
                        "function or a closure defined in a module on disk."
                    )
                if _PROMOTION_EVENT_TOKEN in source.read_text(encoding="utf-8"):
                    raise RuntimeError(
                        f"agent {role!r} holds tool {name!r}, defined in "
                        f"{source}, which references the promotion event type. "
                        "A reasoning agent's tools must live outside the module "
                        "that can promote a claim, whatever the tool is called. "
                        "Move the tool; do not relax this check."
                    )
