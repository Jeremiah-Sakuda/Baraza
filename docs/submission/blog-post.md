---
title: "Three defects that shaped an agent's architecture: an ISO-8601 sort, a fold that had to be stable, and a boundary that had to fail closed"
published: false
tags: python, googlecloud, ai, architecture
canonical_url: <SET-BEFORE-PUBLISHING>
---

> **This piece was created for the purposes of entering the All Things Agentic
> Hackathon.**
>
> *(Before publishing: confirm this sentence matches the exact wording the
> official rules require, on the live rules page. If the rules specify a
> particular phrasing, use theirs verbatim rather than this paraphrase.)*

---

I spent a build writing an agent that reads a decade of an organization's records
and finds what they disagree with. The interesting parts of that build were not
the model calls. They were three defects — one I had already shipped somewhere
else, one I could only catch with a property test, and one I designed out of
existence because I did not trust myself to remember a rule at every call site.

This post is about those three. The product is at the end, briefly, because it is
the least transferable part.

---

## 1. The ISO-8601 sort that kept a revoked grant alive

Here is a defect I have actually shipped, in a different project, in code that
had passing tests.

A resolver sorted records by timestamp to find the most recent state. The
timestamps were ISO-8601 strings. The sort was a string sort. Serialization was
byte-stable and the byte-stability tests were green. A grant that had been
revoked stayed active, because the revocation sorted *before* the grant that
preceded it.

The instinct, when you hear this, is that ISO-8601 sorts lexicographically in
instant order — and it does, **if every string carries the same offset.** Mixed
offsets break it. Here is the thing that took me embarrassingly long to get
right: the *obvious* counter-example does not actually diverge.

```
a = "2026-05-01T09:00:00-05:00"
b = "2026-05-01T08:00:00Z"

string order:  a > b      instant order:  a > b     # agree — no bug visible
```

Both orderings agree. A test built on that pair passes for the wrong reason, and
then you believe you have covered the case. To get divergence you have to cross a
date boundary:

```
a = "2026-05-01T20:00:00-05:00"   # == 2026-05-02T01:00:00Z
b = "2026-05-02T00:00:00Z"

string order:   a < b     ("2026-05-01…" sorts before "2026-05-02…")
instant order:  a > b     (a is one hour later)
```

That is the pair. `a` is the later instant and sorts first as text.

The rule I now enforce mechanically: **integer epoch milliseconds, UTC, are the
only comparison key in the system. ISO-8601 is a serialization format and is
never a sort key.** One module normalizes; nothing else is permitted to compare
instants.

Two design details that mattered more than the rule itself:

**Normalize by raising, not by guessing.** A value that cannot be resolved to an
unambiguous instant raises. A naive datetime with no offset is not silently
assumed to be UTC. A wrong instant is a silent correctness defect; a raised error
is a loud one, and loud is strictly better here.

**Disambiguate the two integer conventions explicitly.** The corpus contains bare
integers from a chat export (epoch *seconds*) and our own serialized values
(epoch *millis*). The normalizer splits on a plausible-seconds ceiling — roughly
1970 through 2286 — and reads values below it as seconds. That is a heuristic and
it is documented as one, in the module, at the constant. A heuristic you can find
is fine; a heuristic you cannot find is the same defect in a different costume.

Where this bites in an agent specifically: **interval overlap gating.** My
contradiction detector refuses to compare two claims whose validity intervals do
not overlap — two statements about consecutive fiscal years cannot contradict
each other, and that single gate removes the largest source of false positives
before any model call happens. That gate is arithmetic on epoch values. Run it on
strings under mixed offsets and it starts silently comparing the wrong pairs,
which does not crash — it just quietly makes the agent slightly wrong in a way no
test notices.

---

## 2. The property test: a fold has to be stable under offset permutation

The graph in this system is not stored. There is an append-only event log, and
every graph state is a **fold** over it. No mutable graph store, no cache that can
drift, no in-place mutation after the fold returns. Fixing bad data means
appending a superseding event, never editing one. If a graph looks wrong, the log
is the truth and the fold is the bug.

That design buys auditability, and it buys it entirely on the strength of one
property: **the fold is deterministic.** Events are ordered by
`(occurred_at_millis, event_id)` — an integer and a tiebreaker, never a string.

Determinism is not something you assert in a docstring. It is something you test,
and the test that catches the class of bug in section 1 is not an example-based
test. It is this:

> Take the golden event log. **Permute the serialized UTC offsets** across its
> events — rewrite each timestamp into a different but equivalent offset
> representation, changing the string while leaving the instant identical. Fold
> both logs. Assert the resulting graphs are identical.

This is a property test, and it is the right shape for the bug. An example-based
test asks "did this pair sort correctly?" and you write it using the pair you
already thought of — which, per section 1, is likely to be the pair that agrees.
The property test asks "is the output invariant under a transformation that must
not matter?" and it generates the pairs you did not think of. The offsets are the
transformation. Instant-equality is the invariant. Graph identity is the
assertion.

