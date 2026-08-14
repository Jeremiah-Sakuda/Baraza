"""The ADK agent layer: framework presence and tool isolation.

Two things are asserted here that are asserted nowhere else.

**That ADK is actually used.** BAR-020 and AGENTS.md constraint 8 name ADK as
the agent framework, and ``docs/compliance.md`` claims it. A compliance matrix
that names a framework the code does not import is the exact failure that pulled
the Antigravity claim from an earlier revision. This test is what keeps the
claim honest: it fails if the agents stop being ADK agents.

**That promotion stays isolated.** No reasoning agent may hold a tool that can
commit a claim. The check exists in three layers — code, IAM, and here — because
the layer most likely to be quietly weakened during a late change is the one
nobody tests.
"""

from __future__ import annotations

import pytest

from baraza.agents import (
    ADK_AVAILABLE,
    AgentRole,
    BarazaAgents,
    ToolResult,
    build_approver,
    build_extractor,
    build_interviewer,
    build_reconciler,
)

pytestmark = pytest.mark.skipif(
    not ADK_AVAILABLE, reason="google-adk not installed"
)


# Tool stubs. Real signatures, no side effects — this file tests wiring, not
# behaviour.


def read_chunk(chunk_id: str) -> ToolResult:
    """Read one excerpt of the corpus."""
    return ToolResult(ok=True, data={"chunk_id": chunk_id})


def propose_claim(anchor: str, quote: str) -> ToolResult:
    """Propose a pending claim."""
    return ToolResult(ok=True)


def retrieve_block(claim_id: str) -> ToolResult:
    """Retrieve claims sharing a blocking key."""
    return ToolResult(ok=True, data=[])


def record_contradiction(a: str, b: str, rationale: str) -> ToolResult:
    """Record an adjudicated contradiction."""
    return ToolResult(ok=True)


def next_agenda_item() -> ToolResult:
    """Fetch the next agenda question."""
    return ToolResult(ok=True)


def check_divergence(testimony: str) -> ToolResult:
    """Hold testimony against the documentary record."""
    return ToolResult(ok=True)


def record_answer(text: str) -> ToolResult:
    """Store a pending claim derived from testimony."""
    return ToolResult(ok=True)


def commit_claim(claim_id: str) -> ToolResult:
    """Promote a claim to committed."""
    return ToolResult(ok=True)


def reject_claim(claim_id: str) -> ToolResult:
    """Retract a claim permanently."""
    return ToolResult(ok=True)


def set_visibility(claim_id: str, visibility: str) -> ToolResult:
    """Record the approver's visibility choice."""
    return ToolResult(ok=True)


@pytest.fixture
def fleet() -> BarazaAgents:
    return BarazaAgents(
        extractor=build_extractor([read_chunk, propose_claim]),
        reconciler=build_reconciler([retrieve_block, record_contradiction]),
        interviewer=build_interviewer(
            [next_agenda_item, check_divergence, record_answer]
        ),
        approver=build_approver(
            commit_claim=commit_claim,
            reject_claim=reject_claim,
            set_visibility=set_visibility,
        ),
    )


def test_agents_are_genuinely_adk_agents(fleet: BarazaAgents) -> None:
    """The framework claim in the compliance matrix must be true of the code."""
    from google.adk.agents import LlmAgent

    assert isinstance(fleet.extractor, LlmAgent)
    assert isinstance(fleet.reconciler, LlmAgent)
    assert isinstance(fleet.interviewer, LlmAgent)


def test_models_resolve_through_the_single_pin(fleet: BarazaAgents) -> None:
    """No agent carries a model-ID literal of its own."""
    from baraza.schema import models

    assert fleet.extractor.model == models.resolve("fast")
    assert fleet.reconciler.model == models.resolve("reasoning")
    assert fleet.interviewer.model == models.resolve("fast")


def test_tool_isolation_matrix(fleet: BarazaAgents) -> None:
    """Each agent holds exactly its own tools and no others."""
    matrix = fleet.tool_matrix()
    assert matrix[AgentRole.EXTRACTOR] == ["propose_claim", "read_chunk"]
    assert matrix[AgentRole.RECONCILER] == ["record_contradiction", "retrieve_block"]
    assert matrix[AgentRole.INTERVIEWER] == [
        "check_divergence",
        "next_agenda_item",
        "record_answer",
    ]


def test_no_reasoning_agent_can_promote(fleet: BarazaAgents) -> None:
    """The promotion boundary, asserted as a negative."""
    fleet.assert_promotion_isolated()  # must not raise

    matrix = fleet.tool_matrix()
    promotion_tools = {"commit_claim", "set_visibility", "reject_claim"}
    for role in (AgentRole.EXTRACTOR, AgentRole.RECONCILER, AgentRole.INTERVIEWER):
        assert not (promotion_tools & set(matrix[role])), (
            f"{role} gained a promotion tool"
        )


def test_leak_guard_fires_when_a_promotion_tool_is_misplaced() -> None:
    """A guard nobody has seen fail may not work.

    Give the extractor a commit tool and assert the startup check refuses to
    proceed. This is the test that makes the other one meaningful.
    """
    leaky = BarazaAgents(extractor=build_extractor([read_chunk, commit_claim]))
    with pytest.raises(RuntimeError, match="promotion tool"):
        leaky.assert_promotion_isolated()


def test_approver_has_no_model() -> None:
    """Promotion is never a model's judgement call."""
    approver = build_approver(
        commit_claim=commit_claim,
        reject_claim=reject_claim,
        set_visibility=set_visibility,
    )
    assert approver.has_model is False
    assert not hasattr(approver, "instruction")


def test_agents_cannot_transfer_to_each_other(fleet: BarazaAgents) -> None:
    """Transfer is disabled, so no agent can route around its own tool scope.

    An extractor able to hand off to the approver would defeat the isolation
    regardless of which tools it holds directly.
    """
    for agent in (fleet.extractor, fleet.reconciler, fleet.interviewer):
        assert agent.disallow_transfer_to_parent is True
        assert agent.disallow_transfer_to_peers is True


def test_tools_return_structured_refusals_not_exceptions() -> None:
    """A raised exception inside a tool is useless to the model and may leak.

    The guard converts it into ``{"ok": false, "reason": ...}`` so the agent can
    do something other than retry the same failing call.
    """

    def exploding_tool(x: str) -> ToolResult:
        """A tool that raises."""
        raise ValueError("boom: sensitive detail")

    agent = build_extractor([exploding_tool])
    tool = agent.tools[0]
    func = getattr(tool, "func", tool)
    result = func("anything")

    assert result["ok"] is False
    assert "ValueError" in result["reason"]
