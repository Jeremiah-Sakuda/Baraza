# My AI partner keeps a file on me — and I made it show its work

*This post was created for the purposes of entering the All Things Agentic
Hackathon.* (Before publishing: confirm this sentence against the exact wording
the rules require and adjust if they specify different phrasing.)

---

Last week, mid-draft, my agent stopped me with this:

> On turn t-9 you committed: "Never state a number in a submission doc unless
> it traces to a metrics entry." Just now you said: "Just put a rough number in
> for now." Which governs — and is a draft a submission doc?

Both quotes were mine, verbatim, each with a pointer to the exact exchange
where I said it. The agent refused to silently keep the newer instruction. I
had to adjudicate — and I ended up splitting the rule into a conditional:
submitted artifacts must trace every number; drafts may carry a marked
placeholder. That conditional is now a ratified belief in the file the agent
keeps on me, it compiled into a policy rule that cites my own sentence as its
source, and the next draft followed it.

This is Baraza: a working partner whose model of you is built like a court
record instead of a cache. This post is about the two design decisions that
make that moment possible — **contradiction detection pointed at the user**,
and **an append-only log that gives memory due process** — and the bugs I hit
building it.

## The problem with "memory"

Every AI product is bolting on memory, and nearly every implementation shares
three properties:

1. It stores a **paraphrase** of you, not your words.
2. It is **silently mutable** — beliefs appear, change, and vanish without an
   audit trail.
3. When you contradict yourself, it keeps **whichever version came last**,
   without telling you it noticed.

Each of these is a trust failure. A paraphrase can't be verified against
anything. A mutable store can't prove a belief predates a dispute. And
last-writer-wins on your own contradictions means the system isn't modelling
you — it's modelling your most recent mood.

The fix I landed on is old technology from institutions that solved trust in
records centuries ago: evidence, jurisdiction, and an unalterable record.

## Beliefs as claims, with evidence

In Baraza, nothing about you is stored as free text. When you state a
preference, rule, or judgment in a session, it becomes a `Claim`:

- `quote` — your verbatim sentence. Mandatory. Not a summary.
- an anchor — `turn:t-N`, pointing at the registered source location of the
  exchange. An anchor that doesn't resolve is a **stop condition**, not a
  warning: an agent that fabricates evidence halts.
- `visibility` — defaults to private at append time. Reads route through a
  single `readable_by()` predicate that fails closed. (The quote text is
  structurally unreachable except through an audience-checked accessor; a
  compliance lint fails the build if anything outside the schema package
  touches the raw field.)
- a tier — `proposed` claims exist but do nothing. Only the approval flow can
  mark a claim `committed`, and only committed claims affect behavior.
  `rejected` retracts: out of retrieval, out of the ledger, out of every
  future agenda.

## The log that cannot be quietly rewritten

Claims append to a Firestore event log deployed with `create`-only security
rules — update and delete are refused at the rules layer, and a verification
script proves it live by attempting the forbidden writes. Every rendered state
(the belief graph, the doctrine, the agenda) is a **fold over the event log**.
There is no mutable store to drift.

This has a consequence that sounds like a limitation and is actually the
feature: *you cannot fix bad data by editing it.* You append a superseding
event. When I rejected a belief from my dossier, the retraction landed as its
own event, timestamped, next to the belief it retracts. The history of the
system's beliefs about me — including the wrong ones — is permanent, and
that's precisely why the current ones are credible.

My favorite demo is thirty seconds long: open the Firestore console, try to
edit an event document by hand, and watch the rules refuse. A log that cannot
be quietly rewritten, demonstrated by failing to quietly rewrite it.

## Contradiction detection, pointed at the user

Baraza's contradiction detector was originally built to ask a document corpus
what it disagrees with. Pointing it at the user's own statements turned out to
be the most interesting thing in the project.

Detection runs on-write, blocked on subject and predicate hint, temporally
gated — no O(n²) sweep. When a new claim collides with a committed one, a
divergence card fires with **both quotes and both anchors**, and the agent
refuses to overwrite the old rule until you resolve it. The resolutions are
where the user model gets its depth: almost every real contradiction I've hit
in dogfooding resolved into a *conditional* — "never X, except when Y" — and a
conditional is judgment-shaped in a way that "prefers concise" never is.

