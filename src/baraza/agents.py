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

The same boundary is enforced twice more, at different layers, because one
enforcement point is a single point of failure:

* **In code** — no other module constructs a ``claim.committed`` event.
* **In IAM** — the extractor and reconciler service accounts lack the Firestore
  permission to write one, so a compromised or buggy agent still cannot.
* **In tests** — ``tests/unit/test_approval.py`` asserts the negative.

**Failure tolerance.** A worker agent that loops, times out, or returns a
hallucinated reference does not take the pipeline down. Every agent carries a
turn ceiling and a timeout; every tool validates its own arguments against the
real state and returns a structured refusal rather than raising; and a
hallucinated identifier is discarded at the tool boundary, where it is
detectable, rather than downstream where it would look like data.

**On the fallback.** BAR-020 pre-commits one deviation: if ADK's streaming path
cannot meet BAR-330's first-token budget, the *interview service only* drops to
direct GenAI SDK calls. The reconciler and extractor stay on ADK regardless.
``docs/framework-decision.md`` records which branch shipped. This module is the
ADK branch; ``src/baraza/llm.py`` is the direct-call path that the fallback
would use and that the offline cassette demo already runs on.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence

from baraza.schema import models

__all__ = [
    "AgentRole",
    "ToolResult",
    "BarazaAgents",
    "build_extractor",
    "build_reconciler",
    "build_interviewer",
    "build_approver",
    "ADK_AVAILABLE",
]

try:  # ADK is a runtime dependency; the offline demo must import without it.
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool

    ADK_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    LlmAgent = None  # type: ignore[assignment]
    FunctionTool = None  # type: ignore[assignment]
    ADK_AVAILABLE = False


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

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "data": self.data, "reason": self.reason}


def _guard(fn: Callable[..., ToolResult]) -> Callable[..., Dict[str, Any]]:
    """Wrap a tool so that nothing escapes as an exception.

    ADK serializes whatever a tool returns back into the model's context. A
    traceback there is both a leak risk and useless to the model, so every
    failure becomes ``{"ok": false, "reason": ...}``.
    """

    def wrapper(*args: Any, **kwargs: Any) -> Dict[str, Any]:
        try:
            return fn(*args, **kwargs).to_dict()
        except Exception as exc:  # noqa: BLE001 - deliberate boundary
            return ToolResult(
                ok=False, reason=f"{type(exc).__name__}: {exc}"
            ).to_dict()

    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


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


def build_extractor(tools: Sequence[Callable[..., ToolResult]]) -> "LlmAgent":
    """The extraction agent. Holds no tool that can commit anything."""
    _requires_adk()
    return LlmAgent(
        name="baraza_extractor",
        model=models.resolve("fast"),
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


def build_reconciler(tools: Sequence[Callable[..., ToolResult]]) -> "LlmAgent":
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


def build_interviewer(tools: Sequence[Callable[..., ToolResult]]) -> "LlmAgent":
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
    approver: Optional[ApproverSurface] = None

    def tool_matrix(self) -> Dict[str, List[str]]:
        def names(agent: Any) -> List[str]:
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
        """Fail loudly if any reasoning agent has gained a promotion tool.

        Called at startup. The check is cheap and the failure it prevents is
        not: a tool added to the wrong agent during a late-night change is
        exactly how a promotion boundary quietly stops existing.
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
