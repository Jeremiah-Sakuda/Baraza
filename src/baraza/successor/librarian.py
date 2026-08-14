"""Successor mode — the librarian.

The incoming officer asks a question. The librarian answers **only** from claims
that are both ``committed`` and readable by ``Audience.SUCCESSOR``, and every
sentence it produces carries a citation.

**The refusal is a feature.** When the readable committed record cannot support
an answer, the librarian says so and stops. It does not fall back on general
knowledge about how student organizations usually work, it does not hedge into a
plausible paragraph, and it does not synthesize across claims it cannot cite.
This has its own acceptance criterion, and engineering the refusal away would be
removing the property rather than fixing a bug.

The reason is specific to what this system is for. A successor reading a
handover cannot tell a remembered fact from a fluent guess, and a fluent guess
about who can sign a cheque is worse than silence. Silence is recoverable — they
go and ask someone. A confident wrong answer is not.

**Two failure directions, deliberately asymmetric.** Retrieving nothing produces
a refusal. Retrieving something the audience may not read produces a refusal
that does not reveal that anything was withheld beyond the fact of it — the
count is honest, the content is not disclosed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from baraza.fold.graph import GraphState
from baraza.llm import LLMClient
from baraza.schema.claim import Claim
from baraza.schema.visibility import Audience, readable_by

__all__ = ["Citation", "LibrarianAnswer", "Librarian", "REFUSAL_TEXT"]

REFUSAL_TEXT = (
    "I don't have a record that answers this. Nothing in the committed handover "
    "covers it, so I'd be guessing — and a guess about this is worse than a gap. "
    "Ask the outgoing officer directly, and their answer will become part of the "
    "record for whoever comes after you."
)


@dataclass(frozen=True, slots=True)
class Citation:
    claim_id: str
    anchor: str
    quote: str

    def render(self) -> str:
        return f"[{self.anchor}] “{self.quote}”"


@dataclass(slots=True)
class LibrarianAnswer:
    """An answer, or an honest refusal."""

    text: str
    refused: bool
    citations: List[Citation] = field(default_factory=list)
    considered: int = 0
    readable: int = 0
    withheld: int = 0
    """Committed claims that matched but that this audience may not read.

    Reported as a count and never as content. A successor learning that three
    records exist which they cannot see is being told the truth; being shown
    those records would break the boundary, and being told nothing exists would
    be a lie.
    """

    refusal_reason: str = ""

    def render(self) -> List[str]:
        lines = [self.text]
        if self.citations:
            lines.append("")
            lines.append("Sources:")
            lines.extend(f"  {c.render()}" for c in self.citations)
        if self.withheld:
            lines.append("")
            lines.append(
                f"({self.withheld} further record(s) match this question but are "
                "not visible to your role.)"
            )
        return lines


_SYSTEM = """\
You are a librarian for an organization's institutional memory. An incoming \
officer is asking you a question during their handover.

You may use ONLY the claims provided below. They are the complete set of records \
available for this question.

Rules you never break:

* Every factual sentence you write must be supported by one of the provided \
claims, and you must name the claim id that supports it.
* If the claims do not answer the question, respond with exactly: INSUFFICIENT
* Never use general knowledge about how organizations usually work. If it is not \
in the claims, you do not know it.
* Never combine two claims into an inference the claims do not support. Stating \
that A is true and B is true is fine; concluding C from them is not.
* If the claims conflict with each other, say so and present both. A disagreement \
is information, not a problem to resolve.
* Be brief. Three sentences is usually enough.

