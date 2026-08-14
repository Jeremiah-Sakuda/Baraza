# Framework decision (BAR-020)

**Status as of session B4 (Aug 13, 2026): ADK primary, imported and
instantiated. The fallback branch has not been taken and its trigger never
fired.**

---

## What was decided

ADK is the runtime framework for the interviewer, reconciler, and extractor
agents.

**ADK was chosen without a published comparison, and that is now the whole of the
justification on offer.** BAR-020 originally resolved the framework question by
citing an Aug 8 finding — an Antigravity SDK headless multi-agent assertion that
failed verification — carried over from a sibling project. The source document
was never copied into this repository. What sat at `docs/antigravity/decision.md`
was a placeholder that described the finding from memory, said so, and stated its
own resolution: *if the original cannot be located, delete the citation and state
plainly that ADK was chosen without a published comparison, rather than write a
summary of a document nobody can check.* The original could not be located. The
placeholder has been deleted and this paragraph is what replaces it.

So: no comparative evaluation of agent frameworks is published here. ADK is used
because it was chosen; the honest ground for the choice is that it is Google's
first-party agent framework for a Google-run hackathon, and the repository can
demonstrate that it is genuinely imported and driven rather than named. That is a
weaker claim than "resolved by evidence" and it is the true one. Shipping a
second-hand negative assertion about another vendor's SDK — unverifiable by any
reader, in a submission judged by the vendor — would have been worse than
admitting there is no comparison.

Antigravity is **not claimed, and is no longer disparaged either.** A framework
name never appears in the compliance matrix unless the code imports it — the same
principle that pulled the Model Armor claim from an earlier revision — and the
same standard now applies to negative claims: this repository does not publish a
verification result it cannot show.

## The pre-committed fallback, and its trigger

Scoped to exactly one surface. If **either** of these holds:

- ADK's token-streaming path cannot satisfy BAR-330's first-visible-token < 1s
  acceptance criterion on the replay path, **or**
- ADK's session surface cannot satisfy BAR-334's per-turn externalization
  requirement,

within **one bounded attempt of ≤ 3 hours**, then the interview service — and
only the interview service — drops to direct GenAI SDK calls with our own turn
loop.

The reconciler and extractor remain on ADK regardless. Their surfaces are batch,
not streaming, and carry no equivalent risk.

## Which branch shipped

**The primary branch. The fallback was never triggered, because its trigger was
never tested.** Both statements matter, and conflating them would be the
dishonest version of this section.

**What shipped.** `src/baraza/agents.py` (session B4) imports
`google.adk.agents.LlmAgent` and `google.adk.tools.FunctionTool` and builds the
extractor, reconciler and interviewer as real ADK agents, each holding only the
tools its role requires, with peer and parent transfer disabled. `google-adk`
resolves to 2.6.2 in the build environment. `tests/unit/test_agents.py` asserts
`isinstance` against the genuine ADK class, so the claim degrades loudly rather
than silently if the import ever falls back to a stub.

**What did not happen.** The bounded ≤3h attempt described above was never run,
because the interview service was built on `src/baraza/llm.py` directly and
never attempted ADK's streaming path. So BAR-330's first-visible-token criterion
has not been measured against ADK, and the fallback was not *rejected on
evidence* — it was simply never reached. This file will not describe an untaken
branch as a passed test.

**What is still open.** The extractor is on the live path —
`src/baraza/ingest/extract.py` imports `baraza.agents`, and
`src/baraza/ingest/pipeline.py` constructs `AgentClaimExtractor` — so "ADK is the
runtime framework" now holds in the strong sense for one of the three surfaces.
The reconciler and interviewer are still built in `baraza.agents` and exercised
only by their tests; the reconcile Job and the interview service call `llm.py`
directly. That gap is stated rather than implied, here and in
`docs/compliance.md`, in the same terms.

**Correction history.** Through sessions B0–B3 this file and the compliance
matrix said no module imported ADK. That was accurate then and stopped being
accurate at B4; the statements were corrected in a single pass rather than
individually, which is why several documents change wording in the same commit.

## Why this is recorded either way

A framework choice that is only visible in an import graph is a claim a judge
has to reconstruct. Writing it down before the fork is live is the difference
between a decision and a rationalization.