The generalization I would take to any event-sourced system: **for every field
where you have a canonical form and a serialization, there is a property test
saying the pipeline is invariant under re-serialization.** Timestamps and offsets
are the case everyone has. Unicode normalization, numeric precision, and map
iteration order are the same shape.

A second, cheaper property from the same family, which caught a real ordering
mistake: fold determinism also requires a **total** order. `occurred_at_millis`
alone is not total — two events can share a millisecond. The event ID tiebreaker
is what makes it total, and without it the fold is stable only until the first
collision, which will happen in production and not in your fixtures.

---

## 3. The boundary that fails closed by construction

This system holds testimony from a departing officer, and some of it is private.
The requirement was not "check permissions before rendering". The requirement was
that the boundary must hold **under carelessness** — because a predicate that
must be *remembered* at every read site is a predicate that will eventually be
forgotten at one, and the one that is forgotten will be in the error path at 2
a.m.

My first design was the ordinary one:

```python
# The version I threw away.
class Claim:
    quote: str          # plain attribute
    visibility: Visibility

# ...and every read site is expected to do this, from memory, forever:
if readable_by(claim, audience):
    render(claim.quote)
```

That is a boundary held by discipline. There are roughly a dozen read paths —
divergence detection, the ledger, the agenda generator, the question renderer,
the graph view, successor mode — and every one of them is a place to forget.

The version I shipped makes forgetting impossible rather than unlikely:

```python
@dataclass(frozen=True, slots=True)
class Claim:
    _quote_protected: str          # not part of the public surface
    visibility: Visibility

    def quote_for(self, audience: Audience) -> Optional[str]:
        """The only way to read the quote."""
        if not readable_by(self, audience):
            return None
        return self._quote_protected
```

`slots=True` is load-bearing. `claim.quote` does not exist, so code that reaches
for it raises `AttributeError` **at the access site**, with a traceback pointing
at the line that forgot. It does not return a default, it does not return the
text, and it does not fail somewhere else five frames later.

Three follow-on decisions made this actually hold:

**`readable_by` is defined exactly once,** and the assertion is mechanical:
`grep -rn "def readable_by" src/` returns exactly one line, checked in the gate.
A second definition is how a lattice acquires a second, subtly different meaning.

**The predicate returns `False` on garbage rather than raising.** An unrecognized
audience, a visibility that failed to deserialize, a claim missing the attribute
entirely — all return `False`. This is deliberate and it is the opposite of the
guidance in section 1. The reason: a boundary that *raises* can be caught by a
caller trying to be robust, and the swallowed-exception path is exactly where
leaks live. A normalizer should raise. A security predicate should deny.

**A build lint enforces the module boundary.** `_quote_protected` appearing
anywhere outside `src/…/schema/` fails the build with a `file:line`. Serialization
has to reach through the same door, so `to_dict()` lives inside the schema package
and every consumer of the raw dict is trusted — that is a real cost and it is
worth naming. But it is a *smaller* trusted surface than "every read site", which
is what the alternative bought.

And the part that makes the boundary a design rather than a filter: **counting is
separated from rendering.** The reconciler is allowed to count a claim the current
reader may not see toward a contradiction's existence — otherwise the contradiction
silently disappears for that reader, which is its own kind of lie. It is never
allowed to render that claim's text. So there are two operations:

```python
@dataclass(frozen=True, slots=True)
class RedactedClaim:
    """Structural coordinates only: no quote, no object literal, no anchor text."""
    claim_id: str
    subject_id: str
    predicate_hint: str
    valid_from: Optional[int]
    valid_until: Optional[int]
    readable: bool = False
```

An agenda item derived from a contradiction the interviewee cannot read is
**downgraded, not dropped** — it survives as an open-ended prompt with no quotes
attached. Dropping it would let the boundary silently shrink the agenda and make
the visibility choice look free when it is not.

---

## The build discipline, in two rules

**A lint nobody has seen fail is a lint that might not work.** I verified all four
invariant checks by writing a file that violated each one — a model-ID literal
outside the pin module, a protected-field access outside the schema package, an
ISO-string sort — running the audit, confirming each fired with a clickable
`file:line`, then deleting the file and confirming the audit returned green.

That exercise found a real bug in the lint itself. The first model-pin regex
matched the *word* "Gemini" wherever it opened a docstring. Requiring a `-<digit>`
version suffix fixed it. Worth writing down because the failure mode of an
over-broad lint is not noise — it is that someone adds an allowlist entry to
silence it, and the lint quietly stops covering the real case.