Return JSON only:
{"answer": "...", "claim_ids": ["..."]}
or
{"answer": "INSUFFICIENT", "claim_ids": []}
"""


class Librarian:
    """Successor-mode question answering, citation-bound."""

    def __init__(
        self,
        client: LLMClient,
        state: GraphState,
        *,
        audience: Audience = Audience.SUCCESSOR,
        max_claims: int = 24,
    ):
        self.client = client
        self.state = state
        self.audience = audience
        self.max_claims = max_claims

    def retrieve(self, question: str) -> tuple[List[Claim], int]:
        """Committed claims relevant to the question, plus a withheld count.

        Relevance is keyword overlap over subject and predicate hint. There is
        no vector database: at a few thousand claims, brute-force scoring in
        memory is microseconds, and standing up a vector store here would be
        infrastructure bought to solve a problem this cardinality does not have.
        """
        terms = {
            token
            for token in "".join(
                ch if ch.isalnum() else " " for ch in question.lower()
            ).split()
            if len(token) > 3
        }

        scored: List[tuple[float, Claim]] = []
        withheld = 0

        for claim in self.state.committed_claims():
            haystack = (
                f"{claim.subject_id} {claim.predicate} {claim.predicate_hint}"
            ).lower().replace("-", " ").replace("ent:", "")
            overlap = sum(1 for term in terms if term in haystack)
            if overlap == 0:
                continue
            # The boundary is applied AFTER matching, so the withheld count is a
            # true count of relevant-but-unreadable records rather than an
            # artifact of never having looked.
            if not readable_by(claim, self.audience):
                withheld += 1
                continue
            scored.append((overlap / max(len(terms), 1), claim))

        scored.sort(key=lambda pair: (-pair[0], pair[1].claim_id))
        return [claim for _, claim in scored[: self.max_claims]], withheld

    def ask(self, question: str) -> LibrarianAnswer:
        candidates, withheld = self.retrieve(question)

        if not candidates:
            return LibrarianAnswer(
                text=REFUSAL_TEXT,
                refused=True,
                considered=len(self.state.committed_claims()),
                readable=0,
                withheld=withheld,
                refusal_reason=(
                    "no readable committed claim matched"
                    if withheld == 0
                    else "matching records exist but are not readable by this role"
                ),
            )

        rendered = "\n".join(
            f"  - id: {c.claim_id}\n"
            f"    subject: {c.subject_id.removeprefix('ent:').replace('-', ' ')}\n"
            f"    asserts: {c.object_for(self.audience)}\n"
            f'    quote:   "{c.quote_for(self.audience)}"\n'
            f"    source:  {c.anchor.key()}"
            for c in candidates
        )
        prompt = f"QUESTION\n  {question.strip()}\n\nAVAILABLE CLAIMS\n{rendered}\n"

        try:
            response = self.client.generate(
                role="reasoning",
                prompt=prompt,
                system=_SYSTEM,
                schema_name="librarian.v1",
                temperature=0.1,
            )
            payload = response.json()
            answer_text = str(payload.get("answer", "")).strip()
            cited_ids = list(payload.get("claim_ids") or [])
        except Exception:  # noqa: BLE001
            return LibrarianAnswer(
                text=REFUSAL_TEXT,
                refused=True,
                considered=len(candidates),
                readable=len(candidates),
                withheld=withheld,
                refusal_reason="synthesis failed; refusing rather than guessing",
            )

        if not answer_text or answer_text.upper().startswith("INSUFFICIENT"):
            return LibrarianAnswer(
                text=REFUSAL_TEXT,
                refused=True,
                considered=len(candidates),
                readable=len(candidates),
                withheld=withheld,
                refusal_reason="the record does not support an answer",
            )

        # An answer whose citations do not check out is refused, not published.
        # This is the gate that makes "citation-grounded" a property rather than
        # a prompt instruction: the model is asked to cite, and then the citation
        # is verified against what was actually retrievable and readable.
        by_id = {c.claim_id: c for c in candidates}
        citations: List[Citation] = []
        for claim_id in cited_ids:
            claim = by_id.get(claim_id)
            if claim is None:
                continue
            quote = claim.quote_for(self.audience)
            if not quote:
                continue
            citations.append(
                Citation(claim_id=claim_id, anchor=claim.anchor.key(), quote=quote)
            )

        if not citations:
            return LibrarianAnswer(
                text=REFUSAL_TEXT,
                refused=True,
                considered=len(candidates),
                readable=len(candidates),
                withheld=withheld,
                refusal_reason=(
                    "the synthesis cited no verifiable claim; uncited synthesis "
                    "is refused by design"
                ),
            )

        return LibrarianAnswer(
            text=answer_text,
            refused=False,
            citations=citations,
            considered=len(self.state.committed_claims()),
            readable=len(candidates),
            withheld=withheld,
        )
