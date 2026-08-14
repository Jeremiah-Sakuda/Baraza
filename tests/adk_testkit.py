"""A scripted ADK model, so the agent loop can be exercised without Vertex.

``tests/baraza_testkit.py`` fakes :class:`baraza.llm.LLMClient` — the protocol
the *direct* call path codes against. It cannot fake the agent path, because ADK
does not go through that protocol: an ``LlmAgent`` talks to its own
``BaseLlm``. So the double has to sit at the framework's seam, and this is it.

The same rule applies here as there. The script is exactly what a test wrote,
nothing is guessed, and running off the end of the script is an assertion
failure rather than a plausible default — a fake that improvised would let a
test pass against model output nobody wrote.

Nothing in this module produces text that could be mistaken for a recording. A
cassette is a recording of a real Vertex call; this is a scripted stand-in and
says so in its model id.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from typing import Any

from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

__all__ = ["ScriptedAdkModel", "UnscriptedTurn", "function_call", "say"]

# Not a model ID. The compliance lint pins real model literals to
# schema/models.py; a test double must not look like one even by accident.
FAKE_ADK_MODEL = "fake:adk-no-vertex-call"


class UnscriptedTurn(AssertionError):
    """The agent took a turn the test did not script."""


def function_call(name: str, **args: Any) -> LlmResponse:
    """One model turn that calls a tool."""
    return LlmResponse(
        content=types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(name=name, args=dict(args))
                )
            ],
        )
    )


def say(text: str) -> LlmResponse:
    """One model turn that answers in words and stops."""
    return LlmResponse(
        content=types.Content(role="model", parts=[types.Part(text=text)])
    )


class ScriptedAdkModel(BaseLlm):
    """Yields scripted turns in order.

    ``repeat_last`` exists for one test: the runaway loop. A model that keeps
    calling the same rejected tool forever is the failure the turn ceiling is
    for, and scripting it finitely would test the script's length instead of the
    ceiling.
    """

    script: list[LlmResponse] = []
    repeat_last: bool = False
    delay_seconds: float = 0.0
    calls: int = 0
    prompts: list[str] = []

    def __init__(
        self,
        script: Sequence[LlmResponse],
        *,
        repeat_last: bool = False,
        delay_seconds: float = 0.0,
        model: str = FAKE_ADK_MODEL,
    ):
        super().__init__(
            model=model,
            script=list(script),
            repeat_last=repeat_last,
            delay_seconds=delay_seconds,
            calls=0,
            prompts=[],
        )

    async def generate_content_async(
        self, llm_request: Any, stream: bool = False
    ) -> AsyncGenerator[LlmResponse, None]:
        import asyncio

        index = self.calls
        self.calls += 1
        self.prompts.append(_render(llm_request))
        if self.delay_seconds:
            # A model that has not answered yet. Used to exercise the timeout,
            # which is otherwise only reachable by waiting 90 real seconds.
            await asyncio.sleep(self.delay_seconds)
        if index >= len(self.script):
            if not self.repeat_last or not self.script:
                raise UnscriptedTurn(
                    f"the agent took turn {index + 1} but the script has "
                    f"{len(self.script)}. Script it, or pass repeat_last=True "
                    "if the test is about an unbounded loop."
                )
            index = len(self.script) - 1
        yield self.script[index]

    # ------------------------------------------------------------- assertions

    def tool_results(self) -> list[dict[str, Any]]:
        """Every tool response the agent was shown, oldest first.

        This is how a test asserts that a refusal actually reached the model
        rather than being logged somewhere it could not see.
        """
        found: list[dict[str, Any]] = []
        for prompt in self.prompts:
            found.extend(prompt_responses(prompt))
        return found


def prompt_responses(rendered: str) -> list[dict[str, Any]]:
    """Parse the function responses out of a rendered request."""
    import json

    out: list[dict[str, Any]] = []
    for line in rendered.splitlines():
        if line.startswith("response\t"):
            out.append(json.loads(line.split("\t", 1)[1]))
    return out


def _render(llm_request: Any) -> str:
    """Flatten a request into text a test can assert against."""
    import json

    lines: list[str] = []
    for content in getattr(llm_request, "contents", None) or []:
        for part in getattr(content, "parts", None) or []:
            if getattr(part, "text", None):
                lines.append(f"text\t{part.text}")
            call = getattr(part, "function_call", None)
            if call is not None:
                lines.append(f"call\t{call.name}\t{json.dumps(dict(call.args or {}))}")
            response = getattr(part, "function_response", None)
            if response is not None:
                lines.append(f"response\t{json.dumps(dict(response.response or {}))}")
    return "\n".join(lines)


def tools_declared(agent: Any) -> dict[str, dict | Any | None]:
    """Tool name → declared parameter schema, as ADK would send it."""
    declared: dict[str, dict | Any | None] = {}
    for tool in getattr(agent, "tools", []) or []:
        declaration = tool._get_declaration()  # noqa: SLF001 - the framework's seam
        declared[declaration.name] = (
            declaration.parameters_json_schema or declaration.parameters
        )
    return declared