**`"not yet measured"` is a value.** Every number this project displays anywhere —
console, README, diagram, video — has to trace to a query, a committed metrics
entry, or a script a judge can run. The metrics file accepts exactly two shapes:
an object with a value, a provenance, a run ID and a date, or the literal string
`"not yet measured"`. There is no third form and no placeholder estimate. The
compliance script fails the build on anything else.

```json
"metrics": {
  "contradictions_detected_total": "not yet measured",
  "interview_first_token_ms_replay": "not yet measured"
}
```

Provenance is an enum with three values: `measured in-process`,
`measured deployed`, `not yet measured`. The distinction between the first two is
the one people fudge under deadline, and it is the one that makes a latency claim
either meaningful or fictional.

As I write this, **every entry in that file is `"not yet measured"`.** That is the
correct state before any measurement run has happened, and writing it down is
cheaper than the alternative, which is discovering in a demo that a number you
half-remember is wrong by an order of magnitude.

---

## What the thing actually is

Briefly, because it is the least transferable part.

Every May, student organizations lose their officers and most of what those
officers knew. The handover is a shared drive, a constitution that was scanned
crooked years ago, and three years of group chat.

The system reads that corpus — skew-scanned PDF, headerless spreadsheets, chat
export, minutes — extracts cited claims, and detects contradictions **on write**
rather than by sweeping. The arithmetic is the design: a few thousand claims
all-pairs is millions of comparisons, which at one model call per comparison is
not a system, it is a bill. So a new claim retrieves only claims sharing a
blocking key (subject ∪ objects ∪ predicate hint), gates that block on epoch
interval overlap, caps the survivors at 20, and makes one bounded call. One call
per claim written, not per pair. There is no vector database — claims are
embedded, the corpus is not, and brute-force top-k over a few thousand in-memory
vectors at this cardinality is not worth infrastructure.

The output is a ranked ledger of what the records disagree about, and an interview
agenda no human wrote. The agent then interviews the departing officer from that
agenda and — this is the part I actually built the rest for — when testimony
conflicts with the documentary record, it says so in the moment, with both
citations, and asks which is right. It does not adjudicate. A divergence between
memory and record is a question, not an accusation.

Approved answers become committed memory with an explicit visibility choice.
Resolution retracts: a closed contradiction leaves the ledger and every future
agenda permanently, so the next interview is shorter than the last. And when the
successor asks something the committed record does not cover, the system
**refuses** rather than synthesizing. That refusal has its own acceptance
criterion. A successor cannot distinguish a remembered fact from a fluent guess,
and a fluent guess about who can sign a cheque is worse than silence — silence is
recoverable, because they go and ask someone.

Infrastructure: Cloud Run Jobs for ingestion and nightly reconciliation, Cloud Run
services for the interview and successor surfaces, Firestore for the append-only
claim-event log, Cloud Scheduler for the unattended nightly pass, Gemini on Vertex
AI for the reasoning. Model identifiers live in exactly one module, and a lint
fails the build on a model string literal anywhere else.

---

## What is not done

Stating this because a post that only lists what worked is not a technical post.

- **The offline demo does not run yet**, and this is the largest gap. The
  cassette directory is empty, so the demo targets exit 2 before doing any work
  rather than falling through to invented model output. Everything downstream of
  a run is therefore unobserved: no event log, no citations for the anchor
  verifier to resolve, no behavioural probes for the landmine verifier (it
  confirms all 18 plants are present in the corpus and then says, correctly, that
  present is not the same as caught), and no transcripts for the adaptation
  scorer. Recording the cassettes is a supervised step that costs live calls.
- The pinned model identifiers are **pinned but unverified**. There is a script
  that resolves each against live Vertex and exits nonzero on any that does not,
  and until it has run green, no document in the repository — including this one
  — states which model version shipped. A pinned literal nobody checked is a
  plausible value where a verified one belongs.
- The **agent-framework claim is not yet backed by an import.** The framework is
  a declared dependency; no module imports it, and the runtime path today is the
  GenAI SDK on Vertex. The repository's own rule is that a framework is named
  only where the code uses it, so until that changes, it is not named.
- **Nothing is deployed** as of writing, so there is no Scheduler execution
  history, and the autonomy evidence I care most about — a diff between two
  ledger snapshots from two genuinely different nights, with a document landing
  in between — needs real nights to pass. A diff between snapshots taken minutes
  apart proves nothing, which is why it is scheduled rather than assumed.
- The authoritative requirements document was recovered only in part. Roughly 35
  requirement IDs exist as identifiers with no acceptance criteria, and I did not
  reconstruct them from memory. The compliance script exits **2** ("the audit
  could not run") rather than **1** ("the audit found problems") or **0**, so the
  gap reads as a gap instead of as a pass.

That last one is the discipline I would most want to keep. A green gate that
skipped its main check is worse than a red one, because only one of them gets
noticed.

---

*Repository: `<REPO-URL>` · Live instance: `<HOSTED-URL>` · Demo video:
`<VIDEO-URL>`*
