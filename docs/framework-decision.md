# Framework decision (BAR-020)

**Status as of session B0 (Aug 12–13, 2026): ADK primary. The fallback branch
has not been taken.**

---

## What was decided

ADK is the runtime framework for the interviewer, reconciler, and extractor
agents.

This was **resolved by evidence, not re-verified**. The basis is the Aug 8
finding in `docs/antigravity/decision.md`: the Antigravity SDK's headless
multi-agent boolean assertion failed during verification. No day-1 Antigravity
verification was run for Baraza, because the evidence already existed and
re-running it would have burned a night to reproduce a known negative.

Antigravity is **not claimed** anywhere in the compliance matrix. A framework
name never appears in the matrix unless the code imports it — the same principle
that pulled the Model Armor claim from an earlier revision.

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

> **Not yet exercised.** The interview service is not yet built as of B0.
> This section is updated the moment the bounded attempt runs, whichever way it
> falls, and the compliance matrix is updated to match in the same commit.
>
> If the fallback is taken, the matrix's framework cell changes to name ADK for
> the reconciler and extractor and GenAI SDK for the interviewer, and this file
> records the trigger that fired, the measurement that fired it, and the wall
> time the attempt consumed.

## Why this is recorded either way

A framework choice that is only visible in an import graph is a claim a judge
has to reconstruct. Writing it down before the fork is live is the difference
between a decision and a rationalization.