Due process, mapped completely: quotes are evidence, the approval flow is
jurisdiction, retraction is appeal, and the append-only log is the court
record. The agent argues with me, politely, citing my own words — because a
partner that silently absorbs my latest contradiction isn't adapting to me,
it's erasing me.

## Doctrine: policy with provenance

Committed beliefs compile into the session's operating policy — the doctrine —
and every rule carries the claim ID and quote that put it there. The
compilation is a fold: replay it and you get the same bytes. The doctrine diff
between two points in time names exactly which belief changed which rule.

One phrasing decision I want to be precise about, because it's where projects
like this usually overclaim: **the deterministic thing is the compilation, not
the model.** Same committed beliefs, same doctrine, every rule cited — that
part is replayable byte for byte. Whether the model then *complies* with a
cited rule is probabilistic, and the honest artifact is a doctrine diff plus
before/after outputs on a fixed task, side by side, with no line-level
causality claimed. The compliance rate is a number to be measured by a scripted
battery, and until that battery has run, it is exactly "not yet measured" —
which is what the repo's metrics file says, enforced by lint.

## Three bugs worth your time

**Sorting timestamps as strings.** The classic illustration
(`09:00-05:00` vs `08:00Z`) doesn't actually diverge — string order and
instant order agree, so a test built on it passes for the wrong reason. A pair
that genuinely diverges crosses a date boundary: `2026-05-01T20:00:00-05:00`
sorts *before* `2026-05-02T00:00:00Z` as text and is an hour *after* it as an
instant. Baraza compares integer epoch milliseconds everywhere; ISO strings
are serialization only, and a lint fails the build on string comparison of
instants. Related, subtler: a timestamp field with two plausible meanings
(when was this authored vs. when did the system record it) *will* be read with
the wrong one. Name the clock in the field name, and record facts instead of
inferring them.

**The honesty bug in the scheduler path.** An early job image hardcoded
`scheduled=True` on every event append — so a manual test run was recorded as
a scheduled one, in a log that cannot be edited. The fix records trigger
provenance at write time; the one mislabelled event stays in the log,
documented, because deleting history to fix a label would be the exact thing
the architecture exists to prevent. If your system counts scheduled activity
anywhere, the label has to be written by the code path that knows, not
defaulted.

**Model pins nobody had checked.** My original model pins were plausible
literals — and one named a model that does not exist in the Vertex catalog.
The models that do exist resolve at location `global`, not the regional
endpoint my deploy scripts assumed. Now: model IDs live in exactly one module,
a lint fails the build on a literal anywhere else, and a verification script
resolves every pin against live Vertex — no document in the repo may name a
model version until it exits green. The current pins, live-verified: Gemini
3.7 Flash for reasoning, Gemini 3.5 Flash for fast paths, on Vertex AI.

## The stack

Cloud Run (services + jobs), Firestore (the append-only log), Cloud Scheduler
(agent-initiated sessions, every run labelled `scheduled`), Vertex AI serving
Gemini via the GenAI SDK, the Agent Development Kit driving the extraction
agent with tools bound to real validation gates, Artifact Registry and Cloud
Build for images. Python 3.11+, property-based tests on the fold, and a
compliance script that fails the build on the invariants prose can't protect:
the visibility boundary, the single model-pin module, epoch-only time
comparison, and metrics provenance.

## Open the file it keeps on you

The bet behind Baraza is that "memory" is about to become a trust product.
Any personalized agent — in law, medicine, finance, or your pocket — will need
a user model its user can inspect, verify, and retract, and right-to-inspect
regulation points the same way. The mechanism is here today: every belief a
claim, every claim a quote, every quote in a log that refuses to be rewritten,
and nothing acting without your signature.

Adaptation with due process. Open the file it keeps on you.

*Repo: <https://github.com/Jeremiah-Sakuda/Baraza>*
